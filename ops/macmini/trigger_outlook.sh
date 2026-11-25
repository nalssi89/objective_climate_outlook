#!/bin/zsh
# 맥 미니에서 매일 07:10 KST 에 「객관기후예측 갱신」 워크플로를 workflow_dispatch 로 실행한다.
# GitHub 예약 실행(cron)은 몇 시간씩 늦게 시작되는 일이 잦아, 바깥에서 정시에 걸어 준다.
# 산출은 그대로 GitHub 러너에서 돈다. 필요: gh CLI 로그인(gh auth login).
#
# 잠들어 있다가 늦게 깨어났을 때는, 그날 07시 이후 발표가 이미 게시돼 있으면 건너뛴다.

REPO="nalssi89/objective_climate_outlook"
WORKFLOW="outlook.yml"
MANIFEST="https://raw.githubusercontent.com/${REPO}/gh-pages/data/latest/manifest.json"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

issued=$(curl -fsSL --max-time 30 "$MANIFEST" 2>/dev/null \
         | /usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin)['issued'])" 2>/dev/null)
today="$(TZ=Asia/Seoul date +%Y-%m-%d)T07:00"
if [[ -n "$issued" && "$issued" > "$today" ]]; then
  log "오늘 발표가 이미 게시됨($issued) → 건너뜀"
  exit 0
fi

for i in 1 2 3 4 5; do
  if gh workflow run "$WORKFLOW" -R "$REPO"; then
    log "워크플로 실행 요청 완료 (게시된 발표: ${issued:-없음})"
    exit 0
  fi
  log "실행 요청 실패($i/5), 60초 뒤 재시도"
  sleep 60
done
log "실행 요청 최종 실패 — GitHub 예약 실행(예비)이 대신 돈다"
exit 1
