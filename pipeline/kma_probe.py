"""기상청 API 허브 응답 형식 확인용 (GitHub Actions 에서 실행, 인증키는 KMA_APIHUB_KEY 비밀값).

    KMA_APIHUB_KEY=... python pipeline/kma_probe.py
"""
import os
import sys

import requests

BASE = "https://apihub.kma.go.kr/api/typ01/url/"
KEY = os.environ.get("KMA_APIHUB_KEY")

PROBES = [
    ("ASOS 일자료 도움말", "kma_sfcdd.php", {"tm": "20150715", "stn": "0", "help": "1"}),
    ("ASOS 일자료 1개 지점(서울 108)", "kma_sfcdd.php", {"tm": "20150715", "stn": "108", "help": "0"}),
    ("ASOS 일자료 기간(서울, 10일)", "kma_sfcdd3.php", {"tm1": "20150701", "tm2": "20150710", "stn": "108", "help": "1"}),
    ("일 평년값", "sfc_norm1.php", {"norm": "D", "tmst": "2021", "stn": "0", "MM1": "5", "DD1": "1", "MM2": "5", "DD2": "2", "help": "1"}),
    ("지점 정보", "stn_inf.php", {"inf": "SFC", "stn": "", "tm": "202410290900", "help": "1"}),
    ("ASOS 일자료 CSV(disp=0, 서울·강릉)", "kma_sfcdd.php", {"tm": "19910115", "stn": "108:105", "disp": "0", "help": "0"}),
]


def main():
    if not KEY:
        sys.exit("KMA_APIHUB_KEY 비밀값이 없습니다 (Settings → Secrets and variables → Actions)")
    for title, path, params in PROBES:
        print(f"\n===== {title}: {path} {params}")
        try:
            r = requests.get(BASE + path, params={**params, "authKey": KEY}, timeout=60)
        except requests.RequestException as e:
            print("  error", e)
            continue
        print(f"  HTTP {r.status_code}, {len(r.content)} bytes, encoding={r.encoding}")
        text = r.content.decode("euc-kr", errors="replace") if b"\xb0" in r.content[:2000] else r.text
        lines = text.splitlines()
        for ln in lines[:70]:
            print("  |", ln[:220])
        if len(lines) > 70:
            print(f"  | ... ({len(lines)} lines)")


def parsed_sample():
    import kma

    print("\n===== kma.sfcdd_day 해석 결과 (2015-07-15)")
    d = kma.sfcdd_day("20150715")
    print(f"  지점 수 {len(d)}")
    for stn in (108, 105, 184):
        rec = d.get(stn)
        if rec:
            print(f"  {stn}:", {c: rec.get(c) for c in ("TM", "STN", *kma.ELEMENTS.values())})


if __name__ == "__main__":
    main()
    parsed_sample()
