#!/bin/bash
# Schedule at 09:20 America/New_York on weekdays, e.g. crontab (machine clock in ET):
#   20 9 * * 1-5 /path/to/Apex_Master/apex_master_bot/run_today.sh >> /path/to/Apex_Master/apex_master_bot/logs/cron.log 2>&1
# Optional env: DISCORD_WEBHOOK_URL (alerts), ACCOUNT_SIZE (shows share count per 1R). Profile: reliability | runner.
cd "$(dirname "$0")" || exit 1
mkdir -p logs state ledger
exec python3 -m apex_master_bot live --profile "${APEX_PROFILE:-reliability}"
