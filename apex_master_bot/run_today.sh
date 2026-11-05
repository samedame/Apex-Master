#!/bin/bash
# Scheduler entry point for the bot. Safe to call every 5 minutes at any hour: it only starts the bot when it
# should be running (trading day, 09:10-15:59 ET, not finished, not already running) and otherwise exits at once.
# Optional settings go in .env next to this file (never commit it):
#   DISCORD_WEBHOOK_URL=...   ACCOUNT_SIZE=25000   APEX_PROFILE=reliability   (or runner)
cd "$(dirname "$0")" || exit 1
mkdir -p logs state ledger
set -a; [ -f .env ] && . ./.env; set +a
CMD=(python3 -m apex_master_bot ensure --profile "${APEX_PROFILE:-reliability}")
# caffeinate (macOS) keeps the Mac awake while the bot runs
if command -v caffeinate >/dev/null 2>&1; then exec caffeinate -i "${CMD[@]}"; else exec "${CMD[@]}"; fi
