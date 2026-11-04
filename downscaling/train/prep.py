"""학습자료 정리: 한반도 0.25도 타깃(북한 포함 육지), ASOS 66지점(제주 4 포함), 1.5도 대규모 예측인자.
출력 (WORK 폴더): target_grid.nc, target_asos.nc, pred.nc
"""
import os, sys
from pathlib import Path
import numpy as np, pandas as pd, xarray as xr
from global_land_mask import globe

RAW = Path(os.environ.get("KDS_RAW", "/home/user/kds"))
WORK = Path(os.environ.get("KDS_WORK", "/home/user/kds/work")); WORK.mkdir(exist_ok=True, parents=True)
T0, T1 = "1991-01-01", "2026-10-28"

# 압록강·두만강을 따라 그린 한반도 경계(대략) + 남쪽 바다
KOREA_POLY = np.array([(124.0, 39.6), (124.4, 39.85), (125.0, 40.1), (125.7, 40.5), (126.2, 41.0),
                       (126.9, 41.75), (127.4, 41.45), (128.15, 41.4), (128.05, 42.0), (128.9, 42.05),
                       (129.4, 42.45), (129.75, 42.5), (130.0, 42.95), (130.4, 42.6), (130.7, 42.3),
                       (131.2, 41.8), (132.0, 37.0), (132.0, 33.0), (124.0, 33.0)])


def korea_mask(lat, lon):
    from matplotlib.path import Path as MP
    LO, LA = np.meshgrid(lon, lat)
    land = globe.is_land(LA, LO)
    inside = MP(KOREA_POLY).contains_points(np.c_[LO.ravel(), LA.ravel()]).reshape(LO.shape)
    tsushima_kyushu = (LO > 129.05) & (LA < 34.95)
    return land & inside & ~tsushima_kyushu


def target_grid():
    ds = xr.open_mfdataset(sorted(RAW.glob("era5kor_chunk*.nc")), combine="nested", concat_dim="time")
    ds = ds.sortby("time"); ds = ds.sel(time=~ds.get_index("time").duplicated())
    full = ds.nh.load() >= 23                             # 청크 경계의 불완전한 날 제외
    ds = ds[["t2m", "tp"]].where(full, drop=True).sel(time=slice(T0, T1)).load()
    m = korea_mask(ds.lat.values, ds.lon.values)
    ds["mask"] = (("lat", "lon"), m)
    ds.to_netcdf(WORK / "target_grid.nc"); print("grid", dict(ds.sizes), "land pts", int(m.sum()))


def target_asos():
    """ASOS 66지점(남한 내륙 62 + 제주 4). 남한 평균은 jeju==0 인 62지점으로 계산한다."""
    sys.path.insert(0, str(Path(__file__).parent))
    os.environ.setdefault("CA_DATA", str(RAW / "ca_data"))
    from kma_util import NORMAL_ID
    st = pd.read_csv(Path(__file__).parent / "asos66_stations.csv")
    STN = st.STN.tolist()
    files = sorted((RAW / "asos").glob("asos_*.csv")) + sorted((RAW / "asos_jeju").glob("asos_jeju_*.csv"))
    obs = pd.concat([pd.read_csv(f) for f in files])
    obs["date"] = pd.to_datetime(obs.TM.astype(int).astype(str).str[:8])
    obs = obs[obs.STN.isin(STN)]
    obs.loc[obs.TA_AVG <= -90, "TA_AVG"] = np.nan
    obs["RN_DAY"] = obs.RN_DAY.clip(lower=0)
    T = obs.pivot_table(index="date", columns="STN", values="TA_AVG")
    P = obs.pivot_table(index="date", columns="STN", values="RN_DAY")
    idx = pd.date_range(T0, T1)
    ds = xr.Dataset({"T": (("time", "stn"), T.reindex(index=idx, columns=STN).values),
                     "P": (("time", "stn"), P.reindex(index=idx, columns=STN).values)},
                    coords={"time": idx, "stn": STN, "lat": ("stn", st.lat.values),
                            "lon": ("stn", st.lon.values), "name": ("stn", st.name.values),
                            "jeju": ("stn", st.jeju.values.astype(int)),
                            "norm_id": ("stn", [NORMAL_ID.get(s, s) for s in STN])})
    ds.to_netcdf(WORK / "target_asos.nc"); print("asos", dict(ds.sizes), float(ds["T"].isnull().mean()))


def predictors():
    ds = xr.open_mfdataset(sorted(RAW.glob("era5pred_chunk*.nc")), combine="nested", concat_dim="time")
    ds = ds.sortby("time"); ds = ds.sel(time=~ds.get_index("time").duplicated())
    ds = ds.sel(time=slice(T0, T1)).load()
    ds.to_netcdf(WORK / "pred.nc"); print("pred", dict(ds.sizes))


if __name__ == "__main__":
    for f in sys.argv[1:] or ["grid", "asos", "pred"]:
        {"grid": target_grid, "asos": target_asos, "pred": predictors}[f]()
