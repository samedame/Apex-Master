#!/bin/bash
for label in com.apexmaster.bot com.apexmaster.watchdog; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
  echo "removed $label"
done
