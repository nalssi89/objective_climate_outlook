"""기상청 API허브 도우미 (climate_index_attribution 의 targets.py 에서 가져옴, nalssi89/kmahub 방식).
인증키는 환경변수 KMA_AUTHKEY 로만 읽는다."""
import os
import re
import time

import pandas as pd
import requests

API = "https://apihub.kma.go.kr/api/typ01/url"

# 남한 내륙 62개 대표지점(제주 제외) - kmahub src/normalCriteria.js SOUTH_KOREA_STATION_POLICY
STN62 = [108, 112, 119, 201, 202, 203, 90, 105, 100, 216, 211, 95, 101, 212, 114,
         131, 127, 226, 135, 221, 133, 232, 129, 235, 236, 238,
         143, 281, 138, 279, 278, 136, 273, 272, 277, 130, 271,
         159, 152, 284, 285, 289, 288, 295, 192, 155, 162, 294,
         146, 243, 245, 140, 247, 244, 248, 156, 165, 261, 260, 170, 262, 168]
# 평년값은 대구(143)->신암 병합 860, 전주(146)->완산 병합 864 지점번호로 제공
NORMAL_ID = {143: 860, 146: 864}


def _get(path, params, tries=5):
    params = dict(params, authKey=os.environ["KMA_AUTHKEY"])
    for i in range(tries):
        try:
            r = requests.get(f"{API}/{path}", params=params, timeout=120)
            r.raise_for_status()
            r.encoding = "euc-kr"
            if "authKey" in r.text[:300] or "인증" in r.text[:300]:
                raise RuntimeError(r.text[:300])
            return r.text
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 ** i)
    raise RuntimeError(f"KMA request failed: {path} ({err})")


def field_names(text):
    """help=1 응답의 '# 1. TM : ...' 줄에서 컬럼명을 읽는다 (kmahub parseFieldNames)."""
    f = re.findall(r"^#\s*(\d+)\.\s+([A-Za-z0-9_]+)\s*:", text, flags=re.M)
    return [n.upper() for _, n in sorted(f, key=lambda x: int(x[0]))]


def parse_kma(text):
    names = field_names(text)
    if not names:   # help 없는 응답: 마지막 '#' 헤더 줄 사용
        hdr = [ln.lstrip("#").replace(",", " ").split() for ln in text.splitlines()
               if ln.startswith("#") and len(ln.split()) > 4]
        names = [t.upper() for t in hdr[-1]]
    rows = [ln.replace(",", " ").split() for ln in text.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    rows = [r[:len(names)] for r in rows if len(r) >= len(names)]
    if not rows:
        raise ValueError("cannot parse KMA response:\n" + text[:500])
    return pd.DataFrame(rows, columns=names).apply(pd.to_numeric, errors="coerce")


