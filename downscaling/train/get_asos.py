"""ASOS 62지점 연중 일자료(1991~2026)와 일평년값(1991~2020, 1월1일~12월31일).
기존 climate_attribution/code/targets.py 의 kmahub 방식 함수(_get, parse_kma, STN62)를 재사용.
  KMA_AUTHKEY=... python get_asos.py OUTDIR
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from kma_util import _get, parse_kma, STN62  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KDS_RAW", "work/raw") + "/asos"); OUT.mkdir(parents=True, exist_ok=True)
for y in range(1991, 2027):
    f = OUT / f"asos_{y}.csv"
    if f.exists():
        continue
    tm2 = "20261103" if y == 2026 else f"{y}1231"
    txt = _get("kma_sfcdd3.php", dict(tm1=f"{y}0101", tm2=tm2, stn=":".join(map(str, STN62)), help=1))
    df = parse_kma(txt)
    df[["TM", "STN", "TA_AVG", "TA_MAX", "TA_MIN", "RN_DAY"]].to_csv(f, index=False)
    print(y, len(df), flush=True)
f = OUT / "norm_daily_all.csv"
if not f.exists():
    txt = _get("sfc_norm1.php", dict(norm="D", tmst=2021, stn=0, MM1=1, DD1=1, MM2=12, DD2=31, help=1))
    parse_kma(txt).to_csv(f, index=False); print("normals ok")
