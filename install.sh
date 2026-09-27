#!/usr/bin/env bash
# CPM — One-liner installer for Claude Code's Cross-Project Memory toolkit.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tirupati17/cpm/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/tirupati17/cpm/main/install.sh | bash -s -- ~/Code/my-workspace
#
# What this does:
#   1. Clones (or forks via gh, if authenticated) tirupati17/cpm into a folder
#   2. Creates the memory/ tree so you start clean
#   3. Hands off to setup.sh which prompts for project details + installs hooks
#
# Re-run safe: detects existing CPM dirs and offers to skip the clone step.

set -euo pipefail

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

UPSTREAM_URL="https://github.com/tirupati17/cpm.git"
UPSTREAM_SLUG="tirupati17/cpm"
DEFAULT_DIR_NAME="cpm"

# ----------------------------------------------------------------------------
# Resolve target directory
# ----------------------------------------------------------------------------
TARGET_DIR="${1:-}"
if [ -z "$TARGET_DIR" ]; then
  TARGET_DIR="$(pwd)/$DEFAULT_DIR_NAME"
fi

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  CPM — Cross-Project Memory for Claude Code${NC}"
echo -e "${DIM}  One-liner installer${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "  ${DIM}Target directory:${NC} $TARGET_DIR"
echo ""

# ----------------------------------------------------------------------------
# 1. Clone or fork
# ----------------------------------------------------------------------------
if [ -d "$TARGET_DIR/.git" ] && [ -f "$TARGET_DIR/setup.sh" ]; then
  echo -e "${YELLOW}!${NC} $TARGET_DIR already looks like a CPM checkout — skipping clone."
else
  if [ -e "$TARGET_DIR" ]; then
    echo -e "${RED}✘${NC} $TARGET_DIR already exists but isn't a CPM repo. Move it aside and rerun." >&2
    exit 1
  fi

  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    echo -e "${CYAN}→${NC} Forking ${UPSTREAM_SLUG} via gh CLI…"
    if gh repo fork "$UPSTREAM_SLUG" --clone --remote --fork-name "$DEFAULT_DIR_NAME" -- "$TARGET_DIR" >/dev/null 2>&1; then
      echo -e "  ${GREEN}✓${NC} Forked + cloned into $TARGET_DIR"
    else
      echo -e "  ${YELLOW}!${NC} gh fork failed (existing fork? rate-limited?) — falling back to plain clone."
      git clone "$UPSTREAM_URL" "$TARGET_DIR"
    fi
  else
    echo -e "${CYAN}→${NC} Cloning ${UPSTREAM_SLUG}…"
    echo -e "  ${DIM}(install + authenticate the gh CLI later to convert this into a fork)${NC}"
    git clone "$UPSTREAM_URL" "$TARGET_DIR"
  fi
fi

cd "$TARGET_DIR"

# ----------------------------------------------------------------------------
# 2. memory/ is created on first run by the scripts themselves, so a fresh
#    clone has nothing to strip.

# 3. Hand off to setup.sh
# ----------------------------------------------------------------------------
echo ""
echo -e "${CYAN}→${NC} Launching setup.sh…"
echo ""
chmod +x setup.sh scripts/*.sh 2>/dev/null || true
exec ./setup.sh
