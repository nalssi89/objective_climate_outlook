"""ASOS 관측 평년(1991–2020) — 지점 상세화용.

- 기상청 API 허브(kma_sfcdd3.php)에서 ASOS 지점별 일자료를 5년 단위로 받아 `cache/asos_daily.npz` 에 저장
  (이어받기 지원, 호출이 실패하면 진행분을 저장하고 종료 → 다시 실행).
- 기상청 공식 평년 지점 66곳(본토 62 + 제주 4)을 쓰고, 대구·전주는 공식 병합 지점(860·864) 자료로 2015년 이후를 대체한다.

    python pipeline/asos.py          # 수집/이어받기 (KMA_APIHUB_KEY 필요)
    python pipeline/asos.py --info   # 캐시 요약
"""
import argparse
import datetime as dt
import json
import time
from pathlib import Path

import numpy as np

from climatology import DAY0, Climatology
from config import ASOS_MERGE, ASOS_OFFICIAL_66, CLIM_YEARS

CACHE = Path(__file__).resolve().parent / "cache" / "asos_daily.npz"
CHUNK_YEARS = 5
# 전망 요소 ↔ ASOS 일자료 열
COLUMNS = {"t2m": "TA_AVG", "precip": "RN_DAY", "rad": "SI_DAY", "wind": "WS_AVG"}
MIN_COVER = {"t2m": 0.9, "precip": 0.9, "rad": 0.8, "wind": 0.9}


def ndays():
    return (dt.date(CLIM_YEARS[1], 12, 31) - DAY0).days + 1


def chunks():
    return [(y, min(y + CHUNK_YEARS - 1, CLIM_YEARS[1])) for y in range(CLIM_YEARS[0], CLIM_YEARS[1] + 1, CHUNK_YEARS)]


def build():
    import kma

    CACHE.parent.mkdir(exist_ok=True)
    meta = [s for s in kma.stations() if 90 <= s["stn"] < 300]
    nd, ch = ndays(), chunks()
    data = {k: np.full((len(meta), nd), np.nan, dtype=np.float32) for k in COLUMNS}
    done = np.zeros((len(meta), len(ch)), dtype=bool)
    if CACHE.exists():
        z = np.load(CACHE)
        old = json.loads(str(z["meta"]))
        if [m["stn"] for m in old] == [m["stn"] for m in meta]:
            meta = old
            done = z["done"]
            data = {k: z["var_" + k].copy() for k in COLUMNS}
    print(f"ASOS: {len(meta)} stations x {len(ch)} chunks, done {int(done.sum())}/{done.size}")
    try:
        for i, m in enumerate(meta):
            for c, (y0, y1) in enumerate(ch):
                if done[i, c]:
                    continue
                recs = kma.sfcdd_range(m["stn"], f"{y0}0101", f"{y1}1231")
                for r in recs:
                    try:
                        j = (dt.date(int(r["TM"][:4]), int(r["TM"][4:6]), int(r["TM"][6:8])) - DAY0).days
                    except (ValueError, KeyError):
                        continue
                    if 0 <= j < nd:
                        for k, col in COLUMNS.items():
                            data[k][i, j] = kma.element_value(r, col)
                done[i, c] = True
                time.sleep(0.4)
            _save(meta, data, done)
            cov = np.isfinite(data["t2m"][i]).mean()
            print(f"  {m['stn']:>3} {m['name']}: 기온 자료율 {cov:.0%}")
    except RuntimeError as e:
        print(f"! 수집 중단: {e} -> 진행분 저장, 다시 실행하면 이어받음")
        _save(meta, data, done)
        return False
    merge(meta, data, done)
    return bool(done.all())


def merge(meta, data, done):
    """공식 병합 지점: 전환일 이후를 병합 원천 지점(860·864) 자료로 대체. 자료가 없으면 원래 지점 유지."""
    import kma

    ids = [m["stn"] for m in meta]
    for rule in ASOS_MERGE:
        if rule["station"] not in ids:
            continue
        i = ids.index(rule["station"])
        if meta[i].get("merged") == rule["source"]:
            continue
        start = dt.date.fromisoformat(rule["from"])
        recs = []
        for y0 in range(start.year, CLIM_YEARS[1] + 1, 3):
            y1 = min(y0 + 2, CLIM_YEARS[1])
            t1 = start.strftime("%Y%m%d") if y0 == start.year else f"{y0}0101"
            recs += kma.sfcdd_range(rule["source"], t1, f"{y1}1231")
            time.sleep(0.4)
        if len(recs) < 365:
            print(f"  ! 병합 원천 {rule['source']} 자료 부족({len(recs)}일) -> {rule['station']} 원자료 유지")
            continue
        j0 = (start - DAY0).days
        for k in COLUMNS:
            data[k][i, j0:] = np.nan
        for r in recs:
            j = (dt.date(int(r["TM"][:4]), int(r["TM"][4:6]), int(r["TM"][6:8])) - DAY0).days
            if j0 <= j < ndays():
                for k, col in COLUMNS.items():
                    data[k][i, j] = kma.element_value(r, col)
        meta[i]["merged"] = rule["source"]
        meta[i]["name"] = rule["name"]
        print(f"  병합: {rule['station']} ← {rule['source']} ({rule['from']}~, {len(recs)}일)")
        _save(meta, data, done)


def _save(meta, data, done):
    np.savez_compressed(CACHE, meta=json.dumps(meta, ensure_ascii=False), done=done,
                        **{"var_" + k: v for k, v in data.items()})


def load():
    """평년 지점의 관측 Climatology 와 지점 정보. 캐시가 없거나 미완성이면 (None, None)."""
    if not CACHE.exists():
        return None, None
    z = np.load(CACHE)
    if not z["done"].all():
        print(f"! ASOS 캐시 미완성 ({int(z['done'].sum())}/{z['done'].size})")
        return None, None
    meta = json.loads(str(z["meta"]))
    data = {k: z["var_" + k] for k in COLUMNS}
    keep = np.array([m["stn"] in ASOS_OFFICIAL_66 for m in meta])  # 기상청 공식 평년 지점 66곳
    meta = [m for m, k in zip(meta, keep) if k]
    data = {k: v[keep].astype(float) for k, v in data.items()}
    # 자료율이 낮은 요소는 지점별로 통째로 결측 처리(예: 일사 미관측 지점)
    for k, v in data.items():
        bad = np.isfinite(v).mean(axis=1) < MIN_COVER[k]
        v[bad] = np.nan
        for m, b in zip(meta, bad):
            m.setdefault("missing", [])
            if b:
                m["missing"].append(k)
    dates = [DAY0 + dt.timedelta(days=i) for i in range(ndays())]
    return Climatology([[m["lat"], m["lon"]] for m in meta], dates, data), meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--info", action="store_true")
    a = ap.parse_args()
    if a.info:
        c, meta = load()
        print("stations:", None if meta is None else len(meta))
        if meta:
            print("missing official:", sorted(set(ASOS_OFFICIAL_66) - {m["stn"] for m in meta}))
        if meta:
            for m in meta:
                print(m["stn"], m["name"], m["lat"], m["lon"], m["ht"], "merged:", m.get("merged"), "missing:", m["missing"])
    else:
        raise SystemExit(0 if build() else 3)
