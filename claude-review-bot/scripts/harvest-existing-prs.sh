#!/bin/bash
# Harvest learnings from existing M2 PRs
# Run this once to bootstrap the learnings database from Reviewer A & Reviewer B's reviews

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Harvesting existing PR reviews ==="
echo ""

# Check prerequisites
if ! command -v gh &> /dev/null; then
  echo "Error: gh CLI not installed. Install with: brew install gh"
  exit 1
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "Error: ANTHROPIC_API_KEY not set"
  echo "Run: export ANTHROPIC_API_KEY=your-key-here"
  exit 1
fi

# Install dependencies if needed
cd "$SCRIPT_DIR/../.github/actions/claude-review"
if [ ! -d "node_modules" ]; then
  echo "Installing dependencies..."
  npm install
fi
cd "$SCRIPT_DIR"

echo ""
echo "--- Android PR #XXXX (Reviewer B) ---"
node "$SCRIPT_DIR/harvest-pr-comments.js" \
  --repo your-org/app-android \
  --pr XXXX \
  --reviewer ReviewerB \
  --platform android

echo ""
echo "--- iOS PR #XXXX (Reviewer A) ---"
node "$SCRIPT_DIR/harvest-pr-comments.js" \
  --repo your-org/app-ios \
  --pr XXXX \
  --reviewer ReviewerA \
  --platform ios

echo ""
echo "--- iOS PR #XXXX (Reviewer A — M1, already merged) ---"
node "$SCRIPT_DIR/harvest-pr-comments.js" \
  --repo your-org/app-ios \
  --pr XXXX \
  --reviewer ReviewerA \
  --platform ios

echo ""
echo "=== All PRs harvested ==="
echo "Learnings files updated in .github/actions/claude-review/learnings/"
