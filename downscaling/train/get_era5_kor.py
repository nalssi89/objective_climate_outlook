"""ECMWF ARCO ERA5 SFC geoChunked (0.25도, 매시간) -> 한반도 전역(북한 포함) 일자료.
영역 33-43.5N, 124-132E. KST(UTC+9) 기준 일평균 기온, 일강수량(mm).
geoChunked 청크는 (시간 67584h, 4, 4) 이므로 시간 청크 경계 단위로 영역 전체를 읽는다.
  CDSAPI_KEY=... python get_era5_kor.py OUTDIR
"""
import os, sys, time
import numpy as np, pandas as pd, xarray as xr
from pathlib import Path
from obstore.store import HTTPStore
from zarr.storage import ObjectStore

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KDS_RAW", "work/raw"))
URL = "https://arco.datastores.ecmwf.int/cadl-arco-geo-002/arco/reanalysis_era5_single_levels/sfc/geoChunked.zarr"
http = HTTPStore(URL, client_options={"default_headers": {"Authorization": f"Bearer {os.environ['CDSAPI_KEY']}"},
                                      "timeout": "600s"})
ds = xr.open_zarr(ObjectStore(http, read_only=True), consolidated=True, chunks=None)
ds = ds.rename({k: v for k, v in {"latitude": "lat", "longitude": "lon", "valid_time": "time"}.items() if k in ds.dims or k in ds.coords})
lon = ds.lon.values
ds = ds.assign_coords(lon=((lon + 180) % 360) - 180) if lon.max() > 180 else ds
ds = ds.sortby("lat").sel(lat=slice(33, 43.5), lon=slice(124, 132))
print(ds.t2m.shape, ds.time.values[[0, -1]], flush=True)
CH = 67584
t0 = pd.Timestamp(ds.time.values[0])
k0 = int((pd.Timestamp("1989-12-31") - t0) / pd.Timedelta(hours=1)) // CH
for k in range(k0, ds.sizes["time"] // CH + 1):
    f = OUT / f"era5kor_chunk{k:02d}.nc"
    if f.exists():
        continue
    sl = slice(k * CH, min((k + 1) * CH, ds.sizes["time"]))
    t = time.time()
    x = ds[["t2m", "tp"]].isel(time=sl).load()
    x = x.assign_coords(time=x.time + np.timedelta64(9, "h"))          # KST
    d = xr.Dataset({"t2m": x.t2m.resample(time="1D").mean() - 273.15,
                    "tp": x.tp.resample(time="1D").sum() * 1000.0,
                    "nh": x.t2m.resample(time="1D").count().isel(lat=0, lon=0, drop=True)})
    d.astype("float32").to_netcdf(f)
    print(k, str(x.time.values[0])[:10], str(x.time.values[-1])[:10], f"{time.time()-t:.0f}s", flush=True)
