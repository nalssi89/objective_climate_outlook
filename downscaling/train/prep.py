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

GEO = Path(os.environ.get("KDS_GEO", Path(__file__).resolve().parents[2] / "site/data/geo/korea.geojson"))


def korea_mask(lat, lon, sub=9, min_frac=0.2):
    """0.25° 셀 안의 sub×sub 표본점 가운데 한반도(남·북한) 경계 폴리곤 안에 드는 비율(육지비율)이 min_frac 이상이면 포함.
    셀 중심이 바다인 해안·하구 격자(신의주, 서해안 등)도 빠지지 않게 한다. 울릉도 포함, 대마도·규슈 제외."""
    import json
    from matplotlib.path import Path as MP
    polys = []
    for f in json.load(open(GEO, encoding="utf-8"))["features"]:
        g = f["geometry"]
        for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            polys.append(MP(np.asarray(poly[0])))          # 외곽 링만
    d = 0.25; off = (np.arange(sub) + 0.5) / sub * d - d / 2
    LO, LA = np.meshgrid(lon, lat)
    ox, oy = np.meshgrid(off, off, indexing="ij")                                  # (sub, sub)
    pts = np.stack([np.broadcast_to(LO[..., None, None] + ox, LO.shape + (sub, sub)).ravel(),
                    np.broadcast_to(LA[..., None, None] + oy, LA.shape + (sub, sub)).ravel()], 1)
    inside = np.zeros(len(pts), bool)
    for P in polys:
        inside |= P.contains_points(pts)
    m = inside.reshape(LO.shape + (sub, sub)).mean((2, 3)) >= min_frac
    return m & ~((LO > 129.05) & (LA < 34.95))


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
