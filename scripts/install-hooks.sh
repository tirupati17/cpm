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

# --- pre-push: a mood-journal entry for every push that lands ---
# git has no post-push hook, so pre-push starts a background job that waits
# until the pushed branch's remote-tracking ref reaches the pushed commit (the
# push succeeded), then reads the range and logs it. A failed push logs nothing.
for project in "${PROJECTS[@]}"; do
  repo_dir="$WORKSPACE/$project"
  [ -d "$repo_dir/.git" ] || continue
  hook_file="$repo_dir/.git/hooks/pre-push"
  if [ -f "$hook_file" ] && grep -q "\[cpm\] emotions" "$hook_file" 2>/dev/null; then
    echo "OK: $project — emotions pre-push hook already installed"
    continue
  fi
  [ -f "$hook_file" ] || printf '#!/usr/bin/env bash\n# pre-push hook — auto-installed by [cpm]\n' > "$hook_file"
  cat >> "$hook_file" <<HOOK

# --- [cpm] emotions ---
cpm_remote="\$1"
cpm_repo="\$(git rev-parse --show-toplevel)"
while read -r local_ref local_sha remote_ref remote_sha; do
  case "\$remote_ref" in refs/heads/*) ;; *) continue ;; esac
  case "\$local_sha" in 0000000*) continue ;; esac
  case "\$remote_sha" in 0000000*) cpm_range="--since=12.hours" ;; *) cpm_range="\$remote_sha..\$local_sha" ;; esac
  cpm_tracking="refs/remotes/\$cpm_remote/\${remote_ref#refs/heads/}"
  (
    for _ in \$(seq 1 60); do
      if [ "\$(git -C "\$cpm_repo" rev-parse -q --verify "\$cpm_tracking" 2>/dev/null)" = "\$local_sha" ]; then
        cd "\$cpm_repo" && exec "$WORKSPACE/toolkit/bin/cpm" emotions read "\$cpm_repo" --range "\$cpm_range" --record --log
      fi
      sleep 3
    done
  ) </dev/null >>"\$cpm_repo/.git/cpm-emotions.log" 2>&1 &
done
# --- End [cpm] emotions ---
HOOK
  chmod +x "$hook_file"
  echo "INSTALLED: $project — emotions pre-push hook"
done

echo ""
echo "[cpm] hooks installed. Every commit in sub-projects will auto-generate changelogs."
