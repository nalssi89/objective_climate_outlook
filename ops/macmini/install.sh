#!/bin/zsh
# 맥 미니에 07:10 트리거를 설치한다.  사용: zsh ops/macmini/install.sh
set -e
SRC="${0:A:h}"
DEST="$HOME/Projects/Claude/Work/outlook-trigger"
PLIST="$HOME/Library/LaunchAgents/kr.nalssi89.outlook-trigger.plist"

command -v gh >/dev/null || { echo "gh CLI 가 없습니다: brew install gh"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh 로그인이 필요합니다: gh auth login"; exit 1; }

mkdir -p "$DEST" "$HOME/Library/LaunchAgents"
cp "$SRC/trigger_outlook.sh" "$DEST/"
chmod +x "$DEST/trigger_outlook.sh"
sed "s#__HOME__#$HOME#g" "$SRC/kr.nalssi89.outlook-trigger.plist" > "$PLIST"

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "설치 완료: 매일 07:10 실행, 기록은 $DEST/trigger.log"
echo "지금 한 번 시험: launchctl kickstart gui/$(id -u)/kr.nalssi89.outlook-trigger"
