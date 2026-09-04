#!/usr/bin/env bash
# CPM — Add a new reviewer to the Review Bot
# Usage:
#   ./scripts/add-reviewer.sh --name <name> --github <login> --platform ios|android|web|server
#   ./scripts/add-reviewer.sh --name <name> --github <login> --platform ios --pr 1520
#
# What it does:
#   1. Creates the learnings JSON file (empty patterns, ready to fill)
#   2. Harvests patterns from PRs (if --pr provided, requires GITHUB_TOKEN)
#   3. Updates CLAUDE.md reviewer table
#   4. Runs test to verify

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
LEARNINGS_DIR="$WORKSPACE/claude-review-bot/.github/actions/claude-review/learnings"

NAME=""
GITHUB=""
PLATFORM=""
PRS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --name) NAME="$2"; shift 2 ;;
    --github) GITHUB="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --pr) PRS+=("$2"); shift 2 ;;
    --help|-h)
      echo "Usage: ./scripts/add-reviewer.sh --name NAME --github USERNAME --platform ios|android|web|server [--pr NUMBER ...]"
      echo ""
      echo "Examples:"
      echo "  ./scripts/add-reviewer.sh --name iraida --github iraida-dev --platform ios"
      echo "  ./scripts/add-reviewer.sh --name jane --github janec --platform android --pr 42"
      exit 0
      ;;
    *) echo "Unknown arg: $1. Use --help for usage."; exit 1 ;;
  esac
done

if [ -z "$NAME" ] || [ -z "$GITHUB" ] || [ -z "$PLATFORM" ]; then
  echo "ERROR: --name, --github, and --platform are required."
  echo "Usage: ./scripts/add-reviewer.sh --name NAME --github USERNAME --platform ios|android|web|server [--pr NUMBER ...]"
  exit 1
fi

case "$PLATFORM" in
  ios|android|web|server) ;;
  *) echo "ERROR: --platform must be 'ios', 'android', 'web', or 'server'"; exit 1 ;;
esac

mkdir -p "$LEARNINGS_DIR"

FILENAME="${PLATFORM}-${NAME}.json"
FILEPATH="$LEARNINGS_DIR/$FILENAME"
TODAY=$(date '+%Y-%m-%d')

echo "=== CPM: Add Reviewer ==="
echo "  Name:     $NAME ($GITHUB)"
echo "  Platform: $PLATFORM"
echo "  File:     $FILENAME"
if [ ${#PRS[@]} -gt 0 ]; then
  echo "  PRs:      ${PRS[*]}"
fi
echo ""

if [ -f "$FILEPATH" ]; then
  echo "File already exists: $FILEPATH"
  echo "  Skipping creation (will harvest new PRs if provided)."
else
  pr_json="[]"
  if [ ${#PRS[@]} -gt 0 ]; then
    pr_json="["
    for i in "${!PRS[@]}"; do
      [ "$i" -gt 0 ] && pr_json+=", "
      pr_json+="\"#${PRS[$i]}\""
    done
    pr_json+="]"
  fi

  cat > "$FILEPATH" <<ENDJSON
{
  "reviewer": "$NAME ($GITHUB)",
  "platform": "$PLATFORM",
  "last_updated": "$TODAY",
  "source_prs": $pr_json,
  "stats": {
    "total_comments": 0,
    "critical": 0,
    "major": 0,
    "minor": 0
  },
  "patterns": []
}
ENDJSON

  echo "Created: $FILEPATH"
fi

if [ ${#PRS[@]} -gt 0 ]; then
  HARVEST_SCRIPT="$WORKSPACE/claude-review-bot/scripts/harvest-pr-comments.js"

  if [ ! -f "$HARVEST_SCRIPT" ]; then
    echo "WARN: harvest script not found at $HARVEST_SCRIPT"
    echo "  Skipping auto-harvest. Add patterns manually to $FILEPATH"
  else
    case "$PLATFORM" in
      ios) REPO="${CPM_REPO_IOS:-your-org/your-ios-repo}" ;;
      android) REPO="${CPM_REPO_ANDROID:-your-org/your-android-repo}" ;;
      web) REPO="${CPM_REPO_WEB:-your-org/your-web-repo}" ;;
      server) REPO="${CPM_REPO_SERVER:-your-org/your-server-repo}" ;;
    esac

    for pr in "${PRS[@]}"; do
      echo ""
      echo "Harvesting patterns from $REPO#$pr (reviewer: $GITHUB)..."
      if node "$HARVEST_SCRIPT" --repo "$REPO" --pr "$pr" --reviewer "$GITHUB" --platform "$PLATFORM" 2>&1; then
        echo "  Harvested PR #$pr"
      else
        echo "  WARN: Failed to harvest PR #$pr (needs GITHUB_TOKEN + ANTHROPIC_API_KEY)"
        echo "  You can harvest later: node claude-review-bot/scripts/harvest-pr-comments.js --repo $REPO --pr $pr --reviewer $GITHUB"
      fi
    done
  fi
fi

CLAUDE_MD="$WORKSPACE/CLAUDE.md"

if [ -f "$CLAUDE_MD" ]; then
  pattern_count=$(grep -c '"id"' "$FILEPATH" 2>/dev/null || true)
  pattern_count=${pattern_count:-0}

  critical=$(grep '"severity"' "$FILEPATH" 2>/dev/null | grep -c '"critical"' || true)
  critical=${critical:-0}
  major=$(grep '"severity"' "$FILEPATH" 2>/dev/null | grep -c '"major"' || true)
  major=${major:-0}
  minor=$(grep '"severity"' "$FILEPATH" 2>/dev/null | grep -c '"minor"' || true)
  minor=${minor:-0}
  severity_breakdown="${critical} critical, ${major} major, ${minor} minor"

  name_capitalized="$(echo "$NAME" | awk '{print toupper(substr($0,1,1)) tolower(substr($0,2))}')"
  platform_capitalized="$(echo "$PLATFORM" | awk '{print toupper(substr($0,1,1)) tolower(substr($0,2))}')"
  new_row="| ${platform_capitalized} | ${name_capitalized} | \`${FILENAME}\` | ${pattern_count} patterns (${severity_breakdown}) |"

  if grep -q "$FILENAME" "$CLAUDE_MD" 2>/dev/null; then
    echo "Reviewer already in CLAUDE.md table. Updating pattern count..."
    sed -i '' "s|.*${FILENAME}.*|${new_row}|" "$CLAUDE_MD"
  else
    if grep -q "To add a reviewer" "$CLAUDE_MD" 2>/dev/null; then
      line_num=$(grep -n "To add a reviewer" "$CLAUDE_MD" | head -1 | cut -d: -f1)
      { head -n "$((line_num - 1))" "$CLAUDE_MD"; echo "$new_row"; tail -n +"$line_num" "$CLAUDE_MD"; } > "$CLAUDE_MD.tmp" && mv "$CLAUDE_MD.tmp" "$CLAUDE_MD"
      echo "Added reviewer to CLAUDE.md table."
    else
      echo "WARN: Could not find reviewer table in CLAUDE.md. Add manually:"
      echo "  $new_row"
    fi
  fi
fi

echo ""
echo "=== Done ==="
pattern_count=$(grep -c '"id"' "$FILEPATH" 2>/dev/null || true)
pattern_count=${pattern_count:-0}
echo "  File:     $FILEPATH"
echo "  Patterns: $pattern_count"
echo ""

if [ "$pattern_count" -eq 0 ]; then
  echo "No patterns yet. Two ways to add them:"
  echo ""
  echo "  1. Auto-harvest from a PR:"
  echo "     node claude-review-bot/scripts/harvest-pr-comments.js \\"
  echo "       --repo your-org/your-${PLATFORM}-repo --pr NUMBER --reviewer $GITHUB"
  echo ""
  echo "  2. Ask Claude Code:"
  echo "     \"Harvest review patterns from PR #1234 for $NAME\""
  echo ""
fi

echo "The Review Bot will now enforce $NAME's patterns on all $PLATFORM PRs."
