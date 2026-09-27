#!/bin/bash
# Link every skill in skills/ into .claude/skills/ so the agent can load it on demand.
#
# Links are relative, so moving the workspace breaks nothing. A folder in
# .claude/skills/ that is not our link is left alone (it is somebody's own
# skill), and links whose skill was deleted are removed. Folders starting with
# _ (the template) are never linked.
#
#   scripts/link-skills.sh           link, quietly
#   scripts/link-skills.sh --list    link and print what is available

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$WORKSPACE/skills"
DEST="$WORKSPACE/.claude/skills"
[ -d "$SRC" ] || exit 0
mkdir -p "$DEST"

for link in "$DEST"/*; do
  [ -L "$link" ] || continue
  case "$(readlink "$link")" in
    ../../skills/*) [ -e "$link" ] || rm -f "$link" ;;
  esac
done

linked=0
for dir in "$SRC"/*/; do
  name="$(basename "$dir")"
  case "$name" in _*) continue ;; esac
  [ -f "$dir/SKILL.md" ] || continue
  target="$DEST/$name"
  if [ -L "$target" ] || [ ! -e "$target" ]; then
    ln -sfn "../../skills/$name" "$target"
    linked=$((linked + 1))
  fi
  [ "$1" = "--list" ] && echo "  $name"
done
[ "$1" = "--list" ] && echo "$linked skills linked into .claude/skills/"
exit 0
