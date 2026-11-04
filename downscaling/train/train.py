"""학습·교차검증·최종모형 저장.
  python train.py [grid|asos] [T|P] [week|month]
산출 (WORK): cv_<kind>_<var>_<scale>.nc (관측·CV·독립검증·기준선), model_<kind>_<var>_<scale>.pkl
"""
import os, sys, pickle, time
from pathlib import Path
import numpy as np, pandas as pd, xarray as xr
sys.path.insert(0, str(Path(__file__).parent))
import esd

WORK = Path(os.environ.get("KDS_WORK", "work"))
TRAIN, TEST, FINAL = (1991, 2022), (2023, 2026), (1991, 2025)
LOCAL = {"T": ["t2m", "d2m"], "P": ["tp", "d2m", "msl"]}
NPC = {"week": 6, "month": 3}


def load_target(kind, var):
    if kind == "grid":
        ds = xr.open_dataset(WORK / "target_grid.nc")
        st = ds[{"T": "t2m", "P": "tp"}[var]].stack(pt=("lat", "lon"))
        st = st.isel(pt=np.where(ds.mask.stack(pt=("lat", "lon")).values)[0])
        lat, lon = st.lat.values, st.lon.values
        da = xr.DataArray(st.values, dims=("time", "pt"), coords={"time": st.time.values})
    else:
        ds = xr.open_dataset(WORK / "target_asos.nc")
        da = ds[var].rename(stn="pt"); lat, lon = ds.lat.values, ds.lon.values
        da = da.drop_vars([c for c in da.coords if c != "time"])
    return da, lat, lon


def load_pred():
    ds = xr.open_dataset(WORK / "pred.nc").stack(pt=("lat", "lon"))
    plat, plon = ds.lat.values, ds.lon.values
    out = {v: xr.DataArray(ds[v].values, dims=("time", "pt"), coords={"time": ds.time.values}) for v in esd.PVARS}
    return out, plat, plon


def prepare(kind, var, scale):
    y, lat, lon = load_target(kind, var)
    preds, plat, plon = load_pred()
    t = y.time.to_index().intersection(preds["t2m"].time.to_index())
    y = y.sel(time=t)
    ya, yclim = esd.anomalies(esd.transform(esd.aggregate(y, scale), var), scale)
    X = {}
    xclim = {}
    for v, da in preds.items():
        a, c = esd.anomalies(esd.transform(esd.aggregate(da.sel(time=t), scale), v), scale)
        X[v] = a; xclim[v] = c
    W = esd.radius_weights(plat, plon, lat, lon)
    return dict(ya=ya, yclim=yclim, X=X, xclim=xclim, W=W, lat=lat, lon=lon, plat=plat, plon=plon)


def local_feats(Xd, W, var):
    return np.stack([Xd[v] @ W.T for v in LOCAL[var]], 1)        # (n, m, npt)


def run(kind, var, scale):
    t0 = time.time()
    D = prepare(kind, var, scale)
    ya = D["ya"]; times = ya.time.to_index(); yrs = times.year.values
    Y = ya.values
    Xall = {v: D["X"][v].values for v in esd.PVARS}
    cv = np.full_like(Y, np.nan); base = np.full_like(Y, np.nan)
    models = {}
    for m in range(1, 13):
        win = esd.season_window(times, m, 1)
        cen = times.month.values == m
        tr = win & (yrs >= TRAIN[0]) & (yrs <= TRAIN[1])
        sub = lambda mask: {v: Xall[v][mask] for v in esd.PVARS}
        eof = esd.EOFPredictors(NPC[scale]).fit(sub(tr))
        _, alpha = esd.fit_points(eof.transform(sub(tr)), local_feats(sub(tr), D["W"], var), Y[tr], groups=yrs[tr])
        # leave-one-year-out (EOF도 매 폴드 다시 계산)
        for yy in range(TRAIN[0], TEST[1] + 1):
            te = cen & (yrs == yy)
            if not te.any():
                continue
            fit = tr & (yrs != yy)
            e = esd.EOFPredictors(NPC[scale]).fit(sub(fit))
            c, _ = esd.fit_points(e.transform(sub(fit)), local_feats(sub(fit), D["W"], var), Y[fit], alpha=alpha)
            cv[te] = esd.predict_points(c, e.transform(sub(te)), local_feats(sub(te), D["W"], var))
        base[cen] = local_feats(sub(cen), D["W"], var)[:, 0, :]
        # 최종 모형 (1991~2025)
        fin = win & (yrs >= FINAL[0]) & (yrs <= FINAL[1])
        e = esd.EOFPredictors(NPC[scale]).fit(sub(fin))
        c, _ = esd.fit_points(e.transform(sub(fin)), local_feats(sub(fin), D["W"], var), Y[fin], alpha=alpha)
        res = Y[fin & cen] - esd.predict_points(c, e.transform(sub(fin & cen)), local_feats(sub(fin & cen), D["W"], var))
        models[m] = dict(eof=e, coef=c, alpha=alpha, resid_sd=np.nanstd(res, 0))
        print(f"  {kind} {var} {scale} month {m:2d}  {time.time()-t0:.0f}s", flush=True)
    # 저장
    ds = xr.Dataset({"obs": (("time", "pt"), Y), "cv": (("time", "pt"), cv), "base": (("time", "pt"), base)},
                    coords={"time": times, "lat": ("pt", D["lat"]), "lon": ("pt", D["lon"])})
    if var == "P":   # sqrt 공간 -> mm/일
        key = times.dayofyear.values if scale == "week" else times.month.values
        cl = D["yclim"](key).reshape(len(times), -1)
        ds["clim_sqrt"] = (("time", "pt"), cl)
    ds.to_netcdf(WORK / f"cv_{kind}_{var}_{scale}.nc")
    with open(WORK / f"model_{kind}_{var}_{scale}.pkl", "wb") as f:
        pickle.dump(dict(models=models, W=D["W"], lat=D["lat"], lon=D["lon"], plat=D["plat"], plon=D["plon"],
                         local=LOCAL[var], yclim=_clim_table(D["yclim"], scale),
                         xclim={v: _clim_table(D["xclim"][v], scale) for v in esd.PVARS}), f)
    print("done", kind, var, scale, f"{time.time()-t0:.0f}s", flush=True)


def _clim_table(fn, scale):
    """기후값을 표로 저장 (주: 1~366일, 월: 1~12월)"""
    key = np.arange(1, 367) if scale == "week" else np.arange(1, 13)
    return np.asarray(fn(key)).reshape(len(key), -1)


if __name__ == "__main__":
    kinds, vars_, scales = (sys.argv[1:4] + [None] * 3)[:3]
    for k in [kinds] if kinds else ["asos", "grid"]:
        for v in [vars_] if vars_ else ["T", "P"]:
            for s in [scales] if scales else ["month", "week"]:
                run(k, v, s)
