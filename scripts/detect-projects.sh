#!/usr/bin/env bash
# Discover real repositories using .cpm-repos, or flat/grouped folders without it.
# CPM_PROJECTS keeps stable memory IDs; cpm_repo_dir resolves their real locations.
_CPM_INDEX_OFFSET=0
if [ -n "${ZSH_VERSION:-}" ]; then
  _CPM_INDEX_OFFSET=1
  _DETECT_SCRIPT="${(%):-%x}"
else
  _DETECT_SCRIPT="${BASH_SOURCE[0]:-$0}"
fi
if [ -z "${WORKSPACE:-}" ]; then
  WORKSPACE="$(cd "$(dirname "$_DETECT_SCRIPT")/.." && pwd)"
fi
CPM_PROJECTS=()
CPM_REPO_IDS=()
CPM_REPO_PATHS=()

cpm_register_repo() {
  local name="$1" rel="$2" i j probe
  case "$name" in ''|.|..|*[!a-zA-Z0-9._-]*) echo "CPM: Invalid project ID: $name" >&2; return 1 ;; esac
  case "/$rel/" in /*/../*|/*/./*|//*|*/.git/*) echo "CPM: Unsafe repo path: $rel" >&2; return 1 ;; esac
  case "$rel" in ''|/*) echo "CPM: Repo paths must be workspace-relative" >&2; return 1 ;; esac
  for ((i=0; i<${#CPM_REPO_IDS[@]}; i++)); do
    j=$((i + _CPM_INDEX_OFFSET))
    if [ "${CPM_REPO_IDS[$j]}" = "$name" ] || [ "${CPM_REPO_PATHS[$j]}" = "$rel" ]; then
      echo "CPM: Duplicate project ID or path: $name ($rel)" >&2; return 1
    fi
  done
  probe="$WORKSPACE/$rel"
  while [ "$probe" != "$WORKSPACE" ]; do
    [ ! -L "$probe" ] || { echo "CPM: Repo folders must not be links: $rel" >&2; return 1; }
    probe="$(dirname "$probe")"
  done
  CPM_REPO_IDS+=("$name")
  CPM_REPO_PATHS+=("$rel")
  if [ -e "$WORKSPACE/$rel/.git" ] && [ ! -L "$WORKSPACE/$rel" ]; then
    CPM_PROJECTS+=("$name")
  fi
}

cpm_repo_dir() {
  local name="$1" i j
  for ((i=0; i<${#CPM_REPO_IDS[@]}; i++)); do
    j=$((i + _CPM_INDEX_OFFSET))
    if [ "${CPM_REPO_IDS[$j]}" = "$name" ]; then
      printf '%s/%s\n' "$WORKSPACE" "${CPM_REPO_PATHS[$j]}"; return 0
    fi
  done
  echo "CPM: Unknown project: $name" >&2; return 1
}

cpm_git_dir() {
  git -C "$(cpm_repo_dir "$1")" rev-parse --absolute-git-dir
}

cpm_project_name() {
  local repo="$1" name
  for name in "${CPM_PROJECTS[@]}"; do
    if [ "$(cpm_repo_dir "$name")" = "$repo" ]; then printf '%s\n' "$name"; return 0; fi
  done
  return 1
}

if [ -f "$WORKSPACE/.cpm-repos" ]; then
  while IFS=$'\t' read -r name rel url branch extra || [ -n "${name:-}" ]; do
    case "${name:-}" in ''|\#*) continue ;; esac
    [ -z "${extra:-}" ] || { echo "CPM: Invalid .cpm-repos row: $name" >&2; return 1; }
    cpm_register_repo "$name" "$rel" || return 1
  done < "$WORKSPACE/.cpm-repos"
else
  for dir in "$WORKSPACE"/*/ "$WORKSPACE"/repos/*/; do
    [ -e "$dir/.git" ] && [ ! -L "${dir%/}" ] || continue
    name="$(basename "$dir" | tr ' ' '-')"
    case "$name" in scripts|docs|claude-review-bot|memory|goldy-main|others|archive|private|assets) continue ;; esac
    rel="${dir#"$WORKSPACE"/}"; rel="${rel%/}"
    cpm_register_repo "$name" "$rel" || return 1
  done
fi
