"""PyESD 방식 통계 다운스케일링 운영 실행 (numpy·scipy만 사용).

ECMWF EC46(주 1~6주)·SEAS5(월 1~6개월) 51개 멤버를 Open-Meteo에서 1.5° 예측인자 247점으로 받아,
  1) ECMWF 주·월 편차(모델 기후 기준)로 모델 평년값을 역산해 계통오차를 ERA5 기후로 맞추고
     (기온·이슬점·해면기압은 가법, 강수는 승법; 편차 변수가 없으면 보정 생략)
  2) 학습된 모형(models/*.npz: 변수별 EOF + 반경 250 km 평균 → 점별 능형회귀)으로
     한반도 0.25° 육지 412격자(북한 포함, 해안·하구 격자 포함)와 ASOS 66지점(제주 4 포함) 값을 멤버별로 예측하고
  3) 교차검증 잔차 σ 로 3분위 확률(낮음·비슷·높음, 1991–2020 기준)을 계산한다.

  python downscaling/forecast.py [--out site/data/latest/downscaling] [--demo]
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "pipeline"))
MODELS = HERE / "models"
PVARS = ["t2m", "d2m", "msl", "tp"]
# Open-Meteo 일별 / 주·월 변수 이름
DAILY = {"t2m": "temperature_2m_mean", "d2m": "dew_point_2m_mean", "msl": "pressure_msl_mean", "tp": "precipitation_sum"}
AGG = {"t2m": "temperature_2m", "d2m": "dew_point_2m", "msl": "pressure_msl", "tp": "precipitation"}
PRODUCTS = {"week": dict(model="ecmwf_ec46", days=46, block="weekly", name="EC46"),
            "month": dict(model="ecmwf_seas5", days=200, block="monthly", name="SEAS5")}


# ---------------------------------------------------------------- 자료 입수
def fetch(points, scale):
    """주·월 편차 변수 지원 여부를 첫 지점으로 확인(400이면 기온·강수만, 그래도 안 되면 생략)한 뒤 전 지점 요청."""
    import openmeteo as om
    from config import SEASONAL_URL, TIMEZONE
    P = PRODUCTS[scale]
    full = [f"{AGG[v]}_{s}" for v in PVARS for s in ("mean", "anomaly")]
    lite = [f"{AGG[v]}_{s}" for v in ("t2m", "tp") for s in ("mean", "anomaly")]
    agg = None
    for cand in (full, lite):
        params = dict(latitude=f"{points[0][0]:.3f}", longitude=f"{points[0][1]:.3f}", models=P["model"],
                      daily=",".join(DAILY.values()), forecast_days=P["days"], timezone=TIMEZONE)
        params[P["block"]] = ",".join(cand)
        try:
            om.get_json(SEASONAL_URL, params)
            agg = cand
            break
        except RuntimeError as e:
            if "400" not in str(e):
                raise
            print(f"  ! {P['block']} 변수 일부 미지원: {str(e)[:120]}")
    kw = {P["block"]: agg} if agg else {}
    print(f"  {P['name']}: {P['block']} = {agg}")
    return om.fetch_seasonal(points, P["model"], list(DAILY.values()), forecast_days=P["days"], **kw)


def to_arrays(resp):
    import openmeteo as om
    dates = [dt.date.fromisoformat(t) for t in resp[0]["daily"]["time"]]
    X = {}
    for v, name in DAILY.items():
        arrs = [om.members(r.get("daily"), name) for r in resp]
        nm = max(a.shape[0] for a in arrs if a is not None)
        out = np.full((nm, len(dates), len(resp)), np.nan)
        for j, a in enumerate(arrs):
            if a is not None:
                out[:a.shape[0], :a.shape[1], j] = a
        X[v] = out                                     # (member, day, pt)
    return dates, X


def blocks(resp, dates, scale):
    """API 주·월 기간(ECMWF 정의)을 그대로 쓰고, 일별 자료가 기간 전체를 덮는 것만 남긴다."""
    b = resp[0].get(PRODUCTS[scale]["block"]) or {}
    d2i = {d: i for i, d in enumerate(dates)}
    out = []
    if scale == "week":
        starts = [dt.date.fromisoformat(t[:10]) for t in b.get("time", [])]
        if not starts:   # 주별 자료가 없으면 발표 다음 월요일부터
            s0 = dates[0] + dt.timedelta(days=(7 - dates[0].weekday()) % 7)
            starts = [s0 + dt.timedelta(days=7 * k) for k in range(6)]
        for k, s in enumerate(starts):
            e = s + dt.timedelta(days=6)
            if s in d2i and e in d2i:
                out.append(dict(key=s.isoformat(), start=s, end=e, label=f"{s:%m/%d}~{e:%m/%d}"))
    else:
        months = [t[:7] for t in b.get("time", [])] or sorted({d.isoformat()[:7] for d in dates})
        for mk in months:
            s = dt.date.fromisoformat(mk + "-01")
            e = (s.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            if s in d2i and e in d2i:
                out.append(dict(key=mk, start=s, end=e, label=f"{s.year}년 {s.month}월"))
    for p in out:
        p["i0"], p["i1"] = d2i[p["start"]], d2i[p["end"]]
        mid = p["start"] + (p["end"] - p["start"]) / 2
        p["doy"], p["month"] = mid.timetuple().tm_yday, mid.month
    return out


def api_values(resp, scale, v, key):
    """ECMWF 주·월 평균(A)과 편차(a), 지점별"""
    n = len(resp); A, a = np.full(n, np.nan), np.full(n, np.nan)
    for i, r in enumerate(resp):
        b = r.get(PRODUCTS[scale]["block"]) or {}
        times = [t[:len(key)] for t in b.get("time", [])]
        if key not in times:
            continue
        j = times.index(key)
        for arr, s in ((A, "mean"), (a, "anomaly")):
            x = b.get(f"{AGG[v]}_{s}")
            if x is not None and j < len(x) and x[j] is not None:
                arr[i] = x[j]
    return A, a


# ---------------------------------------------------------------- 계통오차 보정
def bias_correct(X, resp, scale, per, era5_daily):
    """기간별 멤버 평균값(일 단위)을 ERA5 기후 기준으로 맞춘다.
    모델 기후 cm: 가법 cm = ens − a,  승법(강수) cm = ens·(A−a)/A.  보정: X − (cm − era) 또는 X·era/cm"""
    days = np.array([(per["start"] + dt.timedelta(days=k)).timetuple().tm_yday for k in range((per["end"] - per["start"]).days + 1)])
    out, info = {}, {}
    for v in PVARS:
        x = np.nanmean(X[v][:, per["i0"]:per["i1"] + 1, :], axis=1)          # (member, pt) 기간 일평균
        era = era5_daily[v][days - 1].mean(0)                                 # (pt,)
        A, a = api_values(resp, scale, v, per["key"]) if resp is not None else (None, None)
        ens = np.nanmean(x, 0)
        if a is None or not np.isfinite(a).any():
            out[v] = x; info[v] = "none"; continue
        if v != "tp":
            cm = ens - a
            d = np.where(np.isfinite(cm), cm - era, 0.0)
            out[v] = x - d[None]; info[v] = f"add {np.nanmean(d):+.2f}"
        else:
            with np.errstate(invalid="ignore", divide="ignore"):
                f = (A - a) / A
                cm = ens * f
                fac = era / cm
            fac = np.where(np.isfinite(fac) & (fac > 0.2) & (fac < 5) & (A > 1e-6), fac, 1.0)
            out[v] = x * fac[None]; info[v] = f"mul ×{np.nanmean(fac):.2f}"
    return out, info


# ---------------------------------------------------------------- 다운스케일
def load_model(kind, var, scale):
    return dict(np.load(MODELS / f"{kind}_{var}_{scale}.npz", allow_pickle=False))


def predict(M, fields, month, key):
    """fields: {v: (member, 247) ERA5 기후 기준 편차(강수 sqrt)} -> (member, npt) 편차"""
    pcs = []
    for v in PVARS:
        Z = np.nan_to_num((fields[v] - M[f"m{month}_mu_{v}"]) / M[f"m{month}_sd_{v}"])
        pcs.append(Z @ M[f"m{month}_eof_{v}"].T / M[f"m{month}_pcsd_{v}"])
    PC = np.concatenate(pcs, 1)                                              # (member, k)
    L = np.stack([fields[v] @ M["W"].T for v in M["local"]], 1)              # (member, m, npt)
    c = M[f"m{month}_coef"]                                                  # (npt, k+m+1)
    k = PC.shape[1]
    return PC @ c[:, :k].T + np.einsum("bmj,jm->bj", L, c[:, k:-1]) + c[:, -1][None]


def downscale(corr, per, scale, kind, var):
    M = load_model(kind, var, scale)
    key = per["doy"] - 1 if scale == "week" else per["month"] - 1
    fields = {}
    for v in PVARS:
        x = np.sqrt(np.clip(corr[v], 0, None)) if v == "tp" else corr[v]
        fields[v] = x - M[f"xclim_{v}"][key][None]
    m = per["month"]
    mu = predict(M, fields, m, key)
    s = M["sigma"][m]
    pb = norm.cdf((M["q33"][m] - mu) / s).mean(0)
    pa = 1 - norm.cdf((M["q67"][m] - mu) / s).mean(0)
    ycl = M["yclim"][key]
    r = dict(anom=mu.mean(0), spread=mu.std(0), below=pb, above=pa, near=1 - pb - pa, r_cv=M["r_cv"][m])
    if var == "T":
        r["value"] = ycl + mu.mean(0)
    else:
        val = np.clip(ycl[None] + mu, 0, None) ** 2                           # mm/일
        normal = M["normal_doy"][key] if "normal_doy" in M else M["normal"][m]
        r["value"] = val.mean(0); r["normal"] = normal
        r["pct"] = 100 * val.mean(0) / np.maximum(normal, 0.05)
    return r, M


# ---------------------------------------------------------------- 실행
def run(scale, pred, era5_daily, demo=False):
    pts = list(zip(pred["lat"].tolist(), pred["lon"].tolist()))
    if demo:
        resp, dates, X = None, *demo_input(pred, era5_daily, scale)
        pers = demo_blocks(dates, scale)
    else:
        resp = fetch(pts, scale)
        dates, X = to_arrays(resp)
        pers = blocks(resp, dates, scale)
    res = []
    for p in pers:
        corr, info = bias_correct(X, resp, scale, p, era5_daily)
        item = dict(period=p["key"], label=p["label"], start=p["start"].isoformat(), end=p["end"].isoformat(), bias=info)
        for kind in ("grid", "asos"):
            for var in ("T", "P"):
                r, M = downscale(corr, p, scale, kind, var)
                item[f"{kind}_{var}"] = r
        res.append(item)
        print(f"  {scale} {p['label']}: 보정 {info}")
    return dict(issued=str(dates[0]), model=PRODUCTS[scale]["name"], periods=res)


def demo_input(pred, era5_daily, scale):
    """네트워크 없이 시험: ERA5 기후값 + 무작위 편차 (51멤버)"""
    rng = np.random.default_rng(0)
    d0 = dt.date.today()
    nd = PRODUCTS[scale]["days"]
    dates = [d0 + dt.timedelta(days=k) for k in range(nd)]
    doy = np.array([d.timetuple().tm_yday for d in dates])
    X = {}
    for v in PVARS:
        base = era5_daily[v][doy - 1][None]
        sig = {"t2m": 2.0, "d2m": 2.0, "msl": 3.0, "tp": 0}[v]
        X[v] = base + rng.normal(0, 1, (51, nd, base.shape[2])) * sig if v != "tp" else base * rng.gamma(0.8, 1.25, (51, nd, base.shape[2]))
    return dates, X


def demo_blocks(dates, scale):
    d2i = {d: i for i, d in enumerate(dates)}
    if scale == "week":
        s0 = dates[0] + dt.timedelta(days=(7 - dates[0].weekday()) % 7)
        cand = [(s0 + dt.timedelta(days=7 * k), s0 + dt.timedelta(days=7 * k + 6)) for k in range(6)]
        pers = [dict(key=s.isoformat(), start=s, end=e, label=f"{s:%m/%d}~{e:%m/%d}") for s, e in cand]
    else:
        pers = []
        for mk in sorted({d.isoformat()[:7] for d in dates}):
            s = dt.date.fromisoformat(mk + "-01"); e = (s.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            pers.append(dict(key=mk, start=s, end=e, label=f"{s.year}년 {s.month}월"))
    pers = [p for p in pers if p["start"] in d2i and p["end"] in d2i]
    for p in pers:
        p["i0"], p["i1"] = d2i[p["start"]], d2i[p["end"]]
        mid = p["start"] + (p["end"] - p["start"]) / 2
        p["doy"], p["month"] = mid.timetuple().tm_yday, mid.month
    return pers


def to_json(out, products):
    """사이트용 JSON: 격자(412)·지점(66) 좌표는 한 번, 값은 기간별 배열. south_mean = 제주 제외 62지점 평균"""
    out.mkdir(parents=True, exist_ok=True)
    g, a = load_model("grid", "T", "week"), load_model("asos", "T", "week")
    meta = dict(grid=dict(lat=g["lat"].round(2).tolist(), lon=g["lon"].round(2).tolist()),
                asos=dict(stn=a["stn"].tolist(), name=a["name"].tolist(), lat=a["lat"].round(4).tolist(), lon=a["lon"].round(4).tolist(),
                          jeju=[int(v) for v in a["jeju"]] if "jeju" in a else [0] * len(a["stn"])))
    south = np.asarray(meta["asos"]["jeju"]) == 0   # 남한 평균 = 제주 제외 62지점
    rnd = lambda x, nd=2: [None if not np.isfinite(v) else round(float(v), nd) for v in np.asarray(x)]  # noqa: E731
    pct = lambda x: [None if not np.isfinite(v) else int(round(100 * float(v))) for v in np.asarray(x)]  # noqa: E731
    js = dict(meta=meta, generated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), products={})
    for scale, P in products.items():
        per = []
        for it in P["periods"]:
            d = dict(period=it["period"], label=it["label"], start=it["start"], end=it["end"], bias=it["bias"])
            for k in ("grid_T", "grid_P", "asos_T", "asos_P"):
                r = it[k]
                d[k] = {f: (pct(r[f]) if f in ("below", "near", "above") else rnd(r[f], 0 if f == "pct" else 2)) for f in r}
            T, Pp = it["asos_T"], it["asos_P"]
            d["south_mean"] = dict(n=int(south.sum()),
                T_anom=round(float(np.nanmean(np.asarray(T["anom"])[south])), 2),
                T_above=int(round(100 * float(np.nanmean(np.asarray(T["above"])[south])))),
                T_below=int(round(100 * float(np.nanmean(np.asarray(T["below"])[south])))),
                P_pct=int(round(float(np.nanmean(np.asarray(Pp["pct"])[south])))),
                P_above=int(round(100 * float(np.nanmean(np.asarray(Pp["above"])[south])))),
                P_below=int(round(100 * float(np.nanmean(np.asarray(Pp["below"])[south])))))
            per.append(d)
        js["products"][scale] = dict(issued=P["issued"], model=P["model"], periods=per)
    (out / "downscaling.json").write_text(json.dumps(js, ensure_ascii=False, separators=(",", ":")))
    # ASOS 지점 표 (CSV)
    rows = ["product,period,stn,name,jeju,T_anom,T_value,T_below,T_near,T_above,P_value,P_pct,P_below,P_near,P_above"]
    for scale, P in products.items():
        for it in P["periods"]:
            T, Pp = it["asos_T"], it["asos_P"]
            for j, s in enumerate(meta["asos"]["stn"]):
                rows.append(",".join(map(str, [scale, it["period"], s, meta["asos"]["name"][j], meta["asos"]["jeju"][j],
                    f"{T['anom'][j]:.2f}", f"{T['value'][j]:.2f}", f"{T['below'][j]:.2f}", f"{T['near'][j]:.2f}", f"{T['above'][j]:.2f}",
                    f"{Pp['value'][j]:.2f}", f"{Pp['pct'][j]:.0f}", f"{Pp['below'][j]:.2f}", f"{Pp['near'][j]:.2f}", f"{Pp['above'][j]:.2f}"])))
    (out / "asos66_downscaled.csv").write_text("\n".join(rows) + "\n", encoding="utf-8-sig")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site" / "data" / "latest" / "downscaling"))
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--maps", action="store_true", help="PNG 지도도 만든다 (matplotlib 필요)")
    a = ap.parse_args()
    pred = dict(np.load(MODELS / "predictors.npz"))
    era5_daily = {v: pred[f"era5_daily_{v}"] for v in PVARS}
    products = {s: run(s, pred, era5_daily, a.demo) for s in ("week", "month")}
    out = Path(a.out)
    to_json(out, products)
    if a.maps:
        import maps
        maps.draw_all(out, products)
    print("ok", out)


if __name__ == "__main__":
    main()
