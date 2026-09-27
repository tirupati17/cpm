#!/usr/bin/env bash
# CPM — Automated test suite
# Usage: ./scripts/test-cpm.sh

set -euo pipefail

if [ -n "${CPM_TEST_RUNNING:-}" ]; then
  exit 0
fi
export CPM_TEST_RUNNING=1

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0
SKIP=0
TOTAL=0

BOLD='\033[1m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'

pass() {
  PASS=$((PASS + 1))
  TOTAL=$((TOTAL + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
  FAIL=$((FAIL + 1))
  TOTAL=$((TOTAL + 1))
  echo -e "  ${RED}✗${NC} $1"
}

skip() {
  SKIP=$((SKIP + 1))
  TOTAL=$((TOTAL + 1))
  echo -e "  ${YELLOW}⊘${NC} $1 ${DIM}(skipped)${NC}"
}

section() {
  echo ""
  echo -e "${YELLOW}=== $1 ===${NC}"
}

# ──────────────────────────────────────────────────────────────
section "1. Directory Structure"
# ──────────────────────────────────────────────────────────────

[ -d "$WORKSPACE/scripts" ] && pass "scripts/ exists" || fail "scripts/ missing"
[ -d "$WORKSPACE/memory" ] && pass "memory/ exists" || fail "memory/ missing"
[ -d "$WORKSPACE/memory/changelogs" ] && pass "memory/changelogs/ exists" || fail "memory/changelogs/ missing"
[ -d "$WORKSPACE/memory/summaries" ] && pass "memory/summaries/ exists" || fail "memory/summaries/ missing"
[ -f "$WORKSPACE/.gitignore" ] && pass ".gitignore exists" || fail ".gitignore missing"

# ──────────────────────────────────────────────────────────────
section "2. Scripts Exist & Executable"
# ──────────────────────────────────────────────────────────────

for script in detect-projects.sh detect-user.sh setup-memory-system.sh log-commit.sh summarize.sh generate-truth.sh install-hooks.sh backfill.sh generate-report.sh postreport.sh add-reviewer.sh cpm-check.sh test-cpm.sh; do
  if [ -x "$WORKSPACE/scripts/$script" ]; then
    pass "$script executable"
  elif [ -f "$WORKSPACE/scripts/$script" ]; then
    fail "$script exists but not executable"
  else
    fail "$script missing"
  fi
done

# ──────────────────────────────────────────────────────────────
section "3. Script Syntax Validation"
# ──────────────────────────────────────────────────────────────

for script in "$WORKSPACE/scripts/"*.sh; do
  fname=$(basename "$script")
  if bash -n "$script" 2>/dev/null; then
    pass "$fname — valid bash syntax"
  else
    fail "$fname — syntax error"
  fi
done

# ──────────────────────────────────────────────────────────────
section "4. Auto-Detection"
# ──────────────────────────────────────────────────────────────

source "$WORKSPACE/scripts/detect-projects.sh"

if [ ${#CPM_PROJECTS[@]} -gt 0 ]; then
  pass "Auto-detected ${#CPM_PROJECTS[@]} project(s): ${CPM_PROJECTS[*]}"
else
  fail "No projects detected"
fi

for project in "${CPM_PROJECTS[@]}"; do
  [ -d "$WORKSPACE/$project/.git" ] && pass "$project is a valid git repo" || fail "$project is not a git repo"
done

for skip_dir in scripts docs claude-review-bot memory others; do
  if echo "${CPM_PROJECTS[*]}" | grep -qw "$skip_dir"; then
    fail "detect-projects should skip $skip_dir but didn't"
  else
    pass "detect-projects correctly skips $skip_dir"
  fi
done

# ──────────────────────────────────────────────────────────────
section "5. User Detection"
# ──────────────────────────────────────────────────────────────

(
  source "$WORKSPACE/scripts/detect-user.sh" 2>/dev/null
  if [ -n "${CPM_USER_NAME:-}" ]; then
    echo "DETECTED_NAME=${CPM_USER_NAME}"
  fi
  if [ -n "${CPM_USER_LOGIN:-}" ]; then
    echo "DETECTED_LOGIN=${CPM_USER_LOGIN}"
  fi
) > /tmp/cpm_user_test.txt 2>/dev/null

if grep -q "DETECTED_NAME=" /tmp/cpm_user_test.txt 2>/dev/null; then
  detected_name=$(grep "DETECTED_NAME=" /tmp/cpm_user_test.txt | cut -d= -f2-)
  pass "detect-user.sh found user: $detected_name"
else
  skip "detect-user.sh — no user detected"
fi

if grep -q "DETECTED_LOGIN=" /tmp/cpm_user_test.txt 2>/dev/null; then
  pass "detect-user.sh found GitHub login"
else
  skip "detect-user.sh — no GitHub login (needs gh CLI)"
fi
rm -f /tmp/cpm_user_test.txt

# ──────────────────────────────────────────────────────────────
section "6. Git Hooks"
# ──────────────────────────────────────────────────────────────

for project in "${CPM_PROJECTS[@]}"; do
  hook_file="$WORKSPACE/$project/.git/hooks/post-commit"
  if [ -f "$hook_file" ] && grep -q "\[cpm\]" "$hook_file" 2>/dev/null; then
    pass "$project — post-commit hook installed"
    grep -q "log-commit.sh" "$hook_file" && pass "$project — hook calls log-commit.sh" || fail "$project — hook missing log-commit.sh"
    grep -q "summarize.sh" "$hook_file" && pass "$project — hook calls summarize.sh" || fail "$project — hook missing summarize.sh"
    grep -q "generate-truth.sh" "$hook_file" && pass "$project — hook calls generate-truth.sh" || fail "$project — hook missing generate-truth.sh"
    [ -x "$hook_file" ] && pass "$project — hook is executable" || fail "$project — hook not executable"
  else
    fail "$project — post-commit hook missing"
  fi
done

# ──────────────────────────────────────────────────────────────
section "7. Changelogs"
# ──────────────────────────────────────────────────────────────

for project in "${CPM_PROJECTS[@]}"; do
  changelog_dir="$WORKSPACE/memory/changelogs/$project"
  if [ -d "$changelog_dir" ]; then
    count=$(find "$changelog_dir" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$count" -gt 0 ]; then
      pass "$project — $count changelogs"
      latest=$(ls -1t "$changelog_dir"/*.md 2>/dev/null | head -1 || true)
      if [ -n "$latest" ]; then
        head -1 "$latest" | grep -q "^# " && pass "$project — changelog has heading" || fail "$project — changelog missing heading"
        grep -q "Project" "$latest" && pass "$project — changelog has Project field" || fail "$project — missing Project"
        grep -q "Hash" "$latest" && pass "$project — changelog has Hash field" || fail "$project — missing Hash"
        grep -q "Files Changed" "$latest" && pass "$project — has Files Changed" || fail "$project — missing Files Changed"
      fi
    else
      fail "$project — changelog dir exists but empty"
    fi
  else
    fail "$project — changelog dir missing"
  fi
done

# ──────────────────────────────────────────────────────────────
section "8. Summaries"
# ──────────────────────────────────────────────────────────────

for project in "${CPM_PROJECTS[@]}"; do
  summary="$WORKSPACE/memory/summaries/$project.md"
  if [ -f "$summary" ] && [ -s "$summary" ]; then
    pass "$project — summary generated"
    grep -q "branch" "$summary" -i && pass "$project — summary has branch info" || fail "$project — missing branch"
    grep -q "Recent Changes" "$summary" && pass "$project — has Recent Changes" || fail "$project — missing Recent Changes"
    grep -q "Feature Areas" "$summary" && pass "$project — has Feature Areas" || fail "$project — missing Feature Areas"
  else
    fail "$project — summary missing"
  fi
done

# ──────────────────────────────────────────────────────────────
section "9. TRUTH.md"
# ──────────────────────────────────────────────────────────────

if [ -f "$WORKSPACE/TRUTH.md" ] && [ -s "$WORKSPACE/TRUTH.md" ]; then
  pass "TRUTH.md exists and non-empty"
  grep -q "Platform Status" "$WORKSPACE/TRUTH.md" && pass "TRUTH.md has Platform Status" || fail "TRUTH.md missing Platform Status"
  grep -q "Cross-Platform Alerts" "$WORKSPACE/TRUTH.md" && pass "TRUTH.md has Cross-Platform Alerts" || fail "missing Cross-Platform Alerts"
  grep -q "Recent Activity" "$WORKSPACE/TRUTH.md" && pass "TRUTH.md has Recent Activity" || fail "missing Recent Activity"
  grep -q "Per-Platform" "$WORKSPACE/TRUTH.md" && pass "TRUTH.md has Per-Platform Summaries" || fail "missing Per-Platform"
  for project in "${CPM_PROJECTS[@]}"; do
    grep -q "$project" "$WORKSPACE/TRUTH.md" && pass "TRUTH.md includes $project" || fail "TRUTH.md missing $project"
  done
  head -3 "$WORKSPACE/TRUTH.md" | grep -qi "auto-generated" && pass "TRUTH.md has auto-generated header" || fail "missing auto-generated header"
else
  fail "TRUTH.md missing"
fi

# ──────────────────────────────────────────────────────────────
section "10. Agent instructions (AGENTS.md or CLAUDE.md)"
# ──────────────────────────────────────────────────────────────

_instr=""
for _f in AGENTS.md CLAUDE.md; do
  if [ -s "$WORKSPACE/$_f" ] && [ "$(head -c 11 "$WORKSPACE/$_f")" != "@AGENTS.md" ]; then _instr="$_f"; break; fi
done
if [ -n "$_instr" ]; then
  pass "$_instr exists"
  grep -qi "cpm\|cross-project memory" "$WORKSPACE/$_instr" && pass "$_instr mentions CPM" || fail "$_instr missing CPM section"
else
  fail "AGENTS.md missing (run ./setup.sh)"
fi

# ──────────────────────────────────────────────────────────────
section "11. Review Bot"
# ──────────────────────────────────────────────────────────────

learnings_dir="$WORKSPACE/claude-review-bot/.github/actions/claude-review/learnings"
if [ -d "$learnings_dir" ]; then
  pass "Review bot learnings directory exists"
  learnings_count=$(find "$learnings_dir" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  if [ "$learnings_count" -gt 0 ]; then
    pass "$learnings_count reviewer learnings file(s)"
    for f in "$learnings_dir"/*.json; do
      [ -f "$f" ] || continue
      fname=$(basename "$f" .json)
      patterns=$(grep -c '"id"' "$f" 2>/dev/null || echo "0")
      pass "  $fname: $patterns patterns"
      if python3 -c "import json; json.load(open('$f'))" 2>/dev/null; then
        pass "  $fname: valid JSON"
      else
        fail "  $fname: invalid JSON"
      fi
    done
  else
    skip "No learnings files yet — add via add-reviewer.sh"
  fi
else
  skip "Review bot learnings dir missing"
fi

if [ -f "$WORKSPACE/claude-review-bot/.github/actions/claude-review/action.yml" ]; then
  pass "Review bot action.yml exists"
else
  skip "Review bot action.yml missing"
fi

# ──────────────────────────────────────────────────────────────
section "12. Cross-Platform Consistency"
# ──────────────────────────────────────────────────────────────

if [ ${#CPM_PROJECTS[@]} -ge 2 ]; then
  pass "Multi-project workspace (${#CPM_PROJECTS[@]} repos) — cross-platform sync enabled"
fi

if [ -f "$WORKSPACE/.gitignore" ]; then
  ignored=0
  for project in "${CPM_PROJECTS[@]}"; do
    # Accept both anchored "/project/" and bare "project/" forms
    if grep -qE "^/?${project}/" "$WORKSPACE/.gitignore" 2>/dev/null; then
      ignored=$((ignored + 1))
    fi
  done
  if [ "$ignored" -eq "${#CPM_PROJECTS[@]}" ]; then
    pass ".gitignore excludes all sub-repos"
  else
    fail ".gitignore missing some sub-repo exclusions ($ignored/${#CPM_PROJECTS[@]})"
  fi
fi

grep -q ".cpm-user.conf" "$WORKSPACE/.gitignore" 2>/dev/null && pass ".cpm-user.conf is gitignored" || fail ".cpm-user.conf NOT gitignored"
grep -q ".cpm-initialized" "$WORKSPACE/.gitignore" 2>/dev/null && pass ".cpm-initialized is gitignored" || fail ".cpm-initialized NOT gitignored"

# ──────────────────────────────────────────────────────────────
section "13. Status Report Generation"
# ──────────────────────────────────────────────────────────────

report_output=$("$WORKSPACE/scripts/generate-report.sh" --hours 168 --output terminal 2>&1 || echo "FAILED")
if echo "$report_output" | grep -qi "STATUS REPORT"; then
  pass "generate-report.sh produces valid report"
else
  fail "generate-report.sh failed"
fi

for project in "${CPM_PROJECTS[@]}"; do
  if echo "$report_output" | grep -q "$project"; then
    pass "Report includes $project"
  else
    fail "Report missing $project"
  fi
done

echo "$report_output" | grep -qi "INFRASTRUCTURE" && pass "Report shows infrastructure stats" || fail "missing infrastructure stats"

"$WORKSPACE/scripts/generate-report.sh" --hours 168 --output markdown >/dev/null 2>&1
report_file="$WORKSPACE/memory/reports/report_$(date '+%Y-%m-%d').md"
[ -f "$report_file" ] && [ -s "$report_file" ] && pass "Markdown report saved" || fail "Markdown report not saved"

# ──────────────────────────────────────────────────────────────
section "14. CPM-Check"
# ──────────────────────────────────────────────────────────────

check_output=$("$WORKSPACE/scripts/cpm-check.sh" 2>&1 || true)
[ -n "$check_output" ] && pass "cpm-check.sh produces output" || fail "cpm-check.sh produced no output"
echo "$check_output" | grep -qE "repos|CPM" && pass "cpm-check.sh output looks right" || fail "cpm-check.sh output unexpected"

# ──────────────────────────────────────────────────────────────
section "15. Add-Reviewer Validation"
# ──────────────────────────────────────────────────────────────

help_output=$("$WORKSPACE/scripts/add-reviewer.sh" --help 2>&1 || true)
echo "$help_output" | grep -q "Usage" && pass "add-reviewer.sh --help works" || fail "add-reviewer.sh --help broken"

_rv_output=$("$WORKSPACE/scripts/add-reviewer.sh" 2>&1 || true)
echo "$_rv_output" | grep -q "ERROR" && pass "add-reviewer.sh rejects missing args" || fail "missing-args validation broken"

_rv_output2=$("$WORKSPACE/scripts/add-reviewer.sh" --name x --github x --platform mars 2>&1 || true)
echo "$_rv_output2" | grep -q "ERROR" && pass "add-reviewer.sh rejects invalid platform" || fail "platform validation broken"

# ──────────────────────────────────────────────────────────────
echo ""
echo -e "════════════════════════════════════════════"
if [ "$SKIP" -gt 0 ]; then
  echo -e "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}, ${YELLOW}${SKIP} skipped${NC}, ${TOTAL} total"
else
  echo -e "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}, ${TOTAL} total"
fi
echo -e "════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "Fix failing tests, then run again: ./scripts/test-cpm.sh"
  exit 1
else
  echo ""
  echo "All tests passing. CPM is fully operational."
  exit 0
fi
