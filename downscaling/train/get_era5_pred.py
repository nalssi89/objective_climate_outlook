"""대규모 예측인자: ECMWF ARCO ERA5 geoChunked에서 1.5도 격자점 값(점 표본)을 읽어 KST 일자료로.
영역 28-46N, 114-141E (13x19점). 변수 t2m, d2m(°C), msl(hPa), tp(mm/일).
Open-Meteo 예보도 좌표점 값으로 받으므로 학습(ERA5)과 예보 쪽 표본 방식이 같다(면적평균 X).
  CDSAPI_KEY=... python get_era5_pred.py OUTDIR
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
LAT, LON = np.arange(28, 46.01, 1.5), np.arange(114, 141.01, 1.5)
lat_i = [int(np.argmin(np.abs(ds.lat.values - a))) for a in LAT]
lon_v = ds.lon.values
lon_i = [int(np.argmin(np.abs(((lon_v - b + 180) % 360) - 180))) for b in LON]
ds = ds.isel(lat=lat_i, lon=lon_i).assign_coords(lat=LAT, lon=LON).sortby("lat")
CH = 67584
t0 = pd.Timestamp(ds.time.values[0])
k0 = int((pd.Timestamp("1989-12-31") - t0) / pd.Timedelta(hours=1)) // CH
for k in range(k0, ds.sizes["time"] // CH + 1):
    f = OUT / f"era5pred_chunk{k:02d}.nc"
    if f.exists():
        continue
    sl = slice(k * CH, min((k + 1) * CH, ds.sizes["time"]))
    t = time.time()
    x = ds[["t2m", "d2m", "msl", "tp"]].isel(time=sl).load()
    x = x.assign_coords(time=x.time + np.timedelta64(9, "h"))
    r = x.resample(time="1D")
    d = xr.Dataset({"t2m": r.mean().t2m - 273.15, "d2m": r.mean().d2m - 273.15,
                    "msl": r.mean().msl / 100.0, "tp": r.sum().tp * 1000.0})
    d.astype("float32").to_netcdf(f)
    print(k, f"{time.time()-t:.0f}s", flush=True)
