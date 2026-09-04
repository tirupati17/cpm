#!/usr/bin/env node

/**
 * PR Comment Harvester
 *
 * Pulls review comments from GitHub PRs and uses Claude to extract
 * new review patterns, then merges them into the learnings database.
 *
 * Usage:
 *   node scripts/harvest-pr-comments.js --repo your-org/app-android --pr XXXX --reviewer ReviewerB
 *   node scripts/harvest-pr-comments.js --repo your-org/app-ios --pr XXXX --reviewer ReviewerA
 *   node scripts/harvest-pr-comments.js --repo your-org/app-android --pr XXXX --reviewer ReviewerB --dry-run
 *
 * Environment:
 *   GITHUB_TOKEN — GitHub PAT with repo read access
 *   ANTHROPIC_API_KEY — for Claude analysis of comments
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// ========================================
// CLI ARGS
// ========================================

const args = process.argv.slice(2);
function getArg(name) {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 ? args[idx + 1] : null;
}

const repo = getArg('repo');
const prNumber = getArg('pr');
const reviewerFilter = getArg('reviewer');
const dryRun = args.includes('--dry-run');
const platform = getArg('platform') || (repo && repo.includes('ios') ? 'ios' : 'android');

if (!repo || !prNumber) {
  console.error('Usage: node harvest-pr-comments.js --repo OWNER/REPO --pr NUMBER [--reviewer USERNAME] [--platform ios|android] [--dry-run]');
  process.exit(1);
}

// ========================================
// FETCH PR COMMENTS VIA GH CLI
// ========================================

function fetchComments() {
  console.log(`\nFetching comments from ${repo}#${prNumber}...`);

  let comments = [];

  // Inline review comments (code-level)
  try {
    const raw = execSync(
      `gh api repos/${repo}/pulls/${prNumber}/comments --paginate`,
      { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 }
    );
    const data = JSON.parse(raw);
    for (const c of data) {
      if (reviewerFilter && c.user.login !== reviewerFilter) continue;
      comments.push({
        type: 'inline',
        author: c.user.login,
        file: c.path,
        line: c.line || c.original_line,
        body: c.body,
        diff_hunk: c.diff_hunk,
        created_at: c.created_at,
      });
    }
  } catch (e) {
    console.warn('Failed to fetch inline comments:', e.message);
  }

  // Review summaries
  try {
    const raw = execSync(
      `gh api repos/${repo}/pulls/${prNumber}/reviews --paginate`,
      { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 }
    );
    const data = JSON.parse(raw);
    for (const r of data) {
      if (reviewerFilter && r.user.login !== reviewerFilter) continue;
      if (r.body && r.body.trim()) {
        comments.push({
          type: 'review_summary',
          author: r.user.login,
          body: r.body,
          state: r.state,
          created_at: r.submitted_at,
        });
      }
    }
  } catch (e) {
    console.warn('Failed to fetch review summaries:', e.message);
  }

  console.log(`Found ${comments.length} comments${reviewerFilter ? ` from ${reviewerFilter}` : ''}`);
  return comments;
}

// ========================================
// ANALYZE WITH CLAUDE
// ========================================

async function analyzeComments(comments) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.error('ANTHROPIC_API_KEY not set. Outputting raw comments only.');
    return null;
  }

  const { Anthropic } = require('@anthropic-ai/sdk');
  const client = new Anthropic({ apiKey });

  const commentsText = comments.map((c, i) => {
    let entry = `[${i + 1}] ${c.type}`;
    if (c.file) entry += ` | ${c.file}:${c.line}`;
    entry += ` | ${c.author}`;
    entry += `\n${c.body}`;
    if (c.diff_hunk) entry += `\nCode context:\n${c.diff_hunk}`;
    return entry;
  }).join('\n\n---\n\n');

  const message = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 4000,
    system: `You are a code review pattern extractor. Given PR review comments from a specific reviewer, extract reusable patterns that should be enforced in future reviews.

Output a JSON array of patterns. Each pattern must have:
- id: "${platform}-NEW-{number}" (sequential)
- severity: "critical" | "major" | "minor"
- category: one of "architecture", "type-safety", "safety", "performance", "compose-pattern", "shared-code", "constants", "localization", "code-quality", "ux", "assets"
- rule: Clear one-line rule statement
- bad_example: The code pattern that was flagged
- good_example: What the code should look like instead
- source: "PR #${prNumber}, Comment #{number} — {reviewer}: '{exact quote}'"
- files_affected: Array of filenames
- frequency: Number of times this pattern appeared in the comments (group similar comments)

IMPORTANT:
- Group similar comments into ONE pattern with higher frequency
- Focus on patterns that are generalizable (not one-off bugs)
- Include the reviewer's exact words in source
- If a comment just says "Please cleanup imports" — that's minor code-quality
- If a comment says "Please use MVI" — that's critical architecture

Output ONLY the JSON array, no markdown fences or explanation.`,
    messages: [
      {
        role: 'user',
        content: `Extract review patterns from these ${comments.length} comments by ${reviewerFilter || 'reviewer'} on PR #${prNumber} (${platform}):\n\n${commentsText}`,
      },
    ],
  });

  const text = message.content[0].type === 'text' ? message.content[0].text : '';

  try {
    return JSON.parse(text);
  } catch {
    // Try extracting JSON from markdown code block
    const jsonMatch = text.match(/\[[\s\S]*\]/);
    if (jsonMatch) return JSON.parse(jsonMatch[0]);
    console.error('Failed to parse Claude response as JSON');
    console.log(text);
    return null;
  }
}

// ========================================
// MERGE INTO LEARNINGS
// ========================================

function mergeLearnings(newPatterns) {
  const learningsDir = path.join(__dirname, '..', '.github', 'actions', 'claude-review', 'learnings');
  const filename = platform === 'ios' ? 'ios-reviewer-a.json' : 'android-reviewer-b.json';
  const filePath = path.join(learningsDir, filename);

  let existing;
  if (fs.existsSync(filePath)) {
    existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } else {
    existing = {
      reviewer: reviewerFilter || 'unknown',
      platform,
      last_updated: new Date().toISOString().split('T')[0],
      source_prs: [],
      stats: { total_comments: 0, critical: 0, major: 0, minor: 0 },
      patterns: [],
    };
  }

  // Track which PR this harvest is from
  const prRef = `#${prNumber}`;
  if (!existing.source_prs.includes(prRef)) {
    existing.source_prs.push(prRef);
  }

  // Merge patterns — skip duplicates by matching rule text similarity
  let added = 0;
  let updated = 0;

  for (const newPattern of newPatterns) {
    const existingMatch = existing.patterns.find(p => {
      // Match by similar rule or same category + similar files
      const ruleSimilarity = p.rule.toLowerCase().includes(newPattern.rule.toLowerCase().substring(0, 30));
      const sameCategory = p.category === newPattern.category;
      const sameFiles = newPattern.files_affected.some(f =>
        p.files_affected.some(ef => ef === f)
      );
      return ruleSimilarity || (sameCategory && sameFiles);
    });

    if (existingMatch) {
      // Update frequency and add source
      existingMatch.frequency = (existingMatch.frequency || 1) + (newPattern.frequency || 1);
      if (!existingMatch.source.includes(prRef)) {
        existingMatch.source += ` + ${newPattern.source}`;
      }
      // Merge files_affected
      for (const f of newPattern.files_affected) {
        if (!existingMatch.files_affected.includes(f)) {
          existingMatch.files_affected.push(f);
        }
      }
      updated++;
    } else {
      // Renumber ID
      const maxId = existing.patterns
        .map(p => parseInt(p.id.split('-').pop()) || 0)
        .reduce((a, b) => Math.max(a, b), 0);
      newPattern.id = `${platform}-${String(maxId + added + 1).padStart(3, '0')}`;
      existing.patterns.push(newPattern);
      added++;
    }
  }

  // Recalculate stats
  existing.stats.total_comments = existing.patterns.reduce((sum, p) => sum + (p.frequency || 1), 0);
  existing.stats.critical = existing.patterns.filter(p => p.severity === 'critical').length;
  existing.stats.major = existing.patterns.filter(p => p.severity === 'major').length;
  existing.stats.minor = existing.patterns.filter(p => p.severity === 'minor').length;
  existing.last_updated = new Date().toISOString().split('T')[0];

  console.log(`\nMerge result: ${added} new patterns, ${updated} updated patterns`);
  console.log(`Total patterns: ${existing.patterns.length}`);
  console.log(`Stats: ${existing.stats.critical} critical, ${existing.stats.major} major, ${existing.stats.minor} minor`);

  if (dryRun) {
    console.log('\n[DRY RUN] Would write to:', filePath);
    console.log(JSON.stringify(existing, null, 2).substring(0, 500) + '...');
  } else {
    fs.writeFileSync(filePath, JSON.stringify(existing, null, 2));
    console.log(`\nWritten to: ${filePath}`);
  }

  return existing;
}

// ========================================
// MAIN
// ========================================

async function main() {
  console.log('=== PR Comment Harvester ===');
  console.log(`Repo: ${repo} | PR: #${prNumber} | Platform: ${platform} | Reviewer: ${reviewerFilter || 'all'}`);
  if (dryRun) console.log('[DRY RUN MODE]');

  const comments = fetchComments();
  if (comments.length === 0) {
    console.log('No comments found. Nothing to harvest.');
    return;
  }

  // Save raw comments for reference
  const rawDir = path.join(__dirname, '..', '.github', 'actions', 'claude-review', 'learnings', 'raw');
  if (!fs.existsSync(rawDir)) fs.mkdirSync(rawDir, { recursive: true });
  const rawPath = path.join(rawDir, `${repo.replace('/', '-')}-${prNumber}.json`);
  if (!dryRun) {
    fs.writeFileSync(rawPath, JSON.stringify(comments, null, 2));
    console.log(`Raw comments saved to: ${rawPath}`);
  }

  // Analyze with Claude
  const patterns = await analyzeComments(comments);
  if (!patterns) {
    console.log('Could not extract patterns. Raw comments saved for manual review.');
    return;
  }

  console.log(`\nExtracted ${patterns.length} patterns:`);
  for (const p of patterns) {
    console.log(`  [${p.severity}] ${p.rule} (${p.frequency}x)`);
  }

  // Merge into learnings
  mergeLearnings(patterns);

  console.log('\n=== Harvest complete ===');
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
