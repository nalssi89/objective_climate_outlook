"""ASOS 관측 평년(1991–2020) — 지점 상세화용.

- 기상청 API 허브(kma_sfcdd3.php)에서 ASOS 지점별 일자료를 5년 단위로 받아 `cache/asos_daily.npz` 에 저장
  (이어받기 지원, 호출이 실패하면 진행분을 저장하고 종료 → 다시 실행).
- 30년 중 기온 자료가 90% 이상인 지점만 '평년 지점'으로 사용한다.

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
from config import CLIM_YEARS

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
    return bool(done.all())


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
    keep = np.isfinite(data["t2m"]).mean(axis=1) >= MIN_COVER["t2m"]
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
            for m in meta:
                print(m["stn"], m["name"], m["lat"], m["lon"], m["ht"], "missing:", m["missing"])
    else:
        raise SystemExit(0 if build() else 3)
