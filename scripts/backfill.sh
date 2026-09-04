#!/usr/bin/env bash
# CPM — Backfill changelogs from existing git history
# Usage:
#   backfill.sh                       # all projects, last 20 commits each
#   backfill.sh <project> [count]     # one project, custom count

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"

backfill_one() {
  local project="$1"
  local count="${2:-20}"
  local repo_dir="$WORKSPACE/$project"
  local changelog_dir="$WORKSPACE/memory/changelogs/$project"

  if [ ! -d "$repo_dir/.git" ]; then
    echo "[backfill] $project is not a git repo, skipping."
    return
  fi

  mkdir -p "$changelog_dir"
  echo "[backfill] $project — last $count commits"

  cd "$repo_dir"

  local backfilled=0
  local skipped=0

  # Oldest first
  local hashes
  hashes=$(git log --format='%H' -"$count" | tail -r 2>/dev/null || git log --format='%H' -"$count" | tac)

  for full_hash in $hashes; do
    local hash commit_date outfile
    hash=$(git rev-parse --short "$full_hash")
    commit_date=$(git log -1 --date=short --format='%cd' "$full_hash")
    outfile="$changelog_dir/${commit_date}_${hash}.md"

    if [ -f "$outfile" ]; then
      skipped=$((skipped + 1))
      continue
    fi

    local time author branch_name message body files_changed stat_line
    time=$(git log -1 --format='%ci' "$full_hash" | cut -d' ' -f2 | cut -c1-8)
    author=$(git log -1 --format='%an' "$full_hash")
    branch_name=$(git branch --show-current 2>/dev/null || echo "unknown")
    message=$(git log -1 --format='%s' "$full_hash")
    body=$(git log -1 --format='%b' "$full_hash")
    files_changed=$(git diff-tree --no-commit-id --name-status -r "$full_hash" 2>/dev/null || echo "")
    stat_line=$(git diff-tree --no-commit-id --stat -r "$full_hash" 2>/dev/null | tail -1 || echo "")

    cat > "$outfile" <<ENDOFFILE
# $message

| Field     | Value |
|-----------|-------|
| Project   | $project |
| Date      | $commit_date $time |
| Hash      | $hash |
| Full Hash | $full_hash |
| Author    | $author |
| Branch    | $branch_name (at backfill time) |

## Files Changed

\`\`\`
$files_changed
\`\`\`

## Diff Summary

$stat_line
ENDOFFILE

    if [ -n "$body" ]; then
      cat >> "$outfile" <<ENDOFBODY

## Details

$body
ENDOFBODY
    fi

    backfilled=$((backfilled + 1))
  done

  echo "[backfill] $project — backfilled $backfilled, skipped $skipped (already exist)"
}

# Auto-detect or use provided arg
if [ -n "${1:-}" ]; then
  backfill_one "$1" "${2:-20}"
else
  source "$WORKSPACE/scripts/detect-projects.sh"
  for p in "${CPM_PROJECTS[@]}"; do
    backfill_one "$p" 20
  done
fi
