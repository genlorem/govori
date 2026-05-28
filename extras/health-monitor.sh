#!/usr/bin/env bash
# Govori relay uptime monitor — VPS cron every 5 min.
# Pings the public /health and alerts to Telegram ONLY on state transitions
# (up→down, down→up), so no spam. Critical during the internal-testing phase:
# if the relay dies, every tester's dictation silently fails.
#
# Cron (VPS, TZ=UTC):
#   */5 * * * * flock -n -E 0 /tmp/govori-monitor.lock /home/gen/Projects/govori/extras/health-monitor.sh
set -uo pipefail

URL="https://govori.io/health"
STATE_FILE="$HOME/.config/govori/monitor-state"
LOG="$HOME/life/state/logs/govori-monitor.log"
ENV_FILE="$HOME/.config/digest-bot/env"
mkdir -p "$(dirname "$LOG")"

now() { date -u +%FT%TZ; }
prev="$(cat "$STATE_FILE" 2>/dev/null || echo unknown)"

# Healthy = HTTP 200 AND body contains "ok":true
code="$(curl -s -o /tmp/govori-health.out -w '%{http_code}' --max-time 10 "$URL" 2>/dev/null || echo 000)"
if [[ "$code" == "200" ]] && grep -q '"ok":true' /tmp/govori-health.out 2>/dev/null; then
    cur="up"
else
    cur="down"
fi

echo "$(now) check=$cur code=$code prev=$prev" >> "$LOG"

notify() {
    [[ -f "$ENV_FILE" ]] || { echo "$(now) no digest-bot env, skip TG" >> "$LOG"; return; }
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    curl -s --max-time 10 "https://api.telegram.org/bot${DIGEST_BOT_TOKEN}/sendMessage" \
        -d chat_id="${DIGEST_ADMIN_CHAT_ID}" -d text="$1" >/dev/null 2>&1 || true
}

if [[ "$cur" != "$prev" ]]; then
    if [[ "$cur" == "down" ]]; then
        notify "🔴 Govori relay DOWN — govori.io/health не отвечает (code=$code). Диктовка у тестеров не работает."
    elif [[ "$prev" == "down" ]]; then
        notify "🟢 Govori relay снова UP — govori.io/health отвечает."
    fi
    echo "$cur" > "$STATE_FILE"
fi
