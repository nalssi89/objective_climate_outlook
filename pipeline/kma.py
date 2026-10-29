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
MISSING = {-9.0, -9.9, -99.0, -99.9, -999.0}


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


def header_cols(text):
    """주석 줄 중 열 이름 행(# YYMMDD STN ... / # TM,STN,...)을 찾는다. 없으면 None."""
    for ln in text.splitlines():
        if ln.startswith("#") and "STN" in ln.upper():
            toks = [t for t in ln.lstrip("#").replace(",", " ").split() if t]
            if len(toks) > 5:
                return toks
    return None


def to_float(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    return np.nan if x in MISSING else x


def sfcdd_day(day, stn="0"):
    """하루치 ASOS 일자료 {지점번호: {열: 값}}. day: 'YYYYMMDD'."""
    text = get_text("kma_sfcdd.php", {"tm": day, "stn": stn, "disp": "0", "help": "0"})
    cols = header_cols(text) or SFCDD_COLS  # 응답 머리말에 열 이름이 있으면 그것을 우선
    out = {}
    for row in parse_rows(text):
        if len(row) < 3:
            continue
        rec = dict(zip(cols, row))
        out[int(float(rec["STN"]))] = rec
    return out
