#!/usr/bin/env bash
# CPM — Detect current user via GitHub CLI + git config
# Usage: source scripts/detect-user.sh
#
# Sets these variables:
#   CPM_USER_NAME     — display name (e.g., "Tirupati Balan")
#   CPM_USER_LOGIN    — GitHub username
#   CPM_USER_EMAIL    — email
#   CPM_USER_GIT_NAME — git author name for commit filtering
#
# Reads from .cpm-user.conf if it exists (cached).
# Otherwise auto-detects from gh CLI / git config and writes .cpm-user.conf.

if [ -z "${WORKSPACE:-}" ]; then
  if [ -n "${BASH_SOURCE[0]:-}" ]; then
    WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  else
    WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
  fi
fi

CPM_USER_CONF="$WORKSPACE/.cpm-user.conf"

# ── Load from cache ──────────────────────────────────────────
if [ -f "$CPM_USER_CONF" ]; then
  source "$CPM_USER_CONF"
fi

# ── Auto-detect if not cached ────────────────────────────────
if [ -z "${CPM_USER_LOGIN:-}" ] || [ -z "${CPM_USER_NAME:-}" ] || [ "${CPM_USER_NAME:-}" = "None" ]; then

  CPM_USER_LOGIN=""
  CPM_USER_NAME=""
  CPM_USER_EMAIL=""
  CPM_USER_GIT_NAME=""

  # Try GitHub CLI for login
  if command -v gh &>/dev/null; then
    CPM_USER_LOGIN=$(gh api user --jq '.login // empty' 2>/dev/null || echo "")
    _gh_name=$(gh api user --jq '.name // empty' 2>/dev/null || echo "")
    _gh_email=$(gh api user --jq '.email // empty' 2>/dev/null || echo "")
    [ -n "$_gh_name" ] && CPM_USER_NAME="$_gh_name"
    [ -n "$_gh_email" ] && CPM_USER_EMAIL="$_gh_email"
  fi

  # Fallback: git config (check repo-level first via any detected project, then global)
  _first_repo=""
  for dir in "$WORKSPACE"/*/; do
    if [ -d "$dir/.git" ]; then
      _first_repo="$dir"
      break
    fi
  done

  if [ -z "${CPM_USER_NAME:-}" ] && [ -n "$_first_repo" ]; then
    CPM_USER_NAME=$(cd "$_first_repo" && git config user.name 2>/dev/null || echo "")
  fi
  if [ -z "${CPM_USER_NAME:-}" ]; then
    CPM_USER_NAME=$(git config --global user.name 2>/dev/null || echo "")
  fi

  if [ -z "${CPM_USER_EMAIL:-}" ] && [ -n "$_first_repo" ]; then
    CPM_USER_EMAIL=$(cd "$_first_repo" && git config user.email 2>/dev/null || echo "")
  fi
  if [ -z "${CPM_USER_EMAIL:-}" ]; then
    CPM_USER_EMAIL=$(git config --global user.email 2>/dev/null || echo "")
  fi

  if [ -z "${CPM_USER_LOGIN:-}" ] && [ -n "${CPM_USER_EMAIL:-}" ]; then
    # Derive login from email (before @) as last resort
    CPM_USER_LOGIN=$(echo "${CPM_USER_EMAIL}" | cut -d'@' -f1 | tr '.' '-')
  fi

  # Git author name (used for filtering commits)
  if [ -n "$_first_repo" ]; then
    CPM_USER_GIT_NAME=$(cd "$_first_repo" && git config user.name 2>/dev/null || echo "")
  fi
  if [ -z "${CPM_USER_GIT_NAME:-}" ]; then
    CPM_USER_GIT_NAME="${CPM_USER_NAME:-}"
  fi

  # ── Cache to file ────────────────────────────────────────────
  if [ -n "${CPM_USER_LOGIN:-}" ] && [ -n "${CPM_USER_NAME:-}" ]; then
    cat > "$CPM_USER_CONF" <<EOF
# CPM user config — auto-generated, edit if needed
CPM_USER_NAME="${CPM_USER_NAME}"
CPM_USER_LOGIN="${CPM_USER_LOGIN}"
CPM_USER_EMAIL="${CPM_USER_EMAIL:-}"
CPM_USER_GIT_NAME="${CPM_USER_GIT_NAME:-${CPM_USER_NAME}}"
EOF
    echo "CPM: detected user → ${CPM_USER_NAME} (@${CPM_USER_LOGIN})" >&2
  fi
fi

# Ensure git name is set for commit filtering
if [ -z "${CPM_USER_GIT_NAME:-}" ]; then
  CPM_USER_GIT_NAME="${CPM_USER_NAME:-}"
fi
