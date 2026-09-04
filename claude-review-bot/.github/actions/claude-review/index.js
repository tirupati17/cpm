const core = require('@actions/core');
const github = require('@actions/github');
const fs = require('fs');
const path = require('path');
const { Anthropic } = require('@anthropic-ai/sdk');

// ========================================
// MAIN EXECUTION
// ========================================

async function main() {
  try {
    const apiKey = core.getInput('anthropic_api_key');
    const githubToken = core.getInput('github_token');
    const prNumber = core.getInput('pr_number');
    let platform = core.getInput('platform') || 'android';

    const octokit = github.getOctokit(githubToken);
    const context = github.context;

    const pr = context.payload.pull_request;
    const owner = context.repo.owner;
    const repo = context.repo.repo;
    const prNum = prNumber || pr.number;

    core.info(`Reviewing PR #${prNum} in ${owner}/${repo}`);

    // Read the diff
    const diffPath = 'pr_diff.txt';
    if (!fs.existsSync(diffPath)) {
      core.warning('No diff file found. Skipping review.');
      return;
    }

    const diff = fs.readFileSync(diffPath, 'utf8');
    if (!diff.trim()) {
      core.info('Empty diff. Skipping review.');
      return;
    }

    // Detect platform
    platform = detectPlatform(diff, platform);
    core.info(`Detected platform: ${platform}`);

    // Load review prompt + learnings
    const prompt = loadPrompt(platform);
    const learnings = loadLearnings(platform);

    // Build the full system prompt with learnings
    const systemPrompt = buildSystemPrompt(prompt, learnings);

    // Call Claude API
    const review = await reviewWithClaude(apiKey, diff, systemPrompt);
    core.info(`Claude Review completed`);

    // Parse review
    const verdict = parseVerdict(review);
    core.info(`Verdict: ${verdict.status} | Score: ${verdict.score}/10`);

    // Extract and post inline comments
    const comments = extractComments(review, diff);
    if (comments.length > 0) {
      await postReviewComments(octokit, owner, repo, prNum, comments);
    }

    // Submit review
    await submitReview(octokit, owner, repo, prNum, verdict, review);

    // Set outputs for downstream actions
    core.setOutput('verdict', verdict.status);
    core.setOutput('score', verdict.score);
    core.setOutput('critical_count', verdict.criticalCount);
    core.setOutput('major_count', verdict.majorCount);

    core.info('Review completed successfully');
  } catch (error) {
    core.setFailed(`Error: ${error.message}`);
    console.error(error);
  }
}

// ========================================
// PLATFORM DETECTION
// ========================================

function detectPlatform(diff, defaultPlatform) {
  const swiftFiles = diff.match(/\.swift\b/g);
  const kotlinFiles = diff.match(/\.kt\b/g);

  if (swiftFiles && swiftFiles.length > 0 && !kotlinFiles) return 'ios';
  if (kotlinFiles && kotlinFiles.length > 0 && !swiftFiles) return 'android';
  return defaultPlatform;
}

// ========================================
// PROMPT & LEARNINGS LOADING
// ========================================

function loadPrompt(platform) {
  const filename = platform === 'ios'
    ? 'ios-review-prompt.md'
    : 'android-review-prompt.md';

  const promptPath = path.join(__dirname, 'prompts', filename);
  if (!fs.existsSync(promptPath)) {
    throw new Error(`Prompt file not found: ${promptPath}`);
  }
  return fs.readFileSync(promptPath, 'utf8');
}

function loadLearnings(platform) {
  const filename = platform === 'ios'
    ? 'ios-reviewer-a.json'
    : 'android-reviewer-b.json';

  const learningsPath = path.join(__dirname, 'learnings', filename);
  if (!fs.existsSync(learningsPath)) {
    core.info(`No learnings file found at ${learningsPath}. Using prompt only.`);
    return null;
  }

  try {
    const raw = fs.readFileSync(learningsPath, 'utf8');
    const data = JSON.parse(raw);
    core.info(`Loaded ${data.patterns.length} learnings from ${data.reviewer} (last updated: ${data.last_updated})`);
    return data;
  } catch (error) {
    core.warning(`Failed to parse learnings: ${error.message}`);
    return null;
  }
}

function buildSystemPrompt(prompt, learnings) {
  let systemPrompt = prompt;

  if (learnings) {
    // Sort patterns by frequency (most flagged first) then severity
    const severityOrder = { critical: 0, major: 1, minor: 2 };
    const sorted = [...learnings.patterns].sort((a, b) => {
      if (b.frequency !== a.frequency) return b.frequency - a.frequency;
      return (severityOrder[a.severity] || 3) - (severityOrder[b.severity] || 3);
    });

    systemPrompt += '\n\n---\n\n';
    systemPrompt += '## REVIEWER LEARNINGS (from real PR comments)\n\n';
    systemPrompt += `Reviewer: ${learnings.reviewer}\n`;
    systemPrompt += `Source PRs: ${learnings.source_prs.join(', ')}\n`;
    systemPrompt += `Total historical comments: ${learnings.stats.total_comments}\n\n`;

    systemPrompt += '### Top Patterns (sorted by frequency — most flagged first)\n\n';

    for (const pattern of sorted) {
      systemPrompt += `**[${pattern.id}] ${pattern.severity.toUpperCase()} (flagged ${pattern.frequency}x) — ${pattern.category}**\n`;
      systemPrompt += `Rule: ${pattern.rule}\n`;
      systemPrompt += `Bad: \`${pattern.bad_example}\`\n`;
      systemPrompt += `Good: \`${pattern.good_example}\`\n`;
      systemPrompt += `Source: ${pattern.source}\n\n`;
    }

    // Add high-level feedback if available (Reviewer B's)
    if (learnings.reviewer_b_high_level_feedback) {
      systemPrompt += '### Reviewer\'s High-Level Expectations\n\n';
      for (const feedback of learnings.reviewer_b_high_level_feedback) {
        systemPrompt += `- ${feedback}\n`;
      }
    }
  }

  return systemPrompt;
}

// ========================================
// CLAUDE API CALL
// ========================================

async function reviewWithClaude(apiKey, diff, systemPrompt) {
  const client = new Anthropic({ apiKey });

  // Truncate diff if too large (increased limit for better context)
  const maxDiffLength = 80000;
  const truncatedDiff = diff.length > maxDiffLength
    ? diff.substring(0, maxDiffLength) +
      `\n\n[... diff truncated, original size: ${diff.length} bytes. Review visible portion only. ...]`
    : diff;

  const message = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 8000,
    system: systemPrompt,
    messages: [
      {
        role: 'user',
        content: `Review this pull request diff. Apply every rule from the learnings database. Be thorough — check EVERY file in the diff against EVERY pattern. Flag ALL violations, even small ones. This is a production codebase where quality matters.\n\n${truncatedDiff}`,
      },
    ],
  });

  return message.content[0].type === 'text' ? message.content[0].text : '';
}

// ========================================
// RESPONSE PARSING
// ========================================

function parseVerdict(review) {
  const approveMatch = review.match(/VERDICT:\s*APPROVE/i);
  const changesMatch = review.match(/VERDICT:\s*CHANGES_REQUESTED/i);

  let status = 'COMMENT';
  let conclusion = 'neutral';

  if (approveMatch) {
    status = 'APPROVE';
    conclusion = 'success';
  } else if (changesMatch) {
    status = 'CHANGES_REQUESTED';
    conclusion = 'failure';
  }

  // Extract score
  const scoreMatch = review.match(/SCORE:\s*(\d+)\s*\/\s*10/i);
  const score = scoreMatch ? parseInt(scoreMatch[1]) : 0;

  // Count issues by severity
  const criticalSection = review.match(/CRITICAL:\s*([\s\S]*?)(?:MAJOR:|MINOR:|SCORE:|POSITIVES:|$)/i);
  const majorSection = review.match(/MAJOR:\s*([\s\S]*?)(?:MINOR:|SCORE:|POSITIVES:|$)/i);

  const criticalCount = criticalSection
    ? (criticalSection[1].match(/^-\s/gm) || []).length
    : 0;
  const majorCount = majorSection
    ? (majorSection[1].match(/^-\s/gm) || []).length
    : 0;

  const summaryMatch = review.match(/SUMMARY:\s*([^\n]+)/i);
  const summary = summaryMatch ? summaryMatch[1].trim() : 'Code review completed';

  return { status, conclusion, summary, score, criticalCount, majorCount, body: review };
}

function extractComments(review, diff) {
  const comments = [];

  // Parse all severity sections for inline comments
  const sections = ['CRITICAL', 'MAJOR', 'MINOR'];
  for (const section of sections) {
    const sectionRegex = new RegExp(
      `${section}:\\s*([\\s\\S]*?)(?:${sections.filter(s => s !== section).join(':|')}:|SCORE:|POSITIVES:|NEXT_STEPS:|$)`,
      'i'
    );
    const sectionMatch = review.match(sectionRegex);
    if (!sectionMatch) continue;

    const lines = sectionMatch[1].split('\n').filter(line => line.match(/^-\s*\[/));

    for (const line of lines) {
      // Match patterns like: - [File.kt:Line 42]: Issue. Fix: Suggestion.
      // or: - [File.kt/Line 42]: Issue. Fix: Suggestion.
      const match = line.match(
        /^-\s*\[(.*?)(?::|\/)(?:Line\s*)?(\d+)\]:\s*(.*?)(?:\s+Fix:\s+(.*))?$/i
      );
      if (match) {
        const [, file, lineNum, issue, fix] = match;
        const severity = section === 'CRITICAL' ? '🔴' : section === 'MAJOR' ? '🟡' : '⚪';
        comments.push({
          file: file.trim(),
          line: parseInt(lineNum.trim()),
          body: `${severity} **${section}**: ${issue.trim()}${fix ? `\n\n**Fix:** ${fix.trim()}` : ''}`,
        });
      }
    }
  }

  // Also parse legacy format: - [File/Line X]: Issue. Fix: Suggestion.
  const legacyMatch = review.match(/ISSUES:\s*([\s\S]*?)(?:POSITIVES:|NEXT_STEPS:|$)/i);
  if (legacyMatch) {
    const lines = legacyMatch[1].split('\n').filter(line => line.match(/^-\s*\[/));
    for (const line of lines) {
      const match = line.match(/^-\s*\[(.*?):(.*?)\]:\s*(.*?)(?:\s+Fix:\s+(.*))?$/);
      if (match) {
        const [, file, lineNum, issue, fix] = match;
        comments.push({
          file: file.trim(),
          line: parseInt(lineNum.trim()),
          body: `${issue.trim()}${fix ? `\n\n**Suggestion:** ${fix.trim()}` : ''}`,
        });
      }
    }
  }

  return comments;
}

// ========================================
// GITHUB API — POST COMMENTS & REVIEW
// ========================================

async function postReviewComments(octokit, owner, repo, prNum, comments) {
  const filesResponse = await octokit.rest.pulls.listFiles({
    owner, repo, pull_number: prNum, per_page: 100,
  });

  // Build a map of full paths AND basenames for flexible matching
  const fileMap = {};
  const baseNameMap = {};
  for (const file of filesResponse.data) {
    fileMap[file.filename] = file;
    const baseName = path.basename(file.filename);
    // If multiple files share a basename, prefer exact path match
    if (!baseNameMap[baseName]) {
      baseNameMap[baseName] = file;
    }
  }

  for (const comment of comments) {
    // Try exact path first, then basename
    const file = fileMap[comment.file] || baseNameMap[comment.file];
    if (!file) {
      core.warning(`File ${comment.file} not found in PR. Skipping comment.`);
      continue;
    }

    try {
      // Get the latest commit SHA for the PR
      const prData = await octokit.rest.pulls.get({
        owner, repo, pull_number: prNum,
      });

      await octokit.rest.pulls.createReviewComment({
        owner, repo, pull_number: prNum,
        commit_id: prData.data.head.sha,
        path: file.filename,
        line: Math.min(comment.line, (file.patch || '').split('\n').length || 1),
        body: comment.body,
      });
      core.info(`Posted comment on ${file.filename}:${comment.line}`);
    } catch (error) {
      core.warning(`Failed to post comment on ${file.filename}: ${error.message}`);
    }
  }
}

async function submitReview(octokit, owner, repo, prNum, verdict, fullReview) {
  const reviewBody = [
    '## 🤖 CPM Review Bot',
    '',
    `**Score: ${verdict.score}/10** | **Verdict: ${verdict.status}**`,
    '',
    `> ${verdict.summary}`,
    '',
    fullReview,
    '',
    '---',
    '*Powered by Claude — learnings from PR review history*',
  ].join('\n');

  try {
    await octokit.rest.pulls.createReview({
      owner, repo, pull_number: prNum,
      event: verdict.status === 'APPROVE' ? 'APPROVE'
        : verdict.status === 'CHANGES_REQUESTED' ? 'REQUEST_CHANGES'
        : 'COMMENT',
      body: reviewBody,
    });
    core.info(`Review submitted: ${verdict.status} (${verdict.score}/10)`);
  } catch (error) {
    if (error.status === 422) {
      core.info('Review conflict. Posting as comment instead.');
      await octokit.rest.issues.createComment({
        owner, repo, issue_number: prNum,
        body: reviewBody,
      });
    } else {
      throw error;
    }
  }
}

// ========================================
// ENTRY POINT
// ========================================

main();
