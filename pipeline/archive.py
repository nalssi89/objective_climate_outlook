"""매일 발표분 지도 자료를 날짜별로 보관한다 (GitHub Actions 에서 outlook.py 다음에 실행).

site/data/archive/<YYYY-MM-DD>/{manifest,map_1m,map_3m}.json 과 site/data/archive/index.json 을 만든다.
이전 게시본(gh-pages)의 archive 폴더를 site/data/archive 로 복사해 둔 상태에서 실행하면 누적된다.

    python pipeline/archive.py [--keep 45]
"""
import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "site" / "data" / "latest"
ARCHIVE = ROOT / "site" / "data" / "archive"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=45, help="보관 일수")
    args = ap.parse_args()

    manifest = json.load(open(LATEST / "manifest.json"))
    if manifest.get("demo"):
        print("DEMO 자료는 보관하지 않음")
        return
    day = manifest["issued"][:10]
    out = ARCHIVE / day
    out.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "map_1m.json", "map_3m.json"):
        if (LATEST / name).exists():
            shutil.copy2(LATEST / name, out / name)

    cutoff = (dt.date.fromisoformat(day) - dt.timedelta(days=args.keep)).isoformat()
    entries = []
    for d in sorted(ARCHIVE.iterdir()):
        if not d.is_dir():
            continue
        if d.name < cutoff:
            shutil.rmtree(d)
            continue
        try:
            m = json.load(open(d / "manifest.json"))
        except (OSError, ValueError):
            continue
        entries.append({"date": d.name, "issued": m["issued"],
                        "products": {k: {"periods": p["periods"]} for k, p in m["products"].items()}})
    entries.sort(key=lambda e: e["date"], reverse=True)
    json.dump({"updated": manifest["issued"], "issues": entries}, open(ARCHIVE / "index.json", "w"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"archive: {len(entries)} issues ({entries[-1]['date']} ~ {entries[0]['date']})")


if __name__ == "__main__":
    main()
