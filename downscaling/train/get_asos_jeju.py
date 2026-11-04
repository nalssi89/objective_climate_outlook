"""제주 4지점(184 제주, 185 고산, 188 성산, 189 서귀포) 연중 일자료 1991~2026 + 지점정보.
  KMA_AUTHKEY=... python get_asos_jeju.py OUTDIR"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from kma_util import _get, parse_kma  # noqa: E402

JEJU = [184, 185, 188, 189]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/user/kds/asos_jeju"); OUT.mkdir(parents=True, exist_ok=True)
for y in range(1991, 2027):
    f = OUT / f"asos_jeju_{y}.csv"
    if f.exists():
        continue
    tm2 = "20261103" if y == 2026 else f"{y}1231"
    df = parse_kma(_get("kma_sfcdd3.php", dict(tm1=f"{y}0101", tm2=tm2, stn=":".join(map(str, JEJU)), help=1)))
    df[["TM", "STN", "TA_AVG", "TA_MAX", "TA_MIN", "RN_DAY"]].to_csv(f, index=False)
    print(y, len(df), flush=True)
f = OUT / "stn_inf.csv"
if not f.exists():
    try:
        txt = _get("stn_inf.php", dict(inf="SFC", stn="", tm="", help=1))
        (OUT / "stn_inf_raw.txt").write_text(txt, encoding="utf-8")
        parse_kma(txt).to_csv(f, index=False); print("stn_inf ok")
    except Exception as e:  # noqa: BLE001
        print("stn_inf failed:", e)
