"""학습된 모형(pickle)을 numpy 전용 .npz 로 내보낸다 (운영 실행은 numpy/scipy 만 필요).
  python export_models.py OUTDIR
OUTDIR/predictors.npz : 예측인자 247점 좌표, ERA5 1991-2020 일별 기후값(물리단위, 조화함수 평활)
OUTDIR/<kind>_<var>_<scale>.npz : 달(1~12)별 EOF·회귀계수·보정값
"""
import sys, json, pickle
from pathlib import Path
import numpy as np, xarray as xr
sys.path.insert(0, str(Path(__file__).parent))
import esd, apply

WORK = apply.WORK
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)

pred = xr.open_dataset(WORK / "pred.nc").stack(pt=("lat", "lon"))
raw = {}
for v in esd.PVARS:
    da = xr.DataArray(pred[v].values, dims=("time", "pt"), coords={"time": pred.time.values})
    coef, basis = esd.harmonic_clim(da)
    raw[v] = (basis(np.arange(1, 367)) @ coef).astype("float32")          # (366, 247) 일 기후값
np.savez_compressed(out / "predictors.npz", lat=pred.lat.values, lon=pred.lon.values,
                    **{f"era5_daily_{v}": raw[v] for v in esd.PVARS})

for kind in ("grid", "asos"):
    for var in ("T", "P"):
        for scale in ("week", "month"):
            M = pickle.load(open(WORK / f"model_{kind}_{var}_{scale}.pkl", "rb"))
            C = apply.calib(kind, var, scale)
            d = dict(lat=M["lat"], lon=M["lon"], W=M["W"].astype("float32"), local=np.array(M["local"]),
                     yclim=M["yclim"].astype("float32"), pvars=np.array(esd.PVARS))
            for v in esd.PVARS:
                d[f"xclim_{v}"] = M["xclim"][v].astype("float32")
            for m in range(1, 13):
                e = M["models"][m]
                d[f"m{m}_coef"] = e["coef"].astype("float32")
                for v in esd.PVARS:
                    d[f"m{m}_eof_{v}"] = e["eof"].eof[v].astype("float32")
                    d[f"m{m}_mu_{v}"] = e["eof"].mu[v].astype("float32")
                    d[f"m{m}_sd_{v}"] = e["eof"].sd[v].astype("float32")
                    d[f"m{m}_pcsd_{v}"] = np.asarray(e["eof"].pcsd[v], "float32")
            for k in ("q33", "q67", "sigma", "normal", "r_cv"):
                d[k] = C[k].astype("float32")
            if kind == "asos":
                st = xr.open_dataset(WORK / "target_asos.nc")
                d["stn"] = st.stn.values; d["name"] = st.name.values.astype(str)
            np.savez_compressed(out / f"{kind}_{var}_{scale}.npz", **d)
            print(kind, var, scale, (out / f"{kind}_{var}_{scale}.npz").stat().st_size // 1024, "KB")
