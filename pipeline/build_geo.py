"""한반도 육상 격자와 지도용 경계(GeoJSON)를 만든다 (최초 1회 실행).

입력: Natural Earth 국가 경계 GeoJSON (npm `world-atlas` countries-10m/50m 을 topojson-client 로 변환한 파일)
출력: site/data/grid.json, site/data/geo/korea.geojson, site/data/geo/neighbors.geojson

    python pipeline/build_geo.py countries-10m.geojson countries-50m.geojson
"""
import json
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union

from config import GRID

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data"


def load(path, names):
    fc = json.load(open(path))
    return {f["properties"]["name"]: shape(f["geometry"]) for f in fc["features"] if f["properties"]["name"] in names}


def rounded(geom, nd=3):
    g = mapping(geom)

    def r(c):
        if isinstance(c[0], (float, int)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]

    g["coordinates"] = r(g["coordinates"])
    return g


def main(p10, p50):
    kor = load(p10, {"South Korea", "North Korea"})
    korea = unary_union(list(kor.values()))
    view = box(115, 28, 140, 47)

    feats = [
        {"type": "Feature", "properties": {"name": n}, "geometry": rounded(g.simplify(0.004, preserve_topology=True))}
        for n, g in kor.items()
    ]
    json.dump({"type": "FeatureCollection", "features": feats}, open(OUT / "geo" / "korea.geojson", "w"), separators=(",", ":"))

    nb = load(p50, {"China", "Japan", "Russia", "Taiwan", "Mongolia"})
    feats = [
        {"type": "Feature", "properties": {"name": n}, "geometry": rounded(g.intersection(view).simplify(0.02, preserve_topology=True), 2)}
        for n, g in nb.items()
        if not g.intersection(view).is_empty
    ]
    json.dump({"type": "FeatureCollection", "features": feats}, open(OUT / "geo" / "neighbors.geojson", "w"), separators=(",", ":"))

    # --- 0.5° 육상 격자: 셀 면적의 20% 이상이 한반도 육지이거나 격자점이 육지 안에 있으면 채택
    d = GRID["step"]
    lats = np.round(np.arange(GRID["lat0"], GRID["lat1"] + 1e-9, d), 3)
    lons = np.round(np.arange(GRID["lon0"], GRID["lon1"] + 1e-9, d), 3)
    land = []
    for la in lats:
        for lo in lons:
            cell = box(lo - d / 2, la - d / 2, lo + d / 2, la + d / 2)
            frac = cell.intersection(korea).area / cell.area
            if frac >= 0.2 or korea.contains(Point(lo, la)):
                land.append((float(la), float(lo)))
    # 작은 섬(울릉도 등)도 가장 가까운 격자점 하나는 확보
    for poly in getattr(korea, "geoms", [korea]):
        if poly.area < 0.004:  # ~ 40 km² 미만 무시
            continue
        c = poly.representative_point()
        la = round(round(c.y / d) * d, 3)
        lo = round(round(c.x / d) * d, 3)
        if (la, lo) not in land:
            land.append((la, lo))
    land.sort(key=lambda p: (-p[0], p[1]))

    # 사각 격자 전체에 대해 가장 가까운 육상 격자 인덱스(지도 보간 시 해상 노드 채움용)
    arr = np.array(land)
    fill = []
    for la in lats:
        for lo in lons:
            dist = (arr[:, 0] - la) ** 2 + ((arr[:, 1] - lo) * np.cos(np.radians(la))) ** 2
            fill.append(int(dist.argmin()))
    grid = {
        "step": d,
        "lats": lats.tolist(),
        "lons": lons.tolist(),
        "points": [[la, lo] for la, lo in land],
        "fill_index": fill,
    }
    json.dump(grid, open(OUT / "grid.json", "w"), separators=(",", ":"))
    print(f"land points: {len(land)}  (rect {len(lats)}x{len(lons)})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
