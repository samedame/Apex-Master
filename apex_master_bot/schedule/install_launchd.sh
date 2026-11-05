#!/bin/bash
# macOS: installs two background jobs for your user (bot starter + watchdog), each every 5 minutes, and starts them.
# They survive reboots. Remove with schedule/uninstall_launchd.sh. Run from anywhere:  bash schedule/install_launchd.sh
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$DIR/logs"
if ! python3 -c "import pandas, numpy, yfinance" 2>/dev/null; then
  echo "WARNING: python3 is missing pandas/numpy/yfinance. Run: python3 -m pip install -r \"$DIR/requirements.txt\""
fi
PYDIR="$(dirname "$(command -v python3)")"
make_job() {  # label script logname
  local label="$1" script="$2" log="$3" file="$AGENTS/$1.plist"
  cat > "$file" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/$script</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/$log.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/$log.err.log</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$PYDIR:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
</dict></plist>
PLIST
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$file"
  echo "installed $label"
}
make_job com.apexmaster.bot run_today.sh bot
make_job com.apexmaster.watchdog watchdog.sh watchdog
echo "Done. Check with: launchctl list | grep apexmaster"
echo "The Mac must be awake during market hours. 09:10 ET is 07:10 Mountain; to wake it automatically: sudo pmset repeat wakeorpoweron MTWRF 07:05 (use YOUR local time)."
