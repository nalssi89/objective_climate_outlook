"""한반도 객관기후예측(1개월·3개월) 산출.

    python pipeline/outlook.py            # Open-Meteo 실자료
    python pipeline/outlook.py --demo     # 네트워크 없이 합성 자료로 전체 흐름 시험

산출물 (site/data/latest/)
    manifest.json        발표 정보, 기간, 요소
    map_1m.json/map_3m.json   격자별 앙상블 평균·편차·3분위 확률·임계값 초과확률
    points/<i>.json      격자점별 일별 앙상블 분포(시계열), 기간별 표, 멤버 값
"""
import argparse
import datetime as dt
import json
import shutil
import warnings
from pathlib import Path

import numpy as np

import openmeteo as om
from climatology import Climatology, default_shape
from config import DEFAULT_SPREAD, EC46_WEEKLY_PROBS, PRODUCTS, VARIABLES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data" / "latest"
KST = dt.timezone(dt.timedelta(hours=9))
PCTS = [10, 25, 50, 75, 90]
warnings.filterwarnings("ignore", category=RuntimeWarning)  # 결측 구간 nan 통계 경고


# ---------------------------------------------------------------- 기간 정의
def define_periods(key, dates, weekly_block, issue):
    d2i = {d: i for i, d in enumerate(dates)}
    periods = []
    if key == "1m":
        starts = []
        if weekly_block and weekly_block.get("time"):
            starts = [dt.date.fromisoformat(t[:10]) for t in weekly_block["time"]]
        starts = [s for s in starts if s > issue and s + dt.timedelta(days=6) in d2i]
        if not starts:  # 주 경계를 알 수 없으면 다음 월요일부터
            s = issue + dt.timedelta(days=(7 - issue.weekday()) % 7 or 7)
            starts = [s + dt.timedelta(days=7 * k) for k in range(6)]
            starts = [x for x in starts if x + dt.timedelta(days=6) in d2i]
        for k, s in enumerate(starts[:4]):
            e = s + dt.timedelta(days=6)
            periods.append({"id": f"w{k + 1}", "kind": "week", "label": f"{k + 1}주", "start": s, "end": e})
        if len(periods) == 4:
            periods.append({"id": "m1", "kind": "month", "label": "1개월(1–4주)", "start": periods[0]["start"],
                            "end": periods[-1]["end"], "parts": [p["id"] for p in periods]})
    else:
        y, m = (issue.year, issue.month) if issue.day == 1 else _add_month(issue.year, issue.month, 1)
        for k in range(3):
            yy, mm = _add_month(y, m, k)
            s = dt.date(yy, mm, 1)
            e = dt.date(*_add_month(yy, mm, 1), 1) - dt.timedelta(days=1)
            if s in d2i and e in d2i:
                periods.append({"id": f"m{k + 1}", "kind": "month", "label": f"{mm}월", "start": s, "end": e})
        if len(periods) == 3:
            periods.append({"id": "s", "kind": "season", "label": "3개월(" + "·".join(p["label"][:-1] for p in periods) + "월)",
                            "start": periods[0]["start"], "end": periods[-1]["end"], "parts": [p["id"] for p in periods]})
    for p in periods:
        p["i0"], p["i1"] = d2i[p["start"]], d2i[p["end"]]
    return periods


def _add_month(y, m, k):
    m0 = m - 1 + k
    return y + m0 // 12, m0 % 12 + 1


# ---------------------------------------------------------------- 보조
def stack_members(resp, var):
    arrs = [om.members(r.get("daily"), var) for r in resp]
    nm = max((a.shape[0] for a in arrs if a is not None), default=0)
    nd = max((a.shape[1] for a in arrs if a is not None), default=0)
    out = np.full((len(resp), nm, nd), np.nan)
    for i, a in enumerate(arrs):
        if a is not None:
            out[i, :a.shape[0], :a.shape[1]] = a
    return out


def aggregate(D, i0, i1, agg):
    blk = D[:, :, i0:i1 + 1]
    valid = np.isfinite(blk).sum(axis=2)
    with np.errstate(invalid="ignore"):
        v = np.nanmean(blk, axis=2) if agg == "mean" else np.nansum(blk, axis=2)
    v[valid < 0.9 * blk.shape[2]] = np.nan
    return v


def api_period_values(resp, block, prefix, period):
    """ECMWF 가 직접 산출한 주/월 평균·편차 (지점별)."""
    n = len(resp)
    A, a = np.full(n, np.nan), np.full(n, np.nan)
    if not prefix:
        return A, a
    for i, r in enumerate(resp):
        b = r.get(block)
        if not b or "time" not in b:
            continue
        key = period["start"].isoformat()[: 7 if block == "monthly" else 10]
        times = [t[: len(key)] for t in b["time"]]
        if key not in times:
            continue
        j = times.index(key)
        for arr, suffix in ((A, "_mean"), (a, "_anomaly")):
            v = b.get(prefix + suffix)
            if v is not None and j < len(v) and v[j] is not None:
                arr[i] = v[j]
    return A, a


def r2(x, nd=2):
    if isinstance(x, np.ndarray):
        return [None if not np.isfinite(v) else round(float(v), nd) for v in x]
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def pct(x):
    return [None if not np.isfinite(v) else int(round(100 * float(v))) for v in x]


# ---------------------------------------------------------------- 핵심 산출
def monthly_clim_rates(resp, dates, D, V):
    """SEAS5 월별 평균·편차로 역산한 월별 모델 기후값의 '일 단위' 값 {YYYY-MM: (지점,)}.

    API 월값과 일별 멤버 집계의 정의(단위)가 달라도 성립하도록 비율로 환산한다.
    """
    rates = {}
    b = resp[0].get("monthly") or {}
    for t in b.get("time", []):
        mk = t[:7]
        idx = [i for i, d in enumerate(dates) if d.isoformat()[:7] == mk and i < D.shape[2]]
        if len(idx) < 3:
            continue
        with np.errstate(invalid="ignore"):
            daily_ens = np.nanmean(D[:, :, idx], axis=(1, 2))  # 일평균(강수는 일합계의 평균)
        p = {"start": dt.date.fromisoformat(mk + "-01")}
        A, a = api_period_values(resp, "monthly", V["monthly"], p)
        if V["mode"] == "add":
            r = daily_ens - a
        else:
            with np.errstate(invalid="ignore", divide="ignore"):
                f = (A - a) / A
            f[~np.isfinite(f) | (f <= 0.05) | (f > 20)] = np.nan
            r = daily_ens * f
        rates[mk] = r
    return rates


def compute_product(key, resp, points, clim, issue, clim_rates=None):
    """clim_rates: 3개월(SEAS5) 산출에서 얻은 월별 모델 기후 일값 — 1개월 전망의 승법 요소 평년값에 사용."""
    P = PRODUCTS[key]
    dates = [dt.date.fromisoformat(t) for t in resp[0]["daily"]["time"]]
    periods = define_periods(key, dates, resp[0].get("weekly"), issue)
    if not periods:
        raise RuntimeError(f"{key}: 예측기간을 구성할 수 없음 (일수 {len(dates)})")
    block = "weekly" if key == "1m" else "monthly"
    fields, tables, members_out, daily_out, rates_out = {}, {}, {}, {}, {}
    pts = np.asarray(points)
    n = len(points)

    for vk, V in VARIABLES.items():
        D = stack_members(resp, V["daily"])
        if D.size == 0:
            print(f"  ! {key}/{vk}: 일별 멤버 자료 없음 -> 건너뜀")
            continue
        nmem = D.shape[1]
        prefix = V["weekly"] if key == "1m" else V["monthly"]
        fields[vk], tables[vk], members_out[vk] = {}, {}, {}
        base_clim = {}
        if key == "3m" and V["monthly"]:
            rates_out[vk] = monthly_clim_rates(resp, dates, D, V)
        rates = (clim_rates or {}).get(vk, {})

        for p in periods:
            X = aggregate(D, p["i0"], p["i1"], V["agg"])  # (n, nmem)
            with np.errstate(invalid="ignore"):
                ens = np.nanmean(X, axis=1)
            kind = p["kind"]
            # ---- 1) 평년(모델 기후) 평균
            era = clim.stats(vk, p["start"], p["end"], V["agg"], V["mode"]) if clim else None
            era_mean = clim.idw(era[0], pts) if era else np.full(n, np.nan)
            src = np.array(["era5"] * n, dtype=object)
            if "parts" in p:
                parts = [base_clim[q] for q in p["parts"]]
                w = np.array([(next(x for x in periods if x["id"] == q)["i1"] - next(x for x in periods if x["id"] == q)["i0"] + 1)
                              for q in p["parts"]], dtype=float)
                stack = np.array([c[0] for c in parts])
                cm = stack.sum(axis=0) if V["agg"] == "sum" else (stack * w[:, None]).sum(axis=0) / w.sum()
                model_ok = np.all([c[1] == "model" for c in parts], axis=0)
            elif key == "1m" and V["mode"] == "mul":
                # EC46 주별 강수·풍속 평균은 일별 멤버 집계와 정의가 달라 비율 역산이 불안정 →
                # 같은 IFS 계열인 SEAS5 의 월별 모델 기후값(일 단위)을 주 기간에 합산/평균
                days = [dates[i].isoformat()[:7] for i in range(p["i0"], p["i1"] + 1)]
                if days and all(m in rates for m in days):
                    stack = np.array([rates[m] for m in days])
                    cm = stack.sum(axis=0) if V["agg"] == "sum" else stack.mean(axis=0)
                else:
                    cm = np.full(n, np.nan)
                model_ok = np.isfinite(cm)
            else:
                A, a = api_period_values(resp, block, prefix, p)
                if V["mode"] == "add":
                    cm = ens - a
                else:
                    with np.errstate(invalid="ignore", divide="ignore"):
                        ratio = A / (A - a)
                    bad = ~np.isfinite(ratio) | (ratio <= 0.05) | (ratio > 20) | ((A - a) <= 1e-6)
                    with np.errstate(invalid="ignore", divide="ignore"):
                        cm = np.where(bad, np.nan, ens / ratio)
                model_ok = np.isfinite(cm)
            clim_mean = np.where(model_ok, cm, era_mean)
            src[model_ok] = "model"
            base_clim[p["id"]] = (clim_mean, src)

            # ---- 2) 평년 분포 형태 → 3분위·10/90% 경계
            if era is not None:
                shape = clim.idw(era[1], pts)
            else:
                shape = np.full((n, 5), np.nan)
            fallback = default_shape(V["mode"], DEFAULT_SPREAD[vk][kind])
            bad = ~np.all(np.isfinite(shape), axis=1)
            shape[bad] = fallback
            if V["mode"] == "add":
                B = clim_mean[:, None] + shape
            else:
                B = clim_mean[:, None] * shape
            B = np.sort(B, axis=1)

            # ---- 3) 확률 (멤버 계수)
            ok = np.isfinite(X)
            cnt = np.maximum(ok.sum(axis=1), 1)

            def prob(mask):
                return (mask & ok).sum(axis=1) / cnt

            below = prob(X < B[:, [1]])
            above = prob(X > B[:, [3]])
            near = 1 - below - above
            f = {
                "mean": r2(ens), "clim": r2(clim_mean),
                "anom": r2(ens - clim_mean),
                "spread": r2(np.nanstd(X, axis=1)),
                "below": pct(below), "near": pct(near), "above": pct(above),
                "gt_median": pct(prob(X > B[:, [2]])),
                "lt_p10": pct(prob(X < B[:, [0]])), "gt_p90": pct(prob(X > B[:, [4]])),
                "p10": r2(np.nanpercentile(X, 10, axis=1)), "p90": r2(np.nanpercentile(X, 90, axis=1)),
                "clim_src": ["model" if s == "model" else "era5" for s in src],
            }
            if V["mode"] == "mul":
                with np.errstate(invalid="ignore", divide="ignore"):
                    f["anom_pct"] = r2(100 * ens / clim_mean, 0)
            thr = {}
            T = V["thresholds"]
            for t in T.get("anom", []):
                k = f"anom_{'gt' if t > 0 else 'lt'}{t:+g}"
                thr[k] = pct(prob(X - clim_mean[:, None] > t) if t > 0 else prob(X - clim_mean[:, None] < t))
            for t in T.get("ratio", []):
                lim = clim_mean[:, None] * t / 100
                thr[f"ratio_{'gt' if t > 100 else 'lt'}{t}"] = pct(prob(X > lim) if t > 100 else prob(X < lim))
            for t in T.get("abs", {}).get(kind, []):
                thr[f"abs_gt{t}"] = pct(prob(X > t))
            f["thr"] = thr
            fields[vk][p["id"]] = f

            tables[vk][p["id"]] = {
                "q": [r2(np.nanpercentile(X, q, axis=1)) for q in PCTS],
                "b": [r2(B[:, j]) for j in range(5)],
            }
            if "parts" not in p:
                A, a = api_period_values(resp, block, prefix, p)
                tables[vk][p["id"]]["api_mean"], tables[vk][p["id"]]["api_anom"] = r2(A), r2(a)
            members_out[vk][p["id"]] = X

        # ---- 일별 앙상블 분포 (시계열)
        nd = min(D.shape[2], periods[-1]["i1"] + 1)
        Dd = D[:, :, :nd]
        with np.errstate(invalid="ignore"):
            q = np.nanpercentile(Dd, [0, 10, 25, 50, 75, 90, 100], axis=1)  # (7, n, nd)
            mean = np.nanmean(Dd, axis=1)
        dd = {"q": q, "mean": mean}
        if V["agg"] == "sum":
            # 누적은 첫 예측기간 시작일부터
            cum = np.full(Dd.shape, np.nan)
            i0 = periods[0]["i0"]
            cum[:, :, i0:] = np.nancumsum(Dd[:, :, i0:], axis=2)
            dd["cq"] = np.nanpercentile(cum, [10, 25, 50, 75, 90], axis=1)
            dd["cmean"] = np.nanmean(cum, axis=1)
        if clim:
            norm = clim.daily_normal(vk, dates[:nd])
            dd["normal"] = clim.idw(norm, pts) if norm is not None else None
        daily_out[vk] = dd
        print(f"  {key}/{vk}: members={nmem}, periods={len(periods)}")

    # EC46 직접 제공 주별 확률
    ec_probs = None
    if key == "1m":
        ec_probs = []
        for r in resp:
            b = r.get("weekly") or {}
            row = {}
            for p in periods:
                if p["kind"] != "week" or "time" not in b:
                    continue
                ts = [t[:10] for t in b["time"]]
                s = p["start"].isoformat()
                if s in ts:
                    j = ts.index(s)
                    row[p["id"]] = {k: b[k][j] for k in EC46_WEEKLY_PROBS if b.get(k) and b[k][j] is not None}
            ec_probs.append(row)

    return {
        "key": key, "periods": periods, "dates": dates[: periods[-1]["i1"] + 1], "fields": fields, "rates": rates_out,
        "tables": tables, "members": members_out, "daily": daily_out, "ec_probs": ec_probs,
        "nmem": {vk: int(np.max(np.isfinite(m[periods[0]["id"]]).sum(axis=1))) for vk, m in members_out.items()},
    }


# ---------------------------------------------------------------- 저장
def period_meta(periods):
    return [{"id": p["id"], "kind": p["kind"], "label": p["label"], "start": p["start"].isoformat(),
             "end": p["end"].isoformat()} for p in periods]


def write_outputs(products, points, demo, clim):
    tmp = OUT.parent / "latest.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "points").mkdir(parents=True)
    now = dt.datetime.now(KST)
    manifest = {
        "issued": now.isoformat(timespec="minutes"),
        "demo": demo,
        "climatology": "ERA5 1991–2020 (Open-Meteo archive)" if clim else "기본 변동폭 가정(ERA5 캐시 없음)",
        "variables": {k: {kk: V[kk] for kk in ("name", "unit", "agg", "mode")} | {"thresholds": V["thresholds"]}
                      for k, V in VARIABLES.items()},
        "products": {},
    }
    for key, R in sorted(products.items()):
        P = PRODUCTS[key]
        manifest["products"][key] = {
            "name": P["name"], "model": P["model_name"], "periods": period_meta(R["periods"]),
            "start": R["dates"][0].isoformat(), "end": R["dates"][-1].isoformat(), "members": R["nmem"],
        }
        json.dump({"key": key, "periods": period_meta(R["periods"]), "fields": R["fields"]},
                  open(tmp / f"map_{key}.json", "w"), ensure_ascii=False, separators=(",", ":"))

    for i, (la, lo) in enumerate(points):
        out = {"lat": la, "lon": lo}
        for key, R in products.items():
            pr = {"dates": [d.isoformat() for d in R["dates"]], "daily": {}, "periods": {}}
            for vk, dd in R["daily"].items():
                e = {"min": r2(dd["q"][0][i]), "p10": r2(dd["q"][1][i]), "p25": r2(dd["q"][2][i]),
                     "p50": r2(dd["q"][3][i]), "p75": r2(dd["q"][4][i]), "p90": r2(dd["q"][5][i]),
                     "max": r2(dd["q"][6][i]), "mean": r2(dd["mean"][i])}
                if "cq" in dd:
                    e["cum"] = {f"p{p}": r2(dd["cq"][j][i], 1) for j, p in enumerate([10, 25, 50, 75, 90])}
                    e["cum"]["mean"] = r2(dd["cmean"][i], 1)
                if dd.get("normal") is not None:
                    e["normal"] = r2(dd["normal"][i])
                pr["daily"][vk] = e
            for vk, per in R["fields"].items():
                pr["periods"][vk] = {}
                for pid, f in per.items():
                    t = R["tables"][vk][pid]
                    row = {k: (f[k][i] if isinstance(f[k], list) else f[k]) for k in f if k != "thr"}
                    row["thr"] = {k: v[i] for k, v in f["thr"].items()}
                    row["q"] = [x[i] for x in t["q"]]
                    row["bounds"] = [x[i] for x in t["b"]]
                    if "api_mean" in t:
                        row["api_mean"], row["api_anom"] = t["api_mean"][i], t["api_anom"][i]
                    row["members"] = r2(R["members"][vk][pid][i], 2 if vk == "t2m" else 1)
                    pr["periods"][vk][pid] = row
            if R["ec_probs"] is not None:
                pr["ec46_probs"] = R["ec_probs"][i]
            out[key] = pr
        json.dump(out, open(tmp / "points" / f"{i}.json", "w"), ensure_ascii=False, separators=(",", ":"))

    json.dump(manifest, open(tmp / "manifest.json", "w"), ensure_ascii=False, indent=1)
    if OUT.exists():
        shutil.rmtree(OUT)
    tmp.rename(OUT)
    print(f"written -> {OUT}")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="합성 자료로 실행 (네트워크 불필요)")
    ap.add_argument("--products", default="1m,3m")
    ap.add_argument("--issue", help="발표일 YYYY-MM-DD (기본: 오늘, KST)")
    args = ap.parse_args()

    grid = json.load(open(ROOT / "site" / "data" / "grid.json"))
    points = grid["points"]
    issue = dt.date.fromisoformat(args.issue) if args.issue else dt.datetime.now(KST).date()

    if args.demo:
        import synthetic
        clim = synthetic.climatology()
    else:
        clim = Climatology.load()
        if clim is None:
            print("! ERA5 평년 캐시 없음: `python pipeline/climatology.py` 실행 권장. 기본 변동폭으로 진행")

    daily_vars = [V["daily"] for V in VARIABLES.values()]
    products = {}
    keys = args.products.split(",")
    keys.sort(key=lambda k: k != "3m")  # 1개월 평년값에 SEAS5 월별 모델 기후를 쓰므로 3개월 먼저
    for key in keys:
        P = PRODUCTS[key]
        if key == "1m":
            weekly = [f"{V['weekly']}_{s}" for V in VARIABLES.values() if V["weekly"] for s in ("mean", "anomaly")] + EC46_WEEKLY_PROBS
            monthly = None
        else:
            weekly = None
            monthly = [f"{V['monthly']}_{s}" for V in VARIABLES.values() if V["monthly"] for s in ("mean", "anomaly")]
        print(f"[{key}] {P['model']} fetch ({len(points)} points)")
        if args.demo:
            resp = synthetic.seasonal(points, key, issue, P["forecast_days"], daily_vars, weekly, monthly)
        else:
            resp = om.fetch_seasonal(points, P["model"], daily_vars, weekly, monthly, P["forecast_days"])
        rates = products["3m"]["rates"] if "3m" in products else None
        products[key] = compute_product(key, resp, points, clim, issue, rates)
    write_outputs(products, points, args.demo, clim)


if __name__ == "__main__":
    main()
