#!/bin/bash
# Run every 5 minutes. Silent on a healthy day; alerts on a dead bot, a stuck feed or an unclosed trade.
cd "$(dirname "$0")" || exit 1
mkdir -p logs state ledger
set -a; [ -f .env ] && . ./.env; set +a
exec python3 -m apex_master_bot watchdog
