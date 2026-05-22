#!/usr/bin/env bash
# Installs a daily cron job to run the generator at 6:00 AM server time.
# Run once: bash cron-setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
LOG="$SCRIPT_DIR/generate.log"

CRON_LINE="0 6 * * * cd '$SCRIPT_DIR' && '$PYTHON' generate.py >> '$LOG' 2>&1"

# Add to crontab if not already present
( crontab -l 2>/dev/null | grep -F "generate.py" || true
  echo "$CRON_LINE"
) | sort -u | crontab -

echo "Cron job installed. It will run daily at 6:00 AM."
echo "Log file: $LOG"
echo ""
echo "To run manually for a specific date:"
echo "  python3 generate.py 2025-01-15"
echo ""
echo "Output goes to: boxscores/YYYYMMDD.html"
