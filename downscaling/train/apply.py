"""학습된 다운스케일링 모형을 예보(또는 재분석) 예측인자에 적용.

  fc : xr.Dataset (member, time, pt=247) 일자료 t2m,d2m,msl,tp  (openmeteo.fetch 또는 era5_as_forecast)
  scale='week'  : 예보 시작일부터 7일 묶음(1~6주)
  scale='month' : 예보 기간에 완전히 들어가는 달력월
출력 : xr.Dataset (block, pt) 앙상블 평균 편차·절대값, 3분위 확률(below/normal/above), 멤버별 값
확률 = 멤버 k의 회귀 예측 μ_k 에 교차검증 잔차 σ 를 더한 정규분포 혼합으로 계산
       P(below) = mean_k Φ((q33 − μ_k)/σ)   (q33, q67 = 1991~2020 관측 편차 3분위)
"""
import os, sys, pickle
from pathlib import Path
import numpy as np, pandas as pd, xarray as xr
from scipy.stats import norm
sys.path.insert(0, str(Path(__file__).parent))
import esd, train

WORK = Path(os.environ.get("KDS_WORK", "work"))


def calib(kind, var, scale):
    f = WORK / f"calib_{kind}_{var}_{scale}.pkl"
    if f.exists():
        return pickle.load(open(f, "rb"))
    ds = xr.open_dataset(WORK / f"cv_{kind}_{var}_{scale}.nc")
    t = ds.time.to_index()
    out = {k: np.full((13, ds.sizes["pt"]), np.nan) for k in ("q33", "q67", "sigma", "normal", "r_cv")}
    for m in range(1, 13):
        c = (t.month == m) & (t.year >= 1991) & (t.year <= 2020)
        o, p = ds.obs.values[c], ds.cv.values[c]
        out["q33"][m], out["q67"][m] = np.nanquantile(o, 1 / 3, 0), np.nanquantile(o, 2 / 3, 0)
        out["sigma"][m] = np.nanstd(p - o, 0)
        out["r_cv"][m] = [np.corrcoef(o[:, j][np.isfinite(o[:, j])], p[:, j][np.isfinite(o[:, j])])[0, 1]
                          for j in range(o.shape[1])]
        if var == "P":
            out["normal"][m] = np.nanmean(np.clip(ds.clim_sqrt.values[c] + o, 0, None) ** 2, 0)
    pickle.dump(out, open(f, "wb"))
    return out


def blocks(fc, scale):
    """예보 일자료 -> 블록 평균 (member, block, pt), 블록 중심일, 블록 이름"""
    t = fc.time.to_index()
    if scale == "week":
        nb = len(t) // 7
        lab = [f"{k+1}주 ({t[7*k]:%m/%d}~{t[7*k+6]:%m/%d})" for k in range(nb)]
        cen = [t[7 * k + 3] for k in range(nb)]
        sel = [slice(7 * k, 7 * k + 7) for k in range(nb)]
    else:
        months = pd.period_range(t[0], t[-1], freq="M")
        months = [p for p in months if p.start_time >= t[0].normalize() and p.end_time.normalize() <= t[-1]]
        lab = [f"{p.year}년 {p.month}월" for p in months]
        cen = [p.start_time for p in months]
        sel = [np.where((t >= p.start_time) & (t <= p.end_time))[0] for p in months]
    agg = {v: np.stack([fc[v].isel(time=s).mean("time").values for s in sel], 1) for v in esd.PVARS}
    return agg, pd.DatetimeIndex(cen), lab


def downscale(fc, kind, var, scale, clim_bias=None, anoms=None):
    """fc: 일자료 예보 (ERA5 기후값 대비 편차를 계산) 또는
    anoms=(fields, cen, lab): 이미 모형기후 대비 편차로 만든 예측인자 {v: (member, block, pt)}"""
    M = pickle.load(open(WORK / f"model_{kind}_{var}_{scale}.pkl", "rb"))
    C = calib(kind, var, scale)
    if anoms is None:
        agg, cen, lab = blocks(fc, scale)
    else:
        afields, cen, lab = anoms
    key = cen.dayofyear.values - 1 if scale == "week" else cen.month.values - 1
    res = {k: [] for k in ("mem", "pb", "pn", "pa")}
    for b, (m, kk) in enumerate(zip(cen.month, key)):
        fields = {}
        for v in esd.PVARS:
            if anoms is not None:
                fields[v] = afields[v][:, b, :]; continue
            x = esd.transform(xr.DataArray(agg[v][:, b, :]), v).values
            a = x - M["xclim"][v][kk][None]
            if clim_bias is not None:            # 예보 모형 기후 편향(선택): bias[v] (block, pt)
                a = a - clim_bias[v][b][None]
            fields[v] = a
        mod = M["models"][m]
        PC = mod["eof"].transform(fields)
        L = np.stack([fields[v] @ M["W"].T for v in M["local"]], 1)
        mu = esd.predict_points(mod["coef"], PC, L)              # (member, npt) 편차
        s = C["sigma"][m]
        pb = norm.cdf((C["q33"][m] - mu) / s).mean(0)
        pa = 1 - norm.cdf((C["q67"][m] - mu) / s).mean(0)
        res["mem"].append(mu); res["pb"].append(pb); res["pa"].append(pa); res["pn"].append(1 - pb - pa)
    mem = np.stack(res["mem"], 1)                                  # (member, block, npt)
    ycl = M["yclim"][key]                                          # (block, npt)
    ds = xr.Dataset({"anom_members": (("member", "block", "pt"), mem),
                     "anom": (("block", "pt"), mem.mean(0)),
                     "p_below": (("block", "pt"), np.stack(res["pb"])),
                     "p_normal": (("block", "pt"), np.stack(res["pn"])),
                     "p_above": (("block", "pt"), np.stack(res["pa"]))},
                    coords={"block": lab, "center": ("block", cen), "lat": ("pt", M["lat"]), "lon": ("pt", M["lon"])})
    if var == "T":
        ds["value"] = (("block", "pt"), ycl + mem.mean(0))
    else:   # sqrt 공간 -> mm/일 (멤버별 역변환 후 평균), 평년 대비 %
        val = np.clip(ycl[None] + mem, 0, None) ** 2
        ds["value"] = (("block", "pt"), val.mean(0))
        normal = C["normal"][cen.month.values]
        ds["normal"] = (("block", "pt"), normal)
        ds["pct_normal"] = (("block", "pt"), 100 * val.mean(0) / np.maximum(normal, 0.05))
    ds["r_cv"] = (("block", "pt"), C["r_cv"][cen.month.values])
    return ds


def raw_anomaly(fc, scale):
    """다운스케일 전 원시(1.5도) 예보 편차 앙상블 평균 (비교용)."""
    M = pickle.load(open(WORK / f"model_grid_T_{scale}.pkl", "rb"))
    agg, cen, lab = blocks(fc, scale)
    key = cen.dayofyear.values - 1 if scale == "week" else cen.month.values - 1
    out = {}
    for v in ("t2m", "tp"):
        if v == "tp":
            out[v] = np.stack([agg[v][:, b].mean(0) for b in range(len(lab))])
        else:
            out[v] = np.stack([(agg[v][:, b] - M["xclim"][v][kk][None]).mean(0) for b, kk in enumerate(key)])
    return out, M["plat"], M["plon"], lab


def era5_as_forecast(t0, ndays):
    """재분석 예측인자를 '완벽한 예보'(멤버 1개)로 사용 - 체계 점검·사후 검증용"""
    ds = xr.open_dataset(WORK / "pred.nc").sel(time=slice(t0, pd.Timestamp(t0) + pd.Timedelta(days=ndays - 1)))
    st = ds.stack(pt=("lat", "lon"))
    return xr.Dataset({v: (("member", "time", "pt"), st[v].values[None]) for v in esd.PVARS},
                      coords={"member": [0], "time": st.time.values})


def seas5_cds_anoms(fc_file, hind_file):
    """CDS SEAS5 월평균(1°) -> 247점 내삽, 재예보(1993~2016) 같은 리드 평균 대비 편차.
    강수는 sqrt(mm/일) 공간에서 편차. 반환 (fields{v:(member,block,pt)}, cen, lab)"""
    pred = xr.open_dataset(WORK / "pred.nc").stack(pt=("lat", "lon"))
    pts = dict(latitude=xr.DataArray(pred.lat.values, dims="pt"), longitude=xr.DataArray(pred.lon.values, dims="pt"))
    nmv = {"t2m": "t2m", "d2m": "d2m", "msl": "msl", "tp": "tprate"}
    def load(f):
        ds = xr.open_dataset(f)
        ren = {k: v for k, v in {"number": "member", "forecastMonth": "lead", "forecast_reference_time": "init",
                                 "time": "init"}.items() if k in ds.dims or k in ds.coords}
        ds = ds.rename(ren)
        out = {}
        for v, cv in nmv.items():
            name = cv if cv in ds else [x for x in ds.data_vars if x.startswith(v[:2])][0]
            x = ds[name].interp(**pts)
            if v in ("t2m", "d2m"): x = x - 273.15
            if v == "msl": x = x / 100.0
            if v == "tp": x = np.sqrt((x * 86400 * 1000).clip(min=0))
            out[v] = x
        return out, ds
    F, dsf = load(fc_file); H, _ = load(hind_file)
    init = pd.Timestamp(np.atleast_1d(dsf["init"].values)[0])
    leads = F["t2m"]["lead"].values
    cen = pd.DatetimeIndex([init + pd.DateOffset(months=int(l) - 1) for l in leads])
    lab = [f"{c.year}년 {c.month}월" for c in cen]
    fields = {}
    for v in esd.PVARS:
        clim = H[v].mean([d for d in H[v].dims if d in ("member", "init")])
        a = (F[v] - clim).squeeze()
        fields[v] = a.transpose("member", "lead", "pt").values
    return fields, cen, lab
