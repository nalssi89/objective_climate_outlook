"""Open-Meteo API 클라이언트 (Seasonal: EC46·SEAS5, Archive: ERA5).

- 여러 지점을 한 번에(쉼표 구분) 요청하고, 429/5xx 는 지수 백오프로 재시도한다.
- 일별 앙상블 멤버는 `<변수>`(control), `<변수>_member01` … `_member50` 키로 온다.
"""
import re
import time

import numpy as np
import requests

from config import ARCHIVE_URL, SEASONAL_URL, TIMEZONE

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "korea-objective-climate-outlook/1.0"


class RateLimited(RuntimeError):
    pass


def get_json(url, params, retries=7, timeout=180):
    wait = 5
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            print(f"  ! network error {e}; retry in {wait}s")
            time.sleep(wait)
            wait = min(wait * 2, 120)
            continue
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else [data]
        msg = r.text[:300]
        if r.status_code == 400:
            raise RuntimeError(f"400 Bad Request: {msg}")
        if r.status_code == 429 and "daily" in msg.lower():
            raise RateLimited(msg)
        if r.status_code == 429 and "hourly" in msg.lower():
            wait = max(wait, 600)
        print(f"  ! HTTP {r.status_code} {msg}; retry in {wait}s")
        time.sleep(wait)
        wait = min(wait * 2, 120)
    raise RuntimeError(f"request failed after {retries} attempts: {url}")


def _batches(points, size):
    for i in range(0, len(points), size):
        yield points[i:i + size]


def fetch_seasonal(points, model, daily, weekly=None, monthly=None, forecast_days=46, batch=6, pause=2.0):
    """지점 목록에 대해 seasonal API 응답(지점별 dict 리스트)을 반환."""
    out = []
    for chunk in _batches(points, batch):
        params = {
            "latitude": ",".join(f"{p[0]:.3f}" for p in chunk),
            "longitude": ",".join(f"{p[1]:.3f}" for p in chunk),
            "models": model,
            "daily": ",".join(daily),
            "forecast_days": forecast_days,
            "timezone": TIMEZONE,
            "wind_speed_unit": "ms",
        }
        if weekly:
            params["weekly"] = ",".join(weekly)
        if monthly:
            params["monthly"] = ",".join(monthly)
        try:
            res = get_json(SEASONAL_URL, params)
        except RuntimeError as e:
            # 주/월 변수 일부가 지원되지 않으면 일별만으로 재시도
            if "400" in str(e) and (weekly or monthly):
                print(f"  ! {e} -> weekly/monthly 없이 재시도")
                params.pop("weekly", None)
                params.pop("monthly", None)
                res = get_json(SEASONAL_URL, params)
            else:
                raise
        out.extend(res)
        print(f"  seasonal {model}: {len(out)}/{len(points)} points")
        time.sleep(pause)
    return out


def fetch_archive(point, start, end, daily):
    params = {
        "latitude": f"{point[0]:.3f}",
        "longitude": f"{point[1]:.3f}",
        "start_date": start,
        "end_date": end,
        "daily": ",".join(daily),
        "timezone": TIMEZONE,
        "wind_speed_unit": "ms",
    }
    return get_json(ARCHIVE_URL, params)[0]


_MEMBER = re.compile(r"_member(\d+)$")


def members(block, var):
    """block(daily dict)에서 var 의 [멤버, 시간] 배열 (control + member01..)."""
    if not block:
        return None
    cols = []
    if var in block:
        cols.append((0, block[var]))
    for k, v in block.items():
        if k.startswith(var + "_member"):
            m = _MEMBER.search(k)
            if m:
                cols.append((int(m.group(1)), v))
    if not cols:
        return None
    cols.sort(key=lambda c: c[0])
    arr = np.array([[np.nan if x is None else x for x in c[1]] for c in cols], dtype=float)
    # 값이 하나도 없는 멤버 제거
    keep = ~np.all(np.isnan(arr), axis=1)
    return arr[keep] if keep.any() else None


def series(block, key):
    if not block or key not in block:
        return None
    return np.array([np.nan if x is None else x for x in block[key]], dtype=float)
