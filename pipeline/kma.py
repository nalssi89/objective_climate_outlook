"""기상청 API 허브(typ01) 클라이언트 — ASOS 일자료·평년값.

인증키는 환경변수 KMA_APIHUB_KEY (GitHub Actions 비밀값)로만 받는다. 저장소에 키를 넣지 말 것.
"""
import os
import time

import numpy as np
import requests

BASE = "https://apihub.kma.go.kr/api/typ01/url/"

# kma_sfcdd.php 출력 열 (API 허브 도움말 순서)
SFCDD_COLS = [
    "TM", "STN", "WS_AVG", "WR_DAY", "WD_MAX", "WS_MAX", "WS_MAX_TM", "WD_INS", "WS_INS", "WS_INS_TM",
    "TA_AVG", "TA_MAX", "TA_MAX_TM", "TA_MIN", "TA_MIN_TM", "TD_AVG", "TS_AVG", "TG_MIN", "HM_AVG", "HM_MIN",
    "HM_MIN_TM", "PV_AVG", "EV_S", "EV_L", "FG_DUR", "PA_AVG", "PS_AVG", "PS_MAX", "PS_MAX_TM", "PS_MIN",
    "PS_MIN_TM", "CA_TOT", "SS_DAY", "SS_DUR", "SS_CMB", "SI_DAY", "SI_60M_MAX", "SI_60M_MAX_TM", "RN_DAY",
    "RN_D99", "RN_DUR", "RN_60M_MAX", "RN_60M_MAX_TM", "RN_10M_MAX", "RN_10M_MAX_TM", "RN_POW_MAX",
    "RN_POW_MAX_TM", "SD_NEW", "SD_NEW_TM", "SD_MAX", "SD_MAX_TM", "TE_05", "TE_10", "TE_15", "TE_30", "TE_50",
]
# 전망 요소 ↔ ASOS 일자료 열
ELEMENTS = {"t2m": "TA_AVG", "precip": "RN_DAY", "rad": "SI_DAY", "wind": "WS_AVG"}
MISSING = {-9.0, -99.0, -99.9, -999.0}


def key():
    k = os.environ.get("KMA_APIHUB_KEY")
    if not k:
        raise RuntimeError("KMA_APIHUB_KEY 환경변수가 없습니다")
    return k


def get_text(path, params, retries=5):
    wait = 5
    for _ in range(retries):
        try:
            r = requests.get(BASE + path, params={**params, "authKey": key()}, timeout=120)
            if r.status_code == 200:
                raw = r.content
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    return raw.decode("euc-kr", errors="replace")
            print(f"  ! KMA HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            print(f"  ! KMA network error {e}")
        time.sleep(wait)
        wait = min(wait * 2, 120)
    raise RuntimeError(f"KMA request failed: {path} {params}")


def parse_rows(text):
    """'#' 주석 줄을 건너뛰고 쉼표/공백 구분 자료를 행 목록으로."""
    rows = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        s = s.rstrip("=").rstrip(",").strip()
        parts = [p.strip() for p in (s.split(",") if "," in s else s.split())]
        rows.append(parts)
    return rows


def to_float(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    return np.nan if x in MISSING else x


def _records(text):
    """응답 행 → [{열: 값}] (머리말의 축약 열 이름은 쓰지 않고 도움말 순서 SFCDD_COLS 사용)."""
    out = []
    for row in parse_rows(text):
        if len(row) < 39 or not row[0].isdigit():
            continue
        out.append(dict(zip(SFCDD_COLS, row)))
    return out


def element_value(rec, col):
    """결측 처리.

    - 기온(TA_*)은 -9.0 이 실제 값일 수 있으므로 -50 이하만 결측
    - 강수(RN_DAY)의 -9 는 '강수 없음'으로 보고 0 (같은 날 기온이 정상일 때만)
    """
    if col.startswith("TA"):
        try:
            v = float(rec.get(col))
        except (TypeError, ValueError):
            return np.nan
        return np.nan if v <= -50 else v
    v = to_float(rec.get(col))
    if col == "RN_DAY" and np.isnan(v) and np.isfinite(element_value(rec, "TA_AVG")):
        return 0.0
    return v


def sfcdd_day(day, stn="0"):
    """하루치 ASOS 일자료 {지점번호: {열: 값}}. day: 'YYYYMMDD'."""
    text = get_text("kma_sfcdd.php", {"tm": day, "stn": stn, "disp": "0", "help": "0"})
    return {int(r["STN"]): r for r in _records(text)}


def sfcdd_range(stn, tm1, tm2):
    """한 지점의 기간 일자료 [{열: 값}] (kma_sfcdd3.php). tm1/tm2: 'YYYYMMDD'."""
    text = get_text("kma_sfcdd3.php", {"tm1": tm1, "tm2": tm2, "stn": str(stn), "disp": "0", "help": "0"})
    return _records(text)


def stations(tm="202012310900"):
    """ASOS 지점 정보 [{stn, lon, lat, ht, name, name_en}]."""
    text = get_text("stn_inf.php", {"inf": "SFC", "stn": "", "tm": tm, "help": "0"})
    out = []
    for ln in text.splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        t = ln.split()
        try:
            out.append({"stn": int(t[0]), "lon": float(t[1]), "lat": float(t[2]), "ht": float(t[4]),
                        "name": t[10], "name_en": t[11]})
        except (IndexError, ValueError):
            continue
    return out
