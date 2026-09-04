#!/usr/bin/env bash
# CPM — Install post-commit hooks in all sub-project repos
# Usage: install-hooks.sh

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"

# Auto-detect projects
source "$WORKSPACE/scripts/detect-projects.sh"
PROJECTS=("${CPM_PROJECTS[@]}")

for project in "${PROJECTS[@]}"; do
  repo_dir="$WORKSPACE/$project"
  hook_file="$repo_dir/.git/hooks/post-commit"

  if [ ! -d "$repo_dir/.git" ]; then
    echo "SKIP: $project — not a git repo"
    continue
  fi

  mkdir -p "$repo_dir/.git/hooks"

  # Migration: strip a legacy pre-1.0 hook block if present
  if [ -f "$hook_file" ] && grep -q "cpm-memory-legacy" "$hook_file" 2>/dev/null && ! grep -q "\[cpm\]" "$hook_file" 2>/dev/null; then
    cp "$hook_file" "$hook_file.legacy.bak"
    # Remove the legacy hook entirely (it was a full-file replacement, not appended)
    rm "$hook_file"
    echo "MIGRATED: $project — backed up legacy hook to .legacy.bak"
  fi

  if [ -f "$hook_file" ]; then
    if grep -q "\[cpm\]" "$hook_file" 2>/dev/null; then
      echo "OK: $project — CPM hook already installed"
      continue
    fi
    # Append to existing hook
    cat >> "$hook_file" <<HOOK

# --- [cpm] Cross-Project Memory (auto-tracking) ---
"$WORKSPACE/scripts/log-commit.sh" "$project" "$WORKSPACE" &
(sleep 2 && "$WORKSPACE/scripts/summarize.sh" "$project" && "$WORKSPACE/scripts/generate-truth.sh") &>/dev/null &
# --- End [cpm] ---
HOOK
    echo "UPDATED: $project — appended CPM to existing post-commit hook"
  else
    cat > "$hook_file" <<HOOK
#!/usr/bin/env bash
# Post-commit hook — auto-installed by [cpm]

# --- [cpm] Cross-Project Memory (auto-tracking) ---
"$WORKSPACE/scripts/log-commit.sh" "$project" "$WORKSPACE" &
(sleep 2 && "$WORKSPACE/scripts/summarize.sh" "$project" && "$WORKSPACE/scripts/generate-truth.sh") &>/dev/null &
# --- End [cpm] ---
HOOK
    echo "INSTALLED: $project — new post-commit hook created"
  fi

  chmod +x "$hook_file"
done

echo ""
echo "[cpm] hooks installed. Every commit in sub-projects will auto-generate changelogs."
