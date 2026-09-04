#!/usr/bin/env bash
# CPM — Cross-project status report
# Usage: ./scripts/generate-report.sh [--hours 24] [--output slack|markdown|terminal] [--all]

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
HOURS=24
OUTPUT="terminal"
REPORT_DIR="$WORKSPACE/memory/reports"

while [[ $# -gt 0 ]]; do
  case $1 in
    --hours) HOURS="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --all) SHOW_ALL_USERS=1; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

source "$WORKSPACE/scripts/detect-projects.sh"

SHOW_ALL_USERS="${SHOW_ALL_USERS:-0}"
source "$WORKSPACE/scripts/detect-user.sh" 2>/dev/null || true
AUTHOR_FILTER=()
if [ "$SHOW_ALL_USERS" -eq 0 ] && [ -n "${CPM_USER_GIT_NAME:-}" ]; then
  AUTHOR_FILTER=("--author=${CPM_USER_GIT_NAME}")
fi

if [ ${#CPM_PROJECTS[@]} -eq 0 ]; then
  echo "No projects detected. Nothing to report."
  exit 1
fi

TODAY=$(date '+%Y-%m-%d')
YESTERDAY=$(date -v-1d '+%Y-%m-%d' 2>/dev/null || date -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || echo "")
NOW=$(date '+%H:%M')
DAY_NAME=$(date '+%A')

mkdir -p "$REPORT_DIR"

SEP="------------------------------------------------------------"

R=""

R+="**CPM STATUS REPORT** | ${CPM_WORKSPACE_NAME:-$(basename "$ROOT")}"$'\n'
if [ -n "${CPM_USER_NAME:-}" ] && [ "$SHOW_ALL_USERS" -eq 0 ]; then
  R+="**${CPM_USER_NAME}** (@${CPM_USER_LOGIN}) | **${DAY_NAME}, ${TODAY} at ${NOW}**"$'\n'
else
  R+="**${DAY_NAME}, ${TODAY} at ${NOW}**"$'\n'
fi
R+="${SEP}"$'\n'
R+=""$'\n'

for project in "${CPM_PROJECTS[@]}"; do
  repo_dir="$WORKSPACE/$project"
  [ -d "$repo_dir/.git" ] || continue

  branch=$(cd "$repo_dir" && git branch --show-current 2>/dev/null || echo "detached")
  platform="unknown"
  case "$project" in
    *ios*|*iOS*) platform="iOS" ;;
    *android*|*Android*) platform="Android" ;;
    *admin*) platform="Admin Panel" ;;
    *landing*) platform="Landing Page" ;;
    *server*) platform="Server" ;;
    *voice*) platform="Voice Agent" ;;
    *web*|*Web*) platform="Web" ;;
  esac

  R+="**${project}** | ${platform} | \`${branch}\`"$'\n'
  R+="${SEP}"$'\n'
  R+=""$'\n'

  R+="**YESTERDAY**"$'\n'
  R+=""$'\n'

  if [ -n "$YESTERDAY" ]; then
    yesterday_commits=$(cd "$repo_dir" && git log --oneline ${AUTHOR_FILTER[@]+"${AUTHOR_FILTER[@]}"} --after="${YESTERDAY} 00:00" --before="${TODAY} 00:00" 2>/dev/null | grep -v '^[a-f0-9]* docs:' || echo "")
  else
    yesterday_commits=""
  fi

  if [ -n "$yesterday_commits" ]; then
    while IFS= read -r line; do
      hash="${line%% *}"
      msg="${line#* }"
      R+="  - ${msg} (\`${hash}\`)"$'\n'
    done <<< "$yesterday_commits"
  else
    R+="  - No commits yesterday"$'\n'
  fi
  R+=""$'\n'

  R+="**TODAY**"$'\n'
  R+=""$'\n'

  today_commits=$(cd "$repo_dir" && git log --oneline ${AUTHOR_FILTER[@]+"${AUTHOR_FILTER[@]}"} --since="${TODAY} 00:00" 2>/dev/null | grep -v '^[a-f0-9]* docs:' || echo "")

  if [ -n "$today_commits" ]; then
    today_count=$(echo "$today_commits" | wc -l | tr -d ' ')
    while IFS= read -r line; do
      hash="${line%% *}"
      msg="${line#* }"
      R+="  - ${msg} (\`${hash}\`)"$'\n'
    done <<< "$today_commits"

    if [ "$today_count" -gt 0 ]; then
      stats=$(cd "$repo_dir" && git diff --stat "HEAD~${today_count}" HEAD 2>/dev/null | tail -1 || echo "")
      if [ -n "$stats" ]; then
        R+="  - **Stats**: ${stats}"$'\n'
      fi
    fi
  else
    R+="  - No commits yet today"$'\n'
  fi
  R+=""$'\n'

  R+="**BLOCKERS**"$'\n'
  R+=""$'\n'

  blockers_found=0

  dirty=$(cd "$repo_dir" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [ "$dirty" -gt 0 ]; then
    R+="  - ${dirty} uncommitted file(s) in working tree"$'\n'
    blockers_found=1
  fi

  unpushed=$(cd "$repo_dir" && git log --oneline @{u}..HEAD 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  if [ "$unpushed" -gt 0 ]; then
    R+="  - ${unpushed} unpushed commit(s) — not yet on remote"$'\n'
    blockers_found=1
  fi

  conflicts=$(cd "$repo_dir" && git diff --name-only --diff-filter=U 2>/dev/null | wc -l | tr -d ' ')
  if [ "$conflicts" -gt 0 ]; then
    R+="  - **CONFLICT**: ${conflicts} file(s) with merge conflicts"$'\n'
    blockers_found=1
  fi

  if [ "$blockers_found" -eq 0 ]; then
    R+="  - None"$'\n'
  fi
  R+=""$'\n'

  R+="**BUILD**"$'\n'
  R+=""$'\n'

  latest_tag=$(cd "$repo_dir" && git tag --sort=-version:refname 2>/dev/null | head -1 || echo "")
  if [ -n "$latest_tag" ]; then
    R+="  - **Latest version**: ${latest_tag}"$'\n'
  fi

  base_branch=""
  for candidate in main master release develop dev; do
    if cd "$repo_dir" && git rev-parse --verify "$candidate" &>/dev/null; then
      base_branch="$candidate"
      break
    fi
  done
  if [ -n "$base_branch" ] && [ "$base_branch" != "$branch" ]; then
    branch_commits=$(cd "$repo_dir" && git rev-list --count "${base_branch}..HEAD" 2>/dev/null || echo "?")
    R+="  - **Branch**: \`${branch}\` (${branch_commits} commits ahead of ${base_branch})"$'\n'
  else
    R+="  - **Branch**: \`${branch}\`"$'\n'
  fi

  last_date=$(cd "$repo_dir" && git log -1 --date=format:'%Y-%m-%d %H:%M' --format='%cd' 2>/dev/null || echo "N/A")
  R+="  - **Last activity**: ${last_date}"$'\n'

  R+=""$'\n'
  R+="${SEP}"$'\n'
  R+=""$'\n'
done

R+="**CROSS-PLATFORM ALERTS**"$'\n'
R+=""$'\n'

if [ -f "$WORKSPACE/TRUTH.md" ]; then
  alerts=$(grep -A 20 "Cross-Platform Alerts" "$WORKSPACE/TRUTH.md" 2>/dev/null | grep "^-" | head -5 || echo "")
  if [ -n "$alerts" ]; then
    while IFS= read -r line; do
      [ -n "$line" ] && R+="  ${line}"$'\n'
    done <<< "$alerts"
  else
    R+="  - None"$'\n'
  fi
else
  R+="  - TRUTH.md not found — run ./scripts/generate-truth.sh"$'\n'
fi
R+=""$'\n'

R+="**SUGGESTIONS**"$'\n'
R+=""$'\n'

suggestions_found=0

for project in "${CPM_PROJECTS[@]}"; do
  repo_dir="$WORKSPACE/$project"
  [ -d "$repo_dir/.git" ] || continue

  last_epoch=$(cd "$repo_dir" && git log -1 --format='%ct' 2>/dev/null || echo "0")
  now_epoch=$(date +%s)
  age_days=$(( (now_epoch - last_epoch) / 86400 ))
  if [ "$age_days" -ge 3 ]; then
    R+="  - ${project}: No commits in ${age_days} days — branch may be stale"$'\n'
    suggestions_found=1
  fi

  dirty=$(cd "$repo_dir" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [ "$dirty" -gt 10 ]; then
    R+="  - ${project}: ${dirty} uncommitted files — consider committing or stashing"$'\n'
    suggestions_found=1
  fi
done

if [ -f "$WORKSPACE/TRUTH.md" ]; then
  if [ "$(uname)" = "Darwin" ]; then
    truth_age=$(( $(date +%s) - $(stat -f %m "$WORKSPACE/TRUTH.md") ))
  else
    truth_age=$(( $(date +%s) - $(stat -c %Y "$WORKSPACE/TRUTH.md") ))
  fi
  truth_hours=$((truth_age / 3600))
  if [ "$truth_hours" -ge 4 ]; then
    R+="  - TRUTH.md is ${truth_hours}h old — consider running ./scripts/generate-truth.sh"$'\n'
    suggestions_found=1
  fi
fi

if [ "$suggestions_found" -eq 0 ]; then
  R+="  - All good — no action needed"$'\n'
fi
R+=""$'\n'

R+="**REVIEW BOT**"$'\n'
R+=""$'\n'

learnings_dir="$WORKSPACE/claude-review-bot/.github/actions/claude-review/learnings"
if [ -d "$learnings_dir" ] && [ -n "$(ls -A "$learnings_dir" 2>/dev/null)" ]; then
  for f in "$learnings_dir"/*.json; do
    [ -f "$f" ] || continue
    fname=$(basename "$f" .json)
    total_p=$(grep -c '"id"' "$f" 2>/dev/null || echo "0")
    critical=$(grep '"severity"' "$f" 2>/dev/null | grep -c '"critical"' || echo "0")
    major=$(grep '"severity"' "$f" 2>/dev/null | grep -c '"major"' || echo "0")
    minor=$(grep '"severity"' "$f" 2>/dev/null | grep -c '"minor"' || echo "0")
    R+="  - **${fname}**: ${total_p} patterns (${critical} critical, ${major} major, ${minor} minor)"$'\n'
  done
else
  R+="  - No review bot configured — run ./scripts/add-reviewer.sh"$'\n'
fi
R+=""$'\n'

R+="**INFRASTRUCTURE**"$'\n'
R+=""$'\n'

total_changelogs=0
for project in "${CPM_PROJECTS[@]}"; do
  changelog_dir="$WORKSPACE/memory/changelogs/$project"
  if [ -d "$changelog_dir" ]; then
    if [ "$SHOW_ALL_USERS" -eq 0 ] && [ -n "${CPM_USER_GIT_NAME:-}" ]; then
      c=$( (grep -rl "| Author    | ${CPM_USER_GIT_NAME}" "$changelog_dir" 2>/dev/null || true) | wc -l | tr -d ' ')
      today_c=$( (find "$changelog_dir" -name "${TODAY}*.md" -exec grep -l "| Author    | ${CPM_USER_GIT_NAME}" {} + 2>/dev/null || true) | wc -l | tr -d ' ')
    else
      c=$(find "$changelog_dir" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
      today_c=$(find "$changelog_dir" -name "${TODAY}*.md" 2>/dev/null | wc -l | tr -d ' ')
    fi
    R+="  - **${project}**: ${c} changelogs (${today_c} today)"$'\n'
    total_changelogs=$((total_changelogs + c))
  fi
done

memory_files=$(find "$WORKSPACE/memory" -name '*.md' -not -path '*/changelogs/*' 2>/dev/null | wc -l | tr -d ' ')
R+="  - **Shared memory**: ${memory_files} files"$'\n'
R+="  - **TRUTH.md**: $([ -f "$WORKSPACE/TRUTH.md" ] && echo "active" || echo "missing")"$'\n'
R+=""$'\n'

R+="**INSTALL**"$'\n'
R+=""$'\n'

INSTALL_CONF="$WORKSPACE/.cpm-install.conf"
if [ -f "$INSTALL_CONF" ]; then
  source "$INSTALL_CONF"
fi

for project in "${CPM_PROJECTS[@]}"; do
  repo_dir="$WORKSPACE/$project"
  [ -d "$repo_dir/.git" ] || continue

  case "$project" in
    *android*)
      if [ -n "${INSTALL_ANDROID_CHANNEL:-}" ]; then
        R+="  - **Android**: ${INSTALL_ANDROID_CHANNEL}"$'\n'
        if [ -n "${INSTALL_ANDROID_STEPS:-}" ]; then
          while IFS= read -r step; do
            [ -n "$step" ] && R+="    ${step}"$'\n'
          done <<< "$INSTALL_ANDROID_STEPS"
        fi
      fi
      ;;
    *ios*)
      if [ -n "${INSTALL_IOS_VERSION:-}" ]; then
        R+="  - **iOS TestFlight**: version \`${INSTALL_IOS_VERSION}\` (latest build)"$'\n'
        if [ -n "${INSTALL_IOS_STEPS:-}" ]; then
          while IFS= read -r step; do
            [ -n "$step" ] && R+="    ${step}"$'\n'
          done <<< "$INSTALL_IOS_STEPS"
        fi
      fi
      ;;
    *landing*)
      if [ -n "${INSTALL_LANDING_URL:-}" ]; then
        R+="  - **Landing**: ${INSTALL_LANDING_URL}"$'\n'
      fi
      ;;
    *admin*)
      if [ -n "${INSTALL_ADMIN_URL:-}" ]; then
        R+="  - **Admin**: ${INSTALL_ADMIN_URL}"$'\n'
      fi
      ;;
  esac
done
R+=""$'\n'

R+="${SEP}"$'\n'
R+="**Generated by CPM** | ${TODAY} ${NOW}"$'\n'

case "$OUTPUT" in
  terminal)
    echo "$R"
    ;;
  markdown)
    outfile="$REPORT_DIR/report_${TODAY}.md"
    echo "$R" > "$outfile"
    echo "[cpm] report saved to $outfile"
    ;;
  slack)
    slack_r=$(echo "$R" | sed 's/\*\*\([^*]*\)\*\*/\*\1\*/g')
    slack_r=$(echo "$slack_r" | sed "s/${SEP}/───────────────────────────────/g")
    echo "$slack_r"
    ;;
  *)
    echo "Unknown output format: $OUTPUT (use: terminal, markdown, slack)"
    exit 1
    ;;
esac
