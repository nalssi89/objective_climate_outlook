"""남한 약 20 km(0.2°) 상세화 격자.

    python pipeline/fine_grid.py build   # 격자 생성(shapely 필요, 결과 커밋됨)
    python pipeline/fine_grid.py elev    # 격자별 평균 고도(Open-Meteo Elevation API, 셀당 5×5 표본) 채우기

출력: site/data/grid_fine.json  {step, lats, lons, points, fill_index, elev}
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data" / "grid_fine.json"
STEP = 0.2
BOX = (33.0, 38.8, 124.4, 131.0)  # lat0, lat1, lon0, lon1
SUB = 5  # 셀당 고도 표본 SUB×SUB


def south_korea():
    from shapely.geometry import shape

    fc = json.load(open(ROOT / "site" / "data" / "geo" / "korea.geojson"))
    return next(shape(f["geometry"]) for f in fc["features"] if f["properties"]["name"] == "South Korea")


def build():
    from shapely.geometry import Point, box

    kr = south_korea()
    lats = np.round(np.arange(BOX[0], BOX[1] + 1e-9, STEP), 3)
    lons = np.round(np.arange(BOX[2], BOX[3] + 1e-9, STEP), 3)
    pts, subs = [], []
    h = STEP / 2
    for la in lats:
        for lo in lons:
            cell = box(lo - h, la - h, lo + h, la + h)
            frac = cell.intersection(kr).area / cell.area
            if frac >= 0.25 or kr.contains(Point(lo, la)):
                pts.append([float(la), float(lo)])
                # 육지 안의 고도 표본점
                off = (np.arange(SUB) + 0.5) / SUB * STEP - h
                s = [[round(la + a, 4), round(lo + b, 4)] for a in off for b in off if kr.contains(Point(lo + b, la + a))]
                subs.append(s or [[la, lo]])
    arr = np.array(pts)
    fill = []
    for la in lats:
        for lo in lons:
            d = (arr[:, 0] - la) ** 2 + ((arr[:, 1] - lo) * np.cos(np.radians(la))) ** 2
            fill.append(int(d.argmin()))
    g = {"step": STEP, "lats": lats.tolist(), "lons": lons.tolist(), "points": pts, "fill_index": fill,
         "elev": None, "samples": subs}
    json.dump(g, open(OUT, "w"), separators=(",", ":"))
    print(f"fine grid: {len(pts)} land cells, {sum(len(s) for s in subs)} elevation samples")


def elev():
    import requests

    g = json.load(open(OUT))
    if g.get("elev"):
        print("elevation already present")
        return
    flat = [(i, p) for i, s in enumerate(g["samples"]) for p in s]
    vals = np.full(len(flat), np.nan)
    for k in range(0, len(flat), 50):
        chunk = flat[k:k + 50]
        params = {"latitude": ",".join(str(p[0]) for _, p in chunk), "longitude": ",".join(str(p[1]) for _, p in chunk)}
        for attempt in range(8):
            try:
                r = requests.get("https://api.open-meteo.com/v1/elevation", params=params, timeout=90)
                if r.status_code == 200:
                    vals[k:k + len(chunk)] = r.json()["elevation"]
                    break
                print(f"  ! elevation HTTP {r.status_code}; retry")
            except requests.RequestException as e:
                print(f"  ! elevation {type(e).__name__}; retry")
            time.sleep(10 * (attempt + 1))
        time.sleep(1)
    print(f"  samples with elevation: {np.isfinite(vals).mean():.0%}")
    cells = np.array([i for i, _ in flat])
    if np.isfinite(vals).mean() < 0.9:
        raise SystemExit("고도 표본이 90% 미만 — 다시 실행하세요")
    g["elev"] = [round(float(np.nanmean(np.maximum(vals[cells == i], 0))), 1) for i in range(len(g["points"]))]
    json.dump(g, open(OUT, "w"), separators=(",", ":"))
    print(f"elevation: mean {np.mean(g['elev']):.0f} m, max {np.max(g['elev']):.0f} m")


if __name__ == "__main__":
    {"build": build, "elev": elev}[sys.argv[1]]()
