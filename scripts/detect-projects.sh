#!/usr/bin/env bash
# CPM — Auto-detect git repos inside the workspace
# Usage: source scripts/detect-projects.sh
# Sets CPM_PROJECTS array with names of all git repos found

# Work in both bash and zsh
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  _DETECT_SCRIPT="${BASH_SOURCE[0]}"
elif [ -n "${(%):-%x}" 2>/dev/null ]; then
  _DETECT_SCRIPT="${(%):-%x}"
else
  _DETECT_SCRIPT="$0"
fi

# If WORKSPACE is already set (by caller), use it. Otherwise derive from script location.
if [ -z "${WORKSPACE:-}" ]; then
  WORKSPACE="$(cd "$(dirname "$_DETECT_SCRIPT")/.." && pwd)"
fi

CPM_PROJECTS=()

# Dirs to skip even if they happen to contain .git
_CPM_SKIP="scripts docs claude-review-bot memory .claude"

for dir in "$WORKSPACE"/*/; do
  [ -d "$dir" ] || continue
  dname=$(basename "$dir")
  # Skip non-repo dirs and tooling dirs
  if [ -d "$dir/.git" ]; then
    case " $_CPM_SKIP " in
      *" $dname "*) continue ;;
    esac
    CPM_PROJECTS+=("$dname")
  fi
done

if [ ${#CPM_PROJECTS[@]} -eq 0 ]; then
  echo "CPM: No git repos found in $WORKSPACE"
  echo "  Clone your repos inside this directory first."
fi
