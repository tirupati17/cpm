#!/usr/bin/env bash
# CPM — One-command setup for Cross-Project Memory
# Usage: ./scripts/setup-memory-system.sh [--backfill N]

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
BACKFILL_COUNT=0

while [[ $# -gt 0 ]]; do
  case $1 in
    --backfill) BACKFILL_COUNT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

echo "=== CPM Setup ==="
echo "Workspace: $WORKSPACE"
echo ""

echo "Step 0: Detecting user..."
source "$WORKSPACE/scripts/detect-user.sh"
if [ -n "${CPM_USER_LOGIN:-}" ]; then
  echo "  ✓ User: ${CPM_USER_NAME} (@${CPM_USER_LOGIN})"
  echo "  ✓ Email: ${CPM_USER_EMAIL:-n/a}"
  echo "  ✓ Git author: ${CPM_USER_GIT_NAME}"
  echo "  ✓ Config saved to .cpm-user.conf"
else
  echo "  ⚠ Could not detect user. Install gh CLI or set git config user.name/email."
  echo "  Reports will show all commits (unfiltered)."
fi
echo ""

source "$WORKSPACE/scripts/detect-projects.sh"

if [ ${#CPM_PROJECTS[@]} -eq 0 ]; then
  echo "ERROR: No git repos found in $WORKSPACE"
  exit 1
fi

echo "Detected projects: ${CPM_PROJECTS[*]}"
echo ""

echo "Step 1: Creating directory structure..."
mkdir -p "$WORKSPACE/memory/summaries"
mkdir -p "$WORKSPACE/memory/projects"
mkdir -p "$WORKSPACE/memory/people"
mkdir -p "$WORKSPACE/memory/reports"
for project in "${CPM_PROJECTS[@]}"; do
  mkdir -p "$WORKSPACE/memory/changelogs/$project"
  echo "  ✓ memory/changelogs/$project/"
done
echo ""

echo "Step 2: Making scripts executable..."
chmod +x "$WORKSPACE/scripts/"*.sh
echo "  ✓ All scripts executable"
echo ""

echo "Step 3: Installing post-commit hooks..."
"$WORKSPACE/scripts/install-hooks.sh"
echo ""

if [ "$BACKFILL_COUNT" -gt 0 ]; then
  echo "Step 4: Backfilling last $BACKFILL_COUNT commits..."
  for project in "${CPM_PROJECTS[@]}"; do
    "$WORKSPACE/scripts/backfill.sh" "$project" "$BACKFILL_COUNT"
  done
  echo ""
fi

echo "Step 5: Generating summaries and TRUTH.md..."
"$WORKSPACE/scripts/summarize.sh"
"$WORKSPACE/scripts/generate-truth.sh"
echo ""

echo "=== CPM Setup Complete ==="
echo ""
echo "What happens now:"
echo "  • Every commit in your repos auto-creates a changelog"
echo "  • Summaries and TRUTH.md refresh automatically (background)"
echo "  • Claude Code reads TRUTH.md for instant cross-project state"
echo ""
echo "Manual commands:"
echo "  ./scripts/cpm-check.sh                    — Health check + briefing"
echo "  ./scripts/generate-report.sh              — Status report"
echo "  ./scripts/test-cpm.sh                     — Full test suite"
echo "  ./scripts/backfill.sh <project> <count>   — Backfill from git history"
echo "  ./scripts/summarize.sh [project]          — Regenerate summaries"
echo "  ./scripts/generate-truth.sh               — Regenerate TRUTH.md"
echo "  ./scripts/install-hooks.sh                — Reinstall hooks"
