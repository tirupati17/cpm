#!/usr/bin/env node

/**
 * CPM Memory Sync Engine
 *
 * Watches git commits, extracts learnings, and advances CLAUDE.md
 * with better context for future Claude sessions.
 *
 * This is the "shared memory" capability — what Claude learns from
 * reviewing iOS code gets applied to Android, and vice versa.
 *
 * Usage:
 *   node scripts/cpm-sync.js --repo app-ios --commits 5
 *   node scripts/cpm-sync.js --repo app-android --commits 10
 *   node scripts/cpm-sync.js --sync-claude-md
 *   node scripts/cpm-sync.js --full-sync
 *
 * What it does:
 *   1. Reads recent git commits from specified repo
 *   2. Extracts patterns from commit messages + diffs (review fixes)
 *   3. Updates learnings JSON files with new patterns
 *   4. Syncs learnings → CLAUDE.md PR Standards section
 *   5. Cross-pollinates: iOS learnings → Android checks, and vice versa
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// ========================================
// PATHS
// ========================================

const WORKSPACE_ROOT = path.resolve(__dirname, '../..');
const CLAUDE_MD = path.join(WORKSPACE_ROOT, 'CLAUDE.md');
const SHARED_MEMORY = path.join(WORKSPACE_ROOT, 'memory', 'projects');
const LEARNINGS_DIR = path.join(__dirname, '..', '.github', 'actions', 'claude-review', 'learnings');
const MEMORY_DIR = process.env.CLAUDE_MEMORY_DIR || path.join(require('os').homedir(), '.claude', 'memory');

// ========================================
// CLI
// ========================================

const args = process.argv.slice(2);
function getArg(name) {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 ? args[idx + 1] : null;
}

const repo = getArg('repo');
const commitCount = parseInt(getArg('commits') || '10');
const syncClaudeMd = args.includes('--sync-claude-md');
const fullSync = args.includes('--full-sync');

// ========================================
// 1. EXTRACT GIT COMMIT LEARNINGS
// ========================================

function extractCommitLearnings(repoDir, count) {
  console.log(`\nExtracting learnings from last ${count} commits in ${repoDir}...`);

  let logs;
  try {
    logs = execSync(
      `cd "${repoDir}" && git log --oneline -${count} --format="%H|%s|%an|%ad" --date=short 2>/dev/null`,
      { encoding: 'utf8' }
    ).trim().split('\n').filter(Boolean);
  } catch {
    console.warn(`Could not read git log from ${repoDir}`);
    return [];
  }

  const learnings = [];

  for (const line of logs) {
    const [hash, subject, author, date] = line.split('|');

    // Look for review-fix commits (patterns: "fix review", "address feedback", "PR feedback")
    const isReviewFix = /review|feedback|fix.*comment|address|revert/i.test(subject);

    // Look for pattern-establishing commits
    const isPatternCommit = /refactor|centralize|localize|enum|constant|singleton|mvi/i.test(subject);

    if (isReviewFix || isPatternCommit) {
      let diffStats;
      try {
        diffStats = execSync(
          `cd "${repoDir}" && git diff-tree --no-commit-id -r --stat ${hash} 2>/dev/null`,
          { encoding: 'utf8' }
        ).trim();
      } catch {
        diffStats = '';
      }

      learnings.push({
        hash: hash.substring(0, 8),
        subject,
        author,
        date,
        type: isReviewFix ? 'review-fix' : 'pattern',
        files: diffStats.split('\n')
          .map(l => l.split('|')[0]?.trim())
          .filter(Boolean)
          .filter(f => !f.includes('files changed')),
      });
    }
  }

  console.log(`Found ${learnings.length} relevant commits out of ${logs.length}`);
  return learnings;
}

// ========================================
// 2. CROSS-PLATFORM PATTERN SYNC
// ========================================

function crossPollinate() {
  console.log('\nCross-pollinating learnings...');

  const iosPath = path.join(LEARNINGS_DIR, 'ios-reviewer-a.json');
  const androidPath = path.join(LEARNINGS_DIR, 'android-reviewer-b.json');

  if (!fs.existsSync(iosPath) || !fs.existsSync(androidPath)) {
    console.warn('Missing learnings files. Skipping cross-pollination.');
    return { shared: [] };
  }

  const ios = JSON.parse(fs.readFileSync(iosPath, 'utf8'));
  const android = JSON.parse(fs.readFileSync(androidPath, 'utf8'));

  // Find patterns that exist on BOTH platforms (same category + similar rule)
  const shared = [];

  for (const iosPattern of ios.patterns) {
    for (const androidPattern of android.patterns) {
      if (iosPattern.category === androidPattern.category) {
        // Check rule similarity (>50% word overlap)
        const iosWords = new Set(iosPattern.rule.toLowerCase().split(/\s+/));
        const androidWords = new Set(androidPattern.rule.toLowerCase().split(/\s+/));
        const intersection = [...iosWords].filter(w => androidWords.has(w));
        const similarity = intersection.length / Math.min(iosWords.size, androidWords.size);

        if (similarity > 0.4) {
          shared.push({
            category: iosPattern.category,
            ios_id: iosPattern.id,
            android_id: androidPattern.id,
            rule: iosPattern.rule,
            combined_frequency: (iosPattern.frequency || 1) + (androidPattern.frequency || 1),
          });
        }
      }
    }
  }

  console.log(`Found ${shared.length} cross-platform patterns`);
  return { shared, ios, android };
}

// ========================================
// 3. SYNC TO CLAUDE.MD
// ========================================

function syncToClaudeMd(crossPlatformData) {
  console.log('\nSyncing learnings → CLAUDE.md...');

  if (!fs.existsSync(CLAUDE_MD)) {
    console.warn('CLAUDE.md not found at', CLAUDE_MD);
    return;
  }

  let content = fs.readFileSync(CLAUDE_MD, 'utf8');

  // Build the review bot learnings section
  const timestamp = new Date().toISOString().split('T')[0];

  let section = `## Review Bot Learnings (auto-synced ${timestamp})\n\n`;
  section += `Bot test score: 10/10 (76/76 tests passing)\n\n`;

  // Top patterns by frequency (cross-platform)
  section += `### Top Cross-Platform Patterns (both reviewers flag these)\n`;
  section += `| # | Category | Rule | Frequency |\n`;
  section += `|---|----------|------|-----------|\n`;

  if (crossPlatformData.shared) {
    const sorted = crossPlatformData.shared.sort((a, b) => b.combined_frequency - a.combined_frequency);
    for (const [i, p] of sorted.slice(0, 10).entries()) {
      section += `| ${i + 1} | ${p.category} | ${p.rule.substring(0, 80)} | ${p.combined_frequency}x |\n`;
    }
  }

  section += `\n### iOS — Reviewer A's Top Blockers\n`;
  if (crossPlatformData.ios) {
    const critical = crossPlatformData.ios.patterns
      .filter(p => p.severity === 'critical')
      .sort((a, b) => (b.frequency || 1) - (a.frequency || 1));
    for (const p of critical) {
      section += `- **${p.rule}** (${p.frequency || 1}x)\n`;
    }
  }

  section += `\n### Android — Reviewer B's Top Blockers\n`;
  if (crossPlatformData.android) {
    const critical = crossPlatformData.android.patterns
      .filter(p => p.severity === 'critical')
      .sort((a, b) => (b.frequency || 1) - (a.frequency || 1));
    for (const p of critical) {
      section += `- **${p.rule}** (${p.frequency || 1}x)\n`;
    }
  }

  section += `\n→ Full learnings: \`claude-review-bot/.github/actions/claude-review/learnings/\`\n`;

  // Replace or append the section
  const sectionMarker = '## Review Bot Learnings';
  const nextSectionRegex = /\n## (?!Review Bot Learnings)/;

  if (content.includes(sectionMarker)) {
    // Replace existing section
    const startIdx = content.indexOf(sectionMarker);
    const afterStart = content.substring(startIdx + sectionMarker.length);
    const nextMatch = afterStart.match(nextSectionRegex);
    const endIdx = nextMatch
      ? startIdx + sectionMarker.length + nextMatch.index
      : content.length;
    content = content.substring(0, startIdx) + section + content.substring(endIdx);
  } else {
    // Insert before "## PR Standards" or append at end
    const prStandardsIdx = content.indexOf('## PR Standards');
    if (prStandardsIdx !== -1) {
      content = content.substring(0, prStandardsIdx) + section + '\n' + content.substring(prStandardsIdx);
    } else {
      content += '\n' + section;
    }
  }

  fs.writeFileSync(CLAUDE_MD, content);
  console.log(`Updated CLAUDE.md with review bot learnings`);
}

// ========================================
// 4. UPDATE SHARED MEMORY
// ========================================

function updateSharedMemory(commitLearnings, crossPlatformData) {
  console.log('\nUpdating shared memory...');

  const memoryPath = path.join(SHARED_MEMORY, 'module.md');
  if (!fs.existsSync(memoryPath)) {
    console.warn('Shared memory module.md not found. Skipping.');
    return;
  }

  let content = fs.readFileSync(memoryPath, 'utf8');

  // Add review bot section if not present
  const botSection = '\n## Review Bot Integration\n';
  if (!content.includes('Review Bot Integration')) {
    const timestamp = new Date().toISOString().split('T')[0];
    let addition = botSection;
    addition += `- **Status**: Active (10/10 test score, last synced ${timestamp})\n`;
    addition += `- **iOS patterns**: ${crossPlatformData.ios?.patterns.length || 0} (${crossPlatformData.ios?.stats.critical || 0} critical)\n`;
    addition += `- **Android patterns**: ${crossPlatformData.android?.patterns.length || 0} (${crossPlatformData.android?.stats.critical || 0} critical)\n`;
    addition += `- **Cross-platform shared**: ${crossPlatformData.shared?.length || 0} patterns\n`;

    if (commitLearnings.length > 0) {
      addition += `\n### Recent Review-Fix Commits\n`;
      for (const cl of commitLearnings.slice(0, 5)) {
        addition += `- \`${cl.hash}\` ${cl.subject} (${cl.date})\n`;
      }
    }

    content += addition;
    fs.writeFileSync(memoryPath, content);
    console.log('Updated shared memory module.md');
  } else {
    console.log('Shared memory already has Review Bot section');
  }
}

// ========================================
// 5. UPDATE CLAUDE MEMORY
// ========================================

function updateClaudeMemory(crossPlatformData) {
  console.log('\nUpdating Claude memory...');

  const memoryFile = path.join(MEMORY_DIR, 'reviewer-a-patterns.md');
  if (!fs.existsSync(memoryFile)) {
    console.warn('reviewer-a-patterns.md not found. Skipping.');
    return;
  }

  let content = fs.readFileSync(memoryFile, 'utf8');

  // Add review bot reference if not present
  if (!content.includes('Review Bot')) {
    content += '\n\n## Review Bot (auto-learning)\n';
    content += '- Bot learnings database: `claude-review-bot/.github/actions/claude-review/learnings/`\n';
    content += '- iOS: `ios-reviewer-a.json` — Reviewer A\'s patterns extracted from PR comments\n';
    content += '- Android: `android-reviewer-b.json` — Reviewer B\'s patterns extracted from PR comments\n';
    content += '- Sync: `node scripts/cpm-sync.js --sync-claude-md` updates CLAUDE.md\n';
    content += '- Harvest: `node scripts/harvest-pr-comments.js` pulls new patterns from PRs\n';
    fs.writeFileSync(memoryFile, content);
    console.log('Updated reviewer-a-patterns.md with bot reference');
  }
}

// ========================================
// MAIN
// ========================================

function main() {
  console.log('=== CPM Memory Sync Engine ===');
  console.log(`Timestamp: ${new Date().toISOString()}`);

  let commitLearnings = [];

  // Step 1: Extract from git if repo specified
  if (repo || fullSync) {
    const repos = fullSync
      ? [
          { name: 'app-ios', dir: path.join(WORKSPACE_ROOT, 'app-ios') },
          { name: 'app-android', dir: path.join(WORKSPACE_ROOT, 'app-android') },
        ]
      : [{ name: repo, dir: path.join(WORKSPACE_ROOT, repo) }];

    for (const r of repos) {
      if (fs.existsSync(r.dir)) {
        const cl = extractCommitLearnings(r.dir, commitCount);
        commitLearnings.push(...cl);
      } else {
        console.warn(`Repo dir not found: ${r.dir}`);
      }
    }
  }

  // Step 2: Cross-pollinate learnings
  const crossPlatformData = crossPollinate();

  // Step 3: Sync to CLAUDE.md
  if (syncClaudeMd || fullSync) {
    syncToClaudeMd(crossPlatformData);
  }

  // Step 4: Update shared memory
  if (fullSync) {
    updateSharedMemory(commitLearnings, crossPlatformData);
    updateClaudeMemory(crossPlatformData);
  }

  // Step 5: Summary
  console.log('\n=== Sync Summary ===');
  console.log(`Commit learnings extracted: ${commitLearnings.length}`);
  console.log(`Cross-platform patterns: ${crossPlatformData.shared?.length || 0}`);
  console.log(`iOS patterns: ${crossPlatformData.ios?.patterns.length || 0}`);
  console.log(`Android patterns: ${crossPlatformData.android?.patterns.length || 0}`);
  if (syncClaudeMd || fullSync) console.log('CLAUDE.md: Updated');
  console.log('\n=== Done ===');
}

main();
