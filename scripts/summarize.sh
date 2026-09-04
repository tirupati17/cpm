#!/usr/bin/env bash
# CPM — Generate per-project summary from changelogs
# Usage: summarize.sh [project-name]   (no arg = all projects)

set -eu
# Note: no pipefail — `head -N` after sorts triggers SIGPIPE in upstream sort/uniq

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
SUMMARY_DIR="$WORKSPACE/memory/summaries"
CHANGELOG_BASE="$WORKSPACE/memory/changelogs"

mkdir -p "$SUMMARY_DIR"

summarize_project() {
  local project="$1"
  local cl_dir="$CHANGELOG_BASE/$project"
  local out="$SUMMARY_DIR/$project.md"
  local repo_dir="$WORKSPACE/$project"

  if [ ! -d "$cl_dir" ] || [ -z "$(ls -A "$cl_dir" 2>/dev/null)" ]; then
    echo "[summarize] No changelogs for $project, skipping."
    return
  fi

  local branch="unknown" commit_count=0
  if [ -d "$repo_dir/.git" ]; then
    branch=$(cd "$repo_dir" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    commit_count=$(cd "$repo_dir" && git rev-list --count HEAD 2>/dev/null || echo 0)
  fi

  local last_updated changelog_count
  last_updated=$(date "+%Y-%m-%d %H:%M:%S")
  changelog_count=$(ls "$cl_dir"/*.md 2>/dev/null | wc -l | tr -d ' ')

  cat > "$out" <<HEADER
# $project Summary

> Last updated: $last_updated
> Total commits in repo: $commit_count
> Changelogs tracked: $changelog_count
> Current branch: $branch

HEADER

  # Recent changes — last 14 days
  echo "## Recent Changes (last 14 days)" >> "$out"
  echo "" >> "$out"

  local cutoff
  cutoff=$(date -v-14d "+%Y-%m-%d" 2>/dev/null || date -d "14 days ago" "+%Y-%m-%d" 2>/dev/null || echo "2026-01-01")

  local found_recent=0
  for f in $(ls -r "$cl_dir"/*.md 2>/dev/null); do
    local fname fdate title hash
    fname=$(basename "$f")
    fdate="${fname:0:10}"
    if [[ "$fdate" > "$cutoff" ]] || [[ "$fdate" == "$cutoff" ]]; then
      title=$(head -1 "$f" | sed 's/^# //')
      hash=$(grep "| Hash" "$f" | head -1 | awk -F'|' '{print $3}' | tr -d ' ')
      echo "- **$fdate** (\`$hash\`): $title" >> "$out"
      found_recent=1
    fi
  done
  [ "$found_recent" -eq 0 ] && echo "_No changes in the last 14 days._" >> "$out"
  echo "" >> "$out"

  # All changes — grouped by date
  echo "## All Tracked Changes" >> "$out"
  echo "" >> "$out"

  local current_date=""
  for f in $(ls -r "$cl_dir"/*.md 2>/dev/null); do
    local fname fdate title hash
    fname=$(basename "$f")
    fdate="${fname:0:10}"
    title=$(head -1 "$f" | sed 's/^# //')
    hash=$(grep "| Hash" "$f" | head -1 | awk -F'|' '{print $3}' | tr -d ' ')

    if [ "$fdate" != "$current_date" ]; then
      echo "### $fdate" >> "$out"
      current_date="$fdate"
    fi
    echo "- (\`$hash\`) $title" >> "$out"
  done
  echo "" >> "$out"

  # Feature areas — group by conventional commit prefix
  echo "## Feature Areas" >> "$out"
  echo "" >> "$out"

  local all_messages=""
  for f in "$cl_dir"/*.md; do
    [ -f "$f" ] || continue
    local msg
    msg=$(head -1 "$f" | sed 's/^# //')
    all_messages="$all_messages
$msg"
  done

  for prefix in "feat" "fix" "refactor" "docs" "chore" "style" "perf" "test"; do
    local matches
    matches=$(echo "$all_messages" | grep -i "^${prefix}[:(]" | head -10 || true)
    if [ -n "$matches" ]; then
      echo "### ${prefix}" >> "$out"
      echo "$matches" | while IFS= read -r line; do
        [ -n "$line" ] && echo "- $line" >> "$out"
      done
      echo "" >> "$out"
    fi
  done

  # Non-conventional prefixes
  for prefix in "Add" "Fix" "Update" "Refactor" "Remove" "Implement" "Improve"; do
    local matches
    matches=$(echo "$all_messages" | grep -i "^${prefix} " | head -10 || true)
    if [ -n "$matches" ]; then
      echo "### ${prefix}" >> "$out"
      echo "$matches" | while IFS= read -r line; do
        [ -n "$line" ] && echo "- $line" >> "$out"
      done
      echo "" >> "$out"
    fi
  done

  # Frequently modified files
  echo "## Frequently Modified Files" >> "$out"
  echo "" >> "$out"

  local all_files=""
  for f in "$cl_dir"/*.md; do
    [ -f "$f" ] || continue
    local in_files=0
    while IFS= read -r line; do
      if [[ "$line" == "## Files Changed" ]]; then
        in_files=1
        continue
      fi
      if [[ "$line" == "## "* ]] && [ "$in_files" -eq 1 ]; then
        break
      fi
      if [ "$in_files" -eq 1 ] && [[ "$line" == "- "* ]]; then
        all_files="$all_files
${line#- }"
      fi
      # Also handle code-block format from new log-commit
      if [ "$in_files" -eq 1 ] && [[ "$line" =~ ^[A-Z][[:space:]] ]]; then
        # e.g., "M\tpath/to/file" or "A\tpath/to/file"
        local p
        p=$(echo "$line" | awk '{print $2}')
        [ -n "$p" ] && all_files="$all_files
$p"
      fi
    done < "$f"
  done

  echo "$all_files" | sort | uniq -c | sort -rn | head -15 | while read count filepath; do
    [ -n "$filepath" ] && echo "- \`$filepath\` ($count commits)" >> "$out"
  done
  echo "" >> "$out"

  echo "[summarize] $project → $out ($changelog_count changelogs)"
}

# Auto-detect or use provided arg
if [ -n "${1:-}" ]; then
  summarize_project "$1"
else
  source "$WORKSPACE/scripts/detect-projects.sh"
  for p in "${CPM_PROJECTS[@]}"; do
    summarize_project "$p"
  done
fi
