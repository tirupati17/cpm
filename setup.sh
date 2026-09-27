#!/usr/bin/env bash
# CPM — Interactive setup wizard
# Usage: ./setup.sh

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")" && pwd)"

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

prompt_with_default() {
  local prompt="$1"
  local default="$2"
  local result
  if [ -n "$default" ]; then
    printf "  %s [%s]: " "$prompt" "$default"
  else
    printf "  %s: " "$prompt"
  fi
  read -r result
  echo "${result:-$default}"
}

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  CPM Setup Wizard${NC}"
echo -e "${BOLD}  Cross-Project Memory for any coding agent${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Fresh-fork bootstrap: if the workspace has no agent instructions yet, write
# AGENTS.md from the template with the project name filled in. AGENTS.md is
# the file most coding agents read (Codex, Cursor, GitHub Copilot and others).
# An existing AGENTS.md or CLAUDE.md is never touched.
if [ ! -f "$WORKSPACE/AGENTS.md" ] && [ ! -f "$WORKSPACE/CLAUDE.md" ] && [ -f "$WORKSPACE/templates/AGENTS.md" ]; then
  echo -e "${CYAN}Looks like a fresh fork. Let's write your AGENTS.md.${NC}"
  echo ""
  _proj_name=$(prompt_with_default "Project name" "My Project")
  _proj_one_liner=$(prompt_with_default "One-line description" "Cross-project codebase.")
  sed -e "s|{{PROJECT_NAME}}|${_proj_name}|g" \
      -e "s|{{ONE_LINE_DESCRIPTION}}|${_proj_one_liner}|g" \
      "$WORKSPACE/templates/AGENTS.md" > "$WORKSPACE/AGENTS.md"
  echo ""
  echo -e "  ${GREEN}✓${NC} Created AGENTS.md from templates/AGENTS.md"
  echo -e "  ${DIM}Edit it later to fill in the Platform Repos table for your sub-repos.${NC}"
  echo ""
fi

# Agents that read their own file name get a one-line pointer to AGENTS.md,
# so every agent follows the same instructions. Both Claude Code (CLAUDE.md)
# and Gemini CLI (GEMINI.md) expand an @file line into that file's contents.
if [ -f "$WORKSPACE/AGENTS.md" ]; then
  for _pointer in CLAUDE.md GEMINI.md; do
    if [ ! -e "$WORKSPACE/$_pointer" ]; then
      printf '%s\n' "@AGENTS.md" > "$WORKSPACE/$_pointer"
      echo -e "  ${GREEN}✓${NC} Created $_pointer pointing at AGENTS.md"
    fi
  done
  echo ""
fi

echo -e "${CYAN}Step 1/4: Who are you?${NC}"
echo ""

_auto_name=""
_auto_login=""
_auto_email=""

if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
  _auto_login=$(gh api user --jq '.login // empty' 2>/dev/null || echo "")
  _auto_name=$(gh api user --jq '.name // empty' 2>/dev/null || echo "")
  _auto_email=$(gh api user --jq '.email // empty' 2>/dev/null || echo "")
fi

[ -z "$_auto_name" ] && _auto_name=$(git config --global user.name 2>/dev/null || echo "")
[ -z "$_auto_email" ] && _auto_email=$(git config --global user.email 2>/dev/null || echo "")

if [ -n "$_auto_login" ] || [ -n "$_auto_name" ]; then
  echo -e "  ${DIM}Auto-detected:${NC}"
  [ -n "$_auto_name" ] && echo -e "    Name:   $_auto_name"
  [ -n "$_auto_login" ] && echo -e "    GitHub: @$_auto_login"
  [ -n "$_auto_email" ] && echo -e "    Email:  $_auto_email"
  echo ""
fi

USER_NAME=$(prompt_with_default "Your name" "$_auto_name")
USER_EMAIL=$(prompt_with_default "Your email" "$_auto_email")
USER_LOGIN=$(prompt_with_default "GitHub username" "$_auto_login")
USER_GIT_NAME="$USER_NAME"

echo ""
echo -e "  ${GREEN}+${NC} Identity: ${USER_NAME} (@${USER_LOGIN})"
echo ""

echo -e "${CYAN}Step 2/4: Which repos do you work on?${NC}"
echo ""

source "$WORKSPACE/scripts/detect-projects.sh"

if [ ${#CPM_PROJECTS[@]} -gt 0 ]; then
  echo -e "  ${DIM}Already in workspace:${NC}"
  for repo in "${CPM_PROJECTS[@]}"; do
    branch=$(cd "$WORKSPACE/$repo" && git branch --show-current 2>/dev/null || echo "detached")
    echo -e "    ${GREEN}+${NC} $repo ($branch)"
  done
  echo ""
fi

echo "  Paste additional repo URLs to clone (one per line)."
echo "  Press Enter on an empty line when done (skip if already done)."
echo -e "  ${DIM}Example: git@github.com:your-org/your-android-repo.git${NC}"
echo ""

CLONE_URLS=()
while true; do
  printf "  Repo URL: "
  read -r url
  [ -z "$url" ] && break
  CLONE_URLS+=("$url")
done

CLONED=()
if [ ${#CLONE_URLS[@]} -gt 0 ]; then
  echo ""
  for url in "${CLONE_URLS[@]}"; do
    repo_name=$(basename "$url" .git)

    if [ -d "$WORKSPACE/$repo_name" ]; then
      echo -e "  ${YELLOW}!${NC} $repo_name already exists, skipping clone"
      CLONED+=("$repo_name")
      continue
    fi

    echo -e "  Cloning ${BOLD}$repo_name${NC}..."
    if git clone "$url" "$WORKSPACE/$repo_name" 2>&1 | tail -1; then
      CLONED+=("$repo_name")
      echo -e "  ${GREEN}+${NC} $repo_name cloned"
    else
      echo -e "  ${RED}x${NC} Failed to clone $url"
    fi
  done
  # Re-detect after cloning
  source "$WORKSPACE/scripts/detect-projects.sh"
fi

echo ""

if [ ${#CPM_PROJECTS[@]} -eq 0 ]; then
  echo -e "  ${RED}No repos found.${NC} Clone at least one repo and re-run ./setup.sh"
  exit 1
fi

echo -e "  ${GREEN}+${NC} Workspace repos: ${CPM_PROJECTS[*]}"
echo ""

echo -e "${CYAN}Step 3/4: Optional config${NC}"
echo ""

SLACK_CHANNEL=$(prompt_with_default "Slack channel ID for reports (press Enter to skip)" "")
echo ""

echo -e "${CYAN}Step 4/4: Setting up CPM...${NC}"
echo ""

cat > "$WORKSPACE/.cpm-user.conf" <<EOF
# CPM user config — auto-generated by setup.sh, edit if needed
CPM_USER_NAME="${USER_NAME}"
CPM_USER_LOGIN="${USER_LOGIN}"
CPM_USER_EMAIL="${USER_EMAIL}"
CPM_USER_GIT_NAME="${USER_GIT_NAME}"
EOF
echo -e "  ${GREEN}+${NC} .cpm-user.conf created (local only, gitignored)"

if [ -n "$SLACK_CHANNEL" ]; then
  mkdir -p "$WORKSPACE/memory"
  cat > "$WORKSPACE/memory/reference_slack_channel.md" <<EOF
---
name: Slack channel for reports
type: reference
---
Channel ID: ${SLACK_CHANNEL}
EOF
  echo -e "  ${GREEN}+${NC} Slack channel saved"
fi

echo -e "  ${DIM}Installing hooks + backfilling changelogs...${NC}"
"$WORKSPACE/scripts/setup-memory-system.sh" --backfill 30 2>&1 | while IFS= read -r line; do
  case "$line" in
    *"✓"*|*"Step"*|*"Detected"*|*"=== CPM"*|*"Complete"*)
      echo "    $line" ;;
  esac
done

echo ""
echo -e "  ${DIM}Running verification...${NC}"
VERIFY_PASS=true

for repo in "${CPM_PROJECTS[@]}"; do
  hook="$WORKSPACE/$repo/.git/hooks/post-commit"
  if [ -f "$hook" ] && grep -q "\[cpm\]" "$hook" 2>/dev/null; then
    echo -e "    ${GREEN}+${NC} $repo: hooks installed"
  else
    echo -e "    ${RED}x${NC} $repo: hooks missing"
    VERIFY_PASS=false
  fi
done

if [ -f "$WORKSPACE/TRUTH.md" ]; then
  echo -e "    ${GREEN}+${NC} TRUTH.md generated"
else
  echo -e "    ${RED}x${NC} TRUTH.md missing"
  VERIFY_PASS=false
fi

"$WORKSPACE/scripts/link-skills.sh" >/dev/null 2>&1
skill_count=$(grep -c '^- \*\*' "$WORKSPACE/skills/INDEX.md" 2>/dev/null || true)
echo -e "    ${GREEN}+${NC} ${skill_count:-0} skills listed in skills/INDEX.md and linked for agents"

for repo in "${CPM_PROJECTS[@]}"; do
  count=$(find "$WORKSPACE/memory/changelogs/$repo" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
  if [ "$count" -gt 0 ]; then
    echo -e "    ${GREEN}+${NC} $repo: $count changelogs"
  else
    echo -e "    ${YELLOW}!${NC} $repo: no changelogs yet"
  fi
done

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Setup complete!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  What happens now:"
echo ""
echo "  1. Open this directory in your coding agent (Claude Code, Codex, Cursor,"
echo "     Gemini CLI, GitHub Copilot, Aider...):"
echo -e "     ${DIM}cd $WORKSPACE${NC}"
echo ""
echo "  2. The agent reads AGENTS.md, which points it at TRUTH.md = full project context"
echo ""
echo "  3. Every commit auto-logs to memory/changelogs/"
echo ""
echo "  4. Store, billing, ads and push helpers ask for credentials on first use"
echo "     and keep them in ~/.config/cpm/<project>/, never in a repo:"
echo -e "     ${DIM}toolkit/bin/cpm${NC}                 list every helper"
echo -e "     ${DIM}toolkit/bin/cpm creds setup play${NC} answer the questions once"
echo ""
echo "  Useful commands:"
echo -e "    ${DIM}cpmcheck${NC}       — Health check (run every session)"
echo -e "    ${DIM}cpmreport${NC}      — Status report"
echo -e "    ${DIM}cpmtest${NC}        — Run diagnostic checks"
echo -e "    ${DIM}cpmreviewer${NC}    — Onboard a code reviewer"
echo ""
if [ "$VERIFY_PASS" = false ]; then
  echo -e "  ${YELLOW}Some checks failed. Run ./scripts/test-cpm.sh for details.${NC}"
  echo ""
fi
