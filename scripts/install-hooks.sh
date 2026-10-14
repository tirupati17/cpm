#!/usr/bin/env bash
# Refresh CPM-owned hook blocks without replacing unrelated hooks.
set -euo pipefail
WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
source "$WORKSPACE/scripts/detect-projects.sh"
for project in "${CPM_PROJECTS[@]}"; do
  hook_dir="$(cpm_git_dir "$project")/hooks"
  mkdir -p "$hook_dir"
  python3 - "$hook_dir" "$project" <<'HOOKPY'
import re, sys
from pathlib import Path
hooks, project = Path(sys.argv[1]), sys.argv[2]
context = r'''
cpm_repo="$(git rev-parse --show-toplevel)"
cpm_workspace="$(dirname "$cpm_repo")"
while [ ! -f "$cpm_workspace/scripts/detect-projects.sh" ]; do
  if [ "$cpm_workspace" = / ]; then exit 0; fi
  cpm_workspace="$(dirname "$cpm_workspace")"
done
'''
post = r'''
# --- [cpm] Cross-Project Memory (portable v2) ---
''' + context + r'''
(cd "$cpm_repo" && "$cpm_workspace/scripts/log-commit.sh" "PROJECT" "$cpm_workspace")
("$cpm_workspace/scripts/summarize.sh" "PROJECT" && "$cpm_workspace/scripts/generate-truth.sh") >/dev/null 2>&1 &
# --- End [cpm] ---
'''
pre = r'''
# --- [cpm] emotions (portable v2) ---
''' + context + r'''
cpm_remote="$1"
cpm_log="$(git rev-parse --absolute-git-dir)/cpm-emotions.log"
while read -r local_ref local_sha remote_ref remote_sha; do
  case "$remote_ref" in refs/heads/*) ;; *) continue ;; esac
  case "$local_sha" in 0000000*) continue ;; esac
  case "$remote_sha" in 0000000*) cpm_range="--since=12.hours" ;; *) cpm_range="$remote_sha..$local_sha" ;; esac
  cpm_tracking="refs/remotes/$cpm_remote/${remote_ref#refs/heads/}"
  (
    for _ in $(seq 1 60); do
      if [ "$(git -C "$cpm_repo" rev-parse -q --verify "$cpm_tracking" 2>/dev/null)" = "$local_sha" ]; then
        cd "$cpm_repo" && exec "$cpm_workspace/toolkit/bin/cpm" emotions read "$cpm_repo" --range "$cpm_range" --record --log
      fi
      sleep 3
    done
  ) </dev/null >>"$cpm_log" 2>&1 &
done
# --- End [cpm] emotions ---
'''
for name, block in [('post-commit', post), ('pre-push', pre)]:
    path = hooks / name
    original = path.read_text() if path.exists() else '#!/usr/bin/env bash\n'
    clean = re.sub(r'\n?# --- \[cpm\][^\n]*\n.*?# --- End \[cpm\][^\n]*\n?', '\n', original, flags=re.S)
    updated = clean.rstrip() + '\n' + block.replace('PROJECT', project)
    if original != updated:
        backup = path.with_name(name + '.cpm-before-portable.bak')
        if path.exists() and not backup.exists(): backup.write_text(original)
        path.write_text(updated)
    path.chmod(path.stat().st_mode | 0o111)
HOOKPY
  echo "OK: $project — portable CPM hooks"
done
