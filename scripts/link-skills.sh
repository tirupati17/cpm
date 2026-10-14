#!/usr/bin/env bash
# Historical command name retained; installs real skill copies, never symlinks.
set -euo pipefail
WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$WORKSPACE/scripts/sync-skills.py" "${1:-}"
