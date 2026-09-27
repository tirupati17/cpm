#!/usr/bin/env bash
# CPM — Post status report to Slack
# Usage: ./scripts/postreport.sh [--channel CHANNEL_ID] [--hours 24]
#
# Prerequisites:
#   export SLACK_BOT_TOKEN="xoxb-your-token"
#   Or configure in .env file at workspace root

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
CHANNEL=""
HOURS=24

while [[ $# -gt 0 ]]; do
  case $1 in
    --channel) CHANNEL="$2"; shift 2 ;;
    --hours) HOURS="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ -f "$WORKSPACE/.env" ]; then
  # shellcheck disable=SC1091
  source "$WORKSPACE/.env"
fi

if [ -z "$CHANNEL" ] && [ -f "$WORKSPACE/memory/reference_slack_channel.md" ]; then
  CHANNEL=$(grep -o 'C[A-Z0-9]\{8,\}' "$WORKSPACE/memory/reference_slack_channel.md" 2>/dev/null | head -1 || echo "")
fi

REPORT=$("$WORKSPACE/scripts/generate-report.sh" --hours "$HOURS" --output slack 2>&1)

if [ -z "${SLACK_BOT_TOKEN:-}" ]; then
  echo "No SLACK_BOT_TOKEN set. Printing report to terminal:"
  echo ""
  echo "───────────────────────────────────────"
  "$WORKSPACE/scripts/generate-report.sh" --hours "$HOURS" --output terminal
  echo "───────────────────────────────────────"
  echo ""
  echo "To post to Slack:"
  echo "  1. export SLACK_BOT_TOKEN='xoxb-your-token'"
  echo "  2. ./scripts/postreport.sh --channel C0XXXXX"
  echo ""
  echo "Or have your coding agent post it through its Slack integration."
  exit 0
fi

if [ -z "$CHANNEL" ]; then
  echo "ERROR: No channel specified."
  echo "  Usage: ./scripts/postreport.sh --channel C0XXXXX"
  echo "  Or save channel ID in memory/reference_slack_channel.md"
  exit 1
fi

response=$(curl -s -X POST "https://slack.com/api/chat.postMessage" \
  -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
  -H "Content-type: application/json" \
  --data "{
    \"channel\": \"${CHANNEL}\",
    \"text\": $(echo "$REPORT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
    \"unfurl_links\": false
  }")

ok=$(echo "$response" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("ok", False))' 2>/dev/null || echo "False")

if [ "$ok" = "True" ]; then
  echo "[cpm] Report posted to Slack channel ${CHANNEL}"
else
  echo "[cpm] Failed to post to Slack"
  echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
  exit 1
fi
