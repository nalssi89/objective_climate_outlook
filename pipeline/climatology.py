"""ERA5(1991–2020) 기반 평년 분포.

- 권역 대표 12개 지점의 일별 ERA5 자료를 Open-Meteo archive API 로 받아 `cache/era5_daily.npz` 에 저장(최초 1회,
  호출 한도에 걸리면 진행분을 저장하고 종료 → 다시 실행하면 이어받음).
- 임의의 예측 기간(주·월·계절)에 대해 30년 동일 달력기간 집계값을 만들고,
  평년 평균·분위수(10, 33.3, 50, 66.7, 90%)를 격자로 역거리가중(IDW) 보간한다.

    python pipeline/climatology.py          # ERA5 캐시 구축/이어받기
"""
import datetime as dt
import json
import time
from pathlib import Path

import numpy as np

from config import CLIM_CHUNK_YEARS, CLIM_POINTS, CLIM_YEARS, VARIABLES

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(__file__).resolve().parent / "cache" / "era5_daily.npz"
QUANTILES = np.array([10, 100 / 3, 50, 200 / 3, 90])
Z = np.array([-1.2816, -0.4307, 0.0, 0.4307, 1.2816])  # 표준정규 분위수
DAY0 = dt.date(CLIM_YEARS[0], 1, 1)


def clim_points():
    return [list(p) for p in CLIM_POINTS]


class Climatology:
    def __init__(self, points, dates, data):
        self.points = np.asarray(points, dtype=float)  # (n, 2)
        self.d0 = dates[0]
        self.ndays = len(dates)
        self.data = data  # var -> (n, ndays)

    @classmethod
    def load(cls, path=CACHE):
        if not Path(path).exists():
            return None
        z = np.load(path)
        if "done" in z.files and not z["done"].all():
            print(f"! ERA5 캐시 미완성 ({int(z['done'].sum())}/{z['done'].size}) -> 기본 변동폭 사용")
            return None
        dates = [DAY0 + dt.timedelta(days=int(i)) for i in z["day"]]
        data = {k[4:]: z[k] for k in z.files if k.startswith("var_")}
        return cls(z["points"], dates, data)

    # ---------- 기간 집계 ----------
    def _idx(self, d):
        return (d - self.d0).days

    def window_values(self, var, start, end, agg):
        """[지점, 연도] : 1991–2020 각 해 동일 달력기간(start~end) 집계값."""
        arr = self.data.get(var)
        if arr is None:
            return None
        out = []
        for y in range(CLIM_YEARS[0], CLIM_YEARS[1] + 1):
            s = _same_day(start, y)
            e = s + (end - start)
            i0, i1 = self._idx(s), self._idx(e)
            if i0 < 0 or i1 >= self.ndays:
                continue
            block = arr[:, i0:i1 + 1]
            out.append(np.nanmean(block, axis=1) if agg == "mean" else np.nansum(block, axis=1))
        return np.array(out).T if out else None

    def stats(self, var, start, end, agg, mode):
        """평년 평균과 분포 형태(add: 분위수-평균, mul: 분위수/평균)."""
        v = self.window_values(var, start, end, agg)
        if v is None:
            return None
        mean = np.nanmean(v, axis=1)
        q = np.nanpercentile(v, QUANTILES, axis=1).T  # (n, 5)
        if mode == "add":
            shape = q - mean[:, None]
        else:
            with np.errstate(invalid="ignore", divide="ignore"):
                shape = q / mean[:, None]
            shape[~np.isfinite(shape)] = np.nan
        return mean, shape

    def daily_normal(self, var, dates, half=7):
        """예측 날짜별 일평년값(±half 일 이동평균, 30년 평균) [지점, 날짜]."""
        arr = self.data.get(var)
        if arr is None:
            return None
        out = np.full((len(self.points), len(dates)), np.nan)
        for j, d in enumerate(dates):
            acc = []
            for y in range(CLIM_YEARS[0], CLIM_YEARS[1] + 1):
                c = self._idx(_same_day(d, y))
                i0, i1 = max(c - half, 0), min(c + half, self.ndays - 1)
                if i0 <= i1:
                    acc.append(arr[:, i0:i1 + 1])
            out[:, j] = np.nanmean(np.concatenate(acc, axis=1), axis=1)
        return out

    # ---------- 보간 ----------
    def idw(self, values, targets, k=4, power=2):
        """values[clim 지점, ...] → targets[격자, ...] 역거리가중 보간."""
        values = np.asarray(values, dtype=float)
        t = np.asarray(targets, dtype=float)
        coslat = np.cos(np.radians(t[:, :1]))
        d2 = (t[:, None, 0] - self.points[None, :, 0]) ** 2 + ((t[:, None, 1] - self.points[None, :, 1]) * coslat) ** 2
        nn = np.argsort(d2, axis=1)[:, :k]
        out = np.empty((len(t),) + values.shape[1:])
        for i in range(len(t)):
            idx = nn[i]
            w = 1.0 / np.maximum(d2[i, idx], 1e-6) ** (power / 2)
            vals = values[idx]
            ok = np.isfinite(vals)
            ww = w.reshape((-1,) + (1,) * (vals.ndim - 1)) * ok
            with np.errstate(invalid="ignore", divide="ignore"):
                out[i] = np.nansum(np.where(ok, vals, 0) * ww, axis=0) / ww.sum(axis=0)
        return out


def _same_day(d, year):
    try:
        return d.replace(year=year)
    except ValueError:  # 2월 29일
        return d.replace(year=year, day=28)


def default_shape(mode, sd):
    """ERA5 가 없을 때 정규(add) / 로그정규(mul) 가정 분포 형태."""
    if mode == "add":
        return Z * sd
    s = np.sqrt(np.log(1 + sd ** 2))
    return np.exp(-s ** 2 / 2 + Z * s)


def build_cache():
    """ERA5 일별 자료 수집(이어받기 지원). 완료되면 True."""
    from openmeteo import RateLimited, fetch_archive

    CACHE.parent.mkdir(exist_ok=True)
    pts = clim_points()
    ndays = (dt.date(CLIM_YEARS[1], 12, 31) - DAY0).days + 1
    chunks = [(y, min(y + CLIM_CHUNK_YEARS - 1, CLIM_YEARS[1])) for y in range(CLIM_YEARS[0], CLIM_YEARS[1] + 1, CLIM_CHUNK_YEARS)]
    keys = {k: v["era5"] for k, v in VARIABLES.items()}
    data = {k: np.full((len(pts), ndays), np.nan, dtype=np.float32) for k in keys}
    done = np.zeros((len(pts), len(chunks)), dtype=bool)
    if CACHE.exists():
        z = np.load(CACHE)
        if "done" in z.files and z["points"].tolist() == pts and z["done"].shape == done.shape:
            done = z["done"]
            data = {k: z["var_" + k].copy() for k in keys}
    print(f"ERA5 climatology: {len(pts)} points x {len(chunks)} chunks, done {int(done.sum())}/{done.size}")
    try:
        for i, p in enumerate(pts):
            for c, (y0, y1) in enumerate(chunks):
                if done[i, c]:
                    continue
                r = fetch_archive(p, f"{y0}-01-01", f"{y1}-12-31", list(keys.values()))
                daily = r["daily"]
                i0 = (dt.date(y0, 1, 1) - DAY0).days
                for k, era in keys.items():
                    v = np.array([np.nan if x is None else x for x in daily[era]], dtype=np.float32)
                    data[k][i, i0:i0 + len(v)] = v
                done[i, c] = True
                _save(pts, data, done, ndays)
                print(f"  ERA5 {p} {y0}-{y1} ok ({int(done.sum())}/{done.size})")
                time.sleep(15)
    except RateLimited as e:
        print(f"! 호출 한도 도달: {e} -> 진행분 저장, 나중에 다시 실행하세요")
        return False
    return bool(done.all())


def _save(points, data, done, ndays):
    np.savez_compressed(
        CACHE, points=np.array(points, dtype=float), day=np.arange(ndays, dtype=np.int32), done=done,
        **{"var_" + k: v for k, v in data.items()},
    )


if __name__ == "__main__":
    import sys

    sys.exit(0 if build_cache() else 3)
