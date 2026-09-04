#!/usr/bin/env node

/**
 * CPM Review Bot — Test Suite
 * Target: 10/10 score
 *
 * Tests every function in index.js against real PR patterns from
 * Reviewer A (iOS) and Reviewer B (Android) review comments.
 *
 * Run: node test.js
 */

const fs = require('fs');
const path = require('path');

// ========================================
// TEST FRAMEWORK (minimal, zero dependencies)
// ========================================

let totalTests = 0;
let passedTests = 0;
let failedTests = 0;
const failures = [];

function describe(name, fn) {
  console.log(`\n  ${name}`);
  fn();
}

function it(name, fn) {
  totalTests++;
  try {
    fn();
    passedTests++;
    console.log(`    ✅ ${name}`);
  } catch (err) {
    failedTests++;
    failures.push({ name, error: err.message });
    console.log(`    ❌ ${name}`);
    console.log(`       ${err.message}`);
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message || 'Assertion failed');
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(
      `${message || 'assertEqual failed'}\n       Expected: ${JSON.stringify(expected)}\n       Actual:   ${JSON.stringify(actual)}`
    );
  }
}

function assertIncludes(str, substr, message) {
  if (!str.includes(substr)) {
    throw new Error(
      `${message || 'assertIncludes failed'}\n       Expected to contain: "${substr}"\n       In: "${str.substring(0, 200)}..."`
    );
  }
}

function assertMatch(str, regex, message) {
  if (!regex.test(str)) {
    throw new Error(
      `${message || 'assertMatch failed'}\n       Pattern: ${regex}\n       In: "${str.substring(0, 200)}..."`
    );
  }
}

// ========================================
// LOAD MODULE FUNCTIONS (extract from index.js)
// ========================================

// We'll test the pure functions by extracting them.
// index.js uses require('@actions/core') etc at top level, so we mock them.

// Mock @actions/core
const mockCore = {
  getInput: () => '',
  info: () => {},
  warning: () => {},
  setFailed: () => {},
  setOutput: () => {},
};

// Mock @actions/github
const mockGithub = {
  getOctokit: () => ({}),
  context: { payload: {}, repo: { owner: 'test', repo: 'test' } },
};

// Override require for mocking
const Module = require('module');
const originalRequire = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === '@actions/core') return mockCore;
  if (id === '@actions/github') return mockGithub;
  return originalRequire.apply(this, arguments);
};

// Now we can extract functions by reading the source and eval-ing pure functions
const indexSource = fs.readFileSync(path.join(__dirname, 'index.js'), 'utf8');

// Extract individual functions
function extractFunction(source, name) {
  // Match function declarations
  const patterns = [
    new RegExp(`function\\s+${name}\\s*\\([^)]*\\)\\s*\\{`, 'g'),
    new RegExp(`async\\s+function\\s+${name}\\s*\\([^)]*\\)\\s*\\{`, 'g'),
  ];

  for (const pattern of patterns) {
    const match = pattern.exec(source);
    if (match) {
      let braceCount = 0;
      let i = match.index;
      let started = false;
      while (i < source.length) {
        if (source[i] === '{') { braceCount++; started = true; }
        if (source[i] === '}') braceCount--;
        if (started && braceCount === 0) {
          return source.substring(match.index, i + 1);
        }
        i++;
      }
    }
  }
  return null;
}

// Build a mini module with just the pure functions
const coreMock = `const core = { info: () => {}, warning: () => {}, setOutput: () => {} };\n`;
const pathMock = `const path = require('path');\nconst fs = require('fs');\n`;

const functionNames = [
  'detectPlatform',
  'loadPrompt',
  'loadLearnings',
  'buildSystemPrompt',
  'parseVerdict',
  'extractComments',
];

let moduleCode = coreMock + pathMock;
for (const name of functionNames) {
  const fn = extractFunction(indexSource, name);
  if (fn) moduleCode += fn + '\n';
}
moduleCode += 'module.exports = { detectPlatform, loadPrompt, loadLearnings, buildSystemPrompt, parseVerdict, extractComments };';

const tmpPath = path.join(__dirname, '_test_module.js');
fs.writeFileSync(tmpPath, moduleCode);
const mod = require(tmpPath);

// ========================================
// TEST SUITE 1: Platform Detection
// ========================================

console.log('\n══════════════════════════════════════════');
console.log('  CPM REVIEW BOT — TEST SUITE');
console.log('══════════════════════════════════════════');

describe('1. detectPlatform()', () => {
  it('detects iOS from .swift files', () => {
    const diff = `diff --git a/App/Views/Wallet/BuyWalletView.swift b/App/Views/Wallet/BuyWalletView.swift
+++ b/App/Views/Wallet/BuyWalletView.swift
@@ -1,5 +1,10 @@
+import SwiftUI`;
    assertEqual(mod.detectPlatform(diff, 'android'), 'ios');
  });

  it('detects Android from .kt files', () => {
    const diff = `diff --git a/app/src/main/java/com/example/app/ui/wallet/WalletBuyScreen.kt
+++ b/app/src/main/java/com/example/app/ui/wallet/WalletBuyScreen.kt
+package com.example.app.ui.wallet`;
    assertEqual(mod.detectPlatform(diff, 'ios'), 'android');
  });

  it('returns default when no recognizable files', () => {
    const diff = 'diff --git a/README.md b/README.md\n+some text';
    assertEqual(mod.detectPlatform(diff, 'android'), 'android');
    assertEqual(mod.detectPlatform(diff, 'ios'), 'ios');
  });

  it('returns default when both .swift and .kt present', () => {
    const diff = `file.swift\nfile.kt`;
    assertEqual(mod.detectPlatform(diff, 'android'), 'android');
  });

  it('handles empty diff', () => {
    assertEqual(mod.detectPlatform('', 'android'), 'android');
  });
});

// ========================================
// TEST SUITE 2: Prompt Loading
// ========================================

describe('2. loadPrompt()', () => {
  it('loads iOS prompt', () => {
    const prompt = mod.loadPrompt('ios');
    assert(prompt.length > 100, 'iOS prompt should be substantial');
    assertIncludes(prompt, 'Reviewer A', 'Should mention Reviewer A as reviewer');
  });

  it('loads Android prompt', () => {
    const prompt = mod.loadPrompt('android');
    assert(prompt.length > 100, 'Android prompt should be substantial');
    assertIncludes(prompt, 'Reviewer B', 'Should mention Reviewer B as reviewer');
  });

  it('falls back to android prompt for unknown platform', () => {
    // loadPrompt uses ternary: ios → ios-review-prompt.md, else → android-review-prompt.md
    // Unknown platforms default to android prompt (safe fallback)
    const prompt = mod.loadPrompt('flutter');
    assertIncludes(prompt, 'Reviewer B', 'Unknown platform should fall back to Android/Reviewer B prompt');
  });
});

// ========================================
// TEST SUITE 3: Learnings Loading
// ========================================

describe('3. loadLearnings()', () => {
  it('loads iOS learnings with patterns', () => {
    const learnings = mod.loadLearnings('ios');
    assert(learnings !== null, 'Should load iOS learnings');
    assertEqual(learnings.platform, 'ios');
    assert(learnings.patterns.length >= 10, `Expected 10+ patterns, got ${learnings.patterns.length}`);
  });

  it('loads Android learnings with patterns', () => {
    const learnings = mod.loadLearnings('android');
    assert(learnings !== null, 'Should load Android learnings');
    assertEqual(learnings.platform, 'android');
    assert(learnings.patterns.length >= 20, `Expected 20+ patterns, got ${learnings.patterns.length}`);
  });

  it('iOS learnings have DateFormatter pattern (Reviewer A\'s #1 concern)', () => {
    const learnings = mod.loadLearnings('ios');
    const dateFormatter = learnings.patterns.find(p => p.id === 'ios-001');
    assert(dateFormatter, 'Should have DateFormatter pattern');
    assertEqual(dateFormatter.severity, 'critical');
    assert(dateFormatter.frequency >= 2, 'Should have frequency >= 2');
  });

  it('Android learnings have BaseMviViewModel pattern (Reviewer B\'s #1 concern)', () => {
    const learnings = mod.loadLearnings('android');
    const mvi = learnings.patterns.find(p => p.id === 'android-001');
    assert(mvi, 'Should have BaseMviViewModel pattern');
    assertEqual(mvi.severity, 'critical');
    assertEqual(mvi.frequency, 7, 'Should have frequency 7 (7 ViewModels flagged)');
  });

  it('Android learnings have shared-code protection', () => {
    const learnings = mod.loadLearnings('android');
    const sharedCode = learnings.patterns.find(p => p.id === 'android-024');
    assert(sharedCode, 'Should have shared-code pattern');
    assertEqual(sharedCode.severity, 'critical');
    assertIncludes(sharedCode.rule, 'NEVER modify base components');
  });

  it('all patterns have required fields', () => {
    for (const platform of ['ios', 'android']) {
      const learnings = mod.loadLearnings(platform);
      for (const p of learnings.patterns) {
        assert(p.id, `Pattern missing id in ${platform}`);
        assert(p.severity, `Pattern ${p.id} missing severity`);
        assert(p.category, `Pattern ${p.id} missing category`);
        assert(p.rule, `Pattern ${p.id} missing rule`);
        assert(p.bad_example, `Pattern ${p.id} missing bad_example`);
        assert(p.good_example, `Pattern ${p.id} missing good_example`);
        assert(p.source, `Pattern ${p.id} missing source`);
        assert(Array.isArray(p.files_affected), `Pattern ${p.id} files_affected should be array`);
        assert(typeof p.frequency === 'number', `Pattern ${p.id} frequency should be number`);
      }
    }
  });
});

// ========================================
// TEST SUITE 4: System Prompt Building
// ========================================

describe('4. buildSystemPrompt()', () => {
  it('includes base prompt when no learnings', () => {
    const result = mod.buildSystemPrompt('Base prompt content', null);
    assertEqual(result, 'Base prompt content');
  });

  it('appends learnings section when learnings provided', () => {
    const learnings = mod.loadLearnings('android');
    const prompt = mod.loadPrompt('android');
    const result = mod.buildSystemPrompt(prompt, learnings);
    assertIncludes(result, 'REVIEWER LEARNINGS');
    assertIncludes(result, 'from real PR comments');
  });

  it('sorts patterns by frequency (highest first)', () => {
    const learnings = mod.loadLearnings('android');
    const prompt = mod.loadPrompt('android');
    const result = mod.buildSystemPrompt(prompt, learnings);
    // BaseMviViewModel (7x) should appear before SavedStateHandle (3x)
    const mviPos = result.indexOf('android-001');
    const savedStatePos = result.indexOf('android-006');
    assert(mviPos < savedStatePos, 'Higher frequency patterns should appear first');
  });

  it('includes Reviewer B high-level feedback for Android', () => {
    const learnings = mod.loadLearnings('android');
    const result = mod.buildSystemPrompt('prompt', learnings);
    assertIncludes(result, 'High-Level Expectations');
    assertIncludes(result, 'nre-nro');
  });

  it('includes severity labels in output', () => {
    const learnings = mod.loadLearnings('ios');
    const result = mod.buildSystemPrompt('prompt', learnings);
    assertIncludes(result, 'CRITICAL');
    assertIncludes(result, 'flagged');
  });
});

// ========================================
// TEST SUITE 5: Verdict Parsing
// ========================================

describe('5. parseVerdict()', () => {
  it('parses APPROVE verdict', () => {
    const review = 'VERDICT: APPROVE\nSUMMARY: Code looks great\nSCORE: 9/10';
    const v = mod.parseVerdict(review);
    assertEqual(v.status, 'APPROVE');
    assertEqual(v.conclusion, 'success');
    assertEqual(v.score, 9);
  });

  it('parses CHANGES_REQUESTED verdict', () => {
    const review = 'VERDICT: CHANGES_REQUESTED\nSUMMARY: Multiple issues found\nSCORE: 4/10';
    const v = mod.parseVerdict(review);
    assertEqual(v.status, 'CHANGES_REQUESTED');
    assertEqual(v.conclusion, 'failure');
    assertEqual(v.score, 4);
  });

  it('defaults to COMMENT when no verdict', () => {
    const review = 'Some general feedback\nSCORE: 6/10';
    const v = mod.parseVerdict(review);
    assertEqual(v.status, 'COMMENT');
    assertEqual(v.conclusion, 'neutral');
  });

  it('extracts score correctly', () => {
    const review = 'VERDICT: APPROVE\nSCORE: 10/10\nSUMMARY: Perfect';
    const v = mod.parseVerdict(review);
    assertEqual(v.score, 10);
  });

  it('defaults score to 0 when missing', () => {
    const review = 'VERDICT: APPROVE\nSUMMARY: Good code';
    const v = mod.parseVerdict(review);
    assertEqual(v.score, 0);
  });

  it('extracts summary', () => {
    const review = 'VERDICT: APPROVE\nSUMMARY: Clean MVI implementation\nSCORE: 8/10';
    const v = mod.parseVerdict(review);
    assertEqual(v.summary, 'Clean MVI implementation');
  });

  it('counts critical issues', () => {
    const review = `VERDICT: CHANGES_REQUESTED
SUMMARY: Issues found
CRITICAL:
- [File.kt:Line 5]: Issue one
- [File.kt:Line 10]: Issue two
- [File.kt:Line 15]: Issue three
MAJOR:
- [File.kt:Line 20]: Minor issue
SCORE: 3/10`;
    const v = mod.parseVerdict(review);
    assertEqual(v.criticalCount, 3, 'Should count 3 critical issues');
    assertEqual(v.majorCount, 1, 'Should count 1 major issue');
  });

  it('handles case-insensitive verdict', () => {
    const review = 'verdict: approve\nsummary: ok\nscore: 7/10';
    const v = mod.parseVerdict(review);
    assertEqual(v.status, 'APPROVE');
  });
});

// ========================================
// TEST SUITE 6: Comment Extraction
// ========================================

describe('6. extractComments() — new severity format', () => {
  it('extracts CRITICAL comments', () => {
    const review = `CRITICAL:
- [WalletBuyViewModel.kt:Line 35]: ViewModel extends raw ViewModel() instead of BaseMviViewModel. Fix: Extend BaseMviViewModel<State, Event, Command>(feature).
MAJOR:
- [WalletCoinsSection.kt:Line 85]: Using Color.White instead of Theme.colors. Fix: Use Theme.colors.fillsSurfaceWhite.
SCORE: 4/10`;
    const comments = mod.extractComments(review, '');
    assert(comments.length >= 2, `Expected 2+ comments, got ${comments.length}`);
    assertIncludes(comments[0].body, 'CRITICAL');
    assertIncludes(comments[0].body, 'BaseMviViewModel');
    assertEqual(comments[0].line, 35);
  });

  it('extracts MINOR comments', () => {
    const review = `MINOR:
- [WalletTransactionGrouper.kt:Line 11]: Useless comments. Fix: Remove them.
SCORE: 8/10`;
    const comments = mod.extractComments(review, '');
    assert(comments.length >= 1, `Expected 1+ comments, got ${comments.length}`);
  });

  it('handles colon separator in file path', () => {
    const review = `CRITICAL:
- [WalletBuyViewModel.kt:35]: Missing MVI. Fix: Use BaseMviViewModel.
SCORE: 3/10`;
    const comments = mod.extractComments(review, '');
    assert(comments.length >= 1, `Expected 1+ comments, got ${comments.length}`);
    assertEqual(comments[0].line, 35);
  });

  it('handles slash separator', () => {
    const review = `MAJOR:
- [WalletBuyScreen.kt/Line 15]: Missing preview. Fix: Add @Preview.
SCORE: 6/10`;
    const comments = mod.extractComments(review, '');
    assert(comments.length >= 1, `Expected 1+ comments, got ${comments.length}`);
    assertEqual(comments[0].line, 15);
  });

  it('handles legacy ISSUES format', () => {
    const review = `ISSUES:
- [WalletBuyViewModel.kt:35]: Uses raw ViewModel. Fix: Use BaseMviViewModel.
- [WalletService.kt:83]: Repeated headers. Fix: Use OkHttp interceptor.
POSITIVES: Good test coverage`;
    const comments = mod.extractComments(review, '');
    assert(comments.length >= 2, `Expected 2+ comments, got ${comments.length}`);
  });

  it('returns empty array for no issues', () => {
    const review = 'VERDICT: APPROVE\nSUMMARY: All good\nSCORE: 10/10';
    const comments = mod.extractComments(review, '');
    assertEqual(comments.length, 0);
  });

  it('adds severity emoji to comment body', () => {
    const review = `CRITICAL:
- [File.kt:Line 1]: Bad code. Fix: Good code.
MAJOR:
- [File2.kt:Line 2]: Minor bad. Fix: Minor good.
SCORE: 5/10`;
    const comments = mod.extractComments(review, '');
    const critical = comments.find(c => c.body.includes('CRITICAL'));
    const major = comments.find(c => c.body.includes('MAJOR'));
    assert(critical, 'Should have critical comment');
    assert(major, 'Should have major comment');
  });
});

// ========================================
// TEST SUITE 7: iOS Pattern Detection (simulated)
// ========================================

describe('7. iOS Review Patterns (Reviewer A\'s rules)', () => {
  const iosPrompt = mod.loadPrompt('ios');
  const iosLearnings = mod.loadLearnings('ios');
  const systemPrompt = mod.buildSystemPrompt(iosPrompt, iosLearnings);

  it('prompt catches DateFormatter instantiation', () => {
    assertIncludes(systemPrompt, 'DateFormatter');
    assertIncludes(systemPrompt, 'static let');
    assertIncludes(systemPrompt, 'most expensive');
  });

  it('prompt catches force unwraps', () => {
    assertIncludes(systemPrompt, 'Force Unwrap');
    assertIncludes(systemPrompt, 'NEVER acceptable');
  });

  it('prompt catches shared file modifications', () => {
    assertIncludes(systemPrompt, 'CurrencyFormatter');
    assertIncludes(systemPrompt, 'Revert');
    assertIncludes(systemPrompt, 'whole project');
  });

  it('prompt catches dangerous USD defaults', () => {
    assertIncludes(systemPrompt, '?? "USD"');
    assertIncludes(systemPrompt, 'UK');
    assertIncludes(systemPrompt, 'wrong information');
  });

  it('prompt catches missing enums for status strings', () => {
    assertIncludes(systemPrompt, 'WalletOrderStatus');
    assertIncludes(systemPrompt, 'ONBOARDING_ALREADY_COMPLETE');
  });

  it('prompt catches hardcoded header keys', () => {
    assertIncludes(systemPrompt, 'X-Country');
    assertIncludes(systemPrompt, 'Constants');
  });

  it('prompt catches failable init with empty defaults', () => {
    assertIncludes(systemPrompt, 'accountName');
    assertIncludes(systemPrompt, 'return nil');
  });

  it('prompt catches localization issues', () => {
    assertIncludes(systemPrompt, 'R.string.localizable');
    assertIncludes(systemPrompt, 'localizable');
  });

  it('prompt catches duplicate assets', () => {
    assertIncludes(systemPrompt, 'duplicate');
    assertIncludes(systemPrompt, 'DesignKit');
  });

  it('prompt has approval checklist', () => {
    assertIncludes(systemPrompt, 'Approval Checklist');
    // Count checklist items
    const checkItems = (systemPrompt.match(/- \[ \]/g) || []).length;
    assert(checkItems >= 15, `Expected 15+ checklist items, got ${checkItems}`);
  });

  it('prompt has SCORE output format', () => {
    assertIncludes(systemPrompt, 'SCORE: X/10');
  });
});

// ========================================
// TEST SUITE 8: Android Pattern Detection (simulated)
// ========================================

describe('8. Android Review Patterns (Reviewer B\'s rules)', () => {
  const androidPrompt = mod.loadPrompt('android');
  const androidLearnings = mod.loadLearnings('android');
  const systemPrompt = mod.buildSystemPrompt(androidPrompt, androidLearnings);

  it('prompt catches raw ViewModel() (Reviewer B\'s #1 concern)', () => {
    assertIncludes(systemPrompt, 'BaseMviViewModel');
    assertIncludes(systemPrompt, ': ViewModel()');
    assertIncludes(systemPrompt, '7');
  });

  it('prompt catches hardcoded order statuses', () => {
    assertIncludes(systemPrompt, '"COMPLETED"');
    assertIncludes(systemPrompt, '"ORDER_COMPLETED"');
    assertIncludes(systemPrompt, 'sealed interface');
  });

  it('prompt catches dangerous currency defaults', () => {
    assertIncludes(systemPrompt, '"USD"');
    assertIncludes(systemPrompt, 'dangerous');
    assertIncludes(systemPrompt, 'required fields');
  });

  it('prompt catches Screen(viewModel) anti-pattern', () => {
    assertIncludes(systemPrompt, 'State, accept: (Event) -> Unit');
    assertIncludes(systemPrompt, 'Too much params');
  });

  it('prompt catches missing @Preview', () => {
    assertIncludes(systemPrompt, '@Preview');
    assertIncludes(systemPrompt, 'AppScreen');
  });

  it('prompt catches base component modifications', () => {
    assertIncludes(systemPrompt, 'PlusButton.kt');
    assertIncludes(systemPrompt, 'MainFragment.kt');
    assertIncludes(systemPrompt, 'app.gradle.kts');
  });

  it('prompt catches SavedStateHandle requirement', () => {
    assertIncludes(systemPrompt, 'SavedStateHandle');
    assertIncludes(systemPrompt, 'arguments?.getString');
  });

  it('prompt catches CoreCommands for toasts', () => {
    assertIncludes(systemPrompt, 'CoreCommands');
    assertIncludes(systemPrompt, 'showPlusToast');
  });

  it('prompt catches Theme color enforcement', () => {
    assertIncludes(systemPrompt, 'Color.White');
    assertIncludes(systemPrompt, 'Theme.colors');
    assertIncludes(systemPrompt, 'fillsSurfaceWhite');
  });

  it('prompt catches Theme typography enforcement', () => {
    assertIncludes(systemPrompt, 'fontSize = 15.sp');
    assertIncludes(systemPrompt, 'Theme.typography');
  });

  it('prompt catches LazyColumn key requirement', () => {
    assertIncludes(systemPrompt, 'key = { it.id }');
  });

  it('prompt catches OkHttp interceptor pattern', () => {
    assertIncludes(systemPrompt, 'OkHttp');
    assertIncludes(systemPrompt, 'Interceptor');
    assertIncludes(systemPrompt, 'X-User-Id');
  });

  it('prompt catches empty state handling', () => {
    assertIncludes(systemPrompt, 'EmptyStateStub');
    assertIncludes(systemPrompt, 'silently return');
  });

  it('prompt has BigDecimal enforcement', () => {
    assertIncludes(systemPrompt, 'BigDecimal');
    assertIncludes(systemPrompt, 'Double/Float');
  });

  it('prompt references nre-nro patterns', () => {
    assertIncludes(systemPrompt, 'nre-nro');
    assertIncludes(systemPrompt, 'develop');
  });

  it('prompt has Reviewer B\'s philosophy quote', () => {
    assertIncludes(systemPrompt, 'Writing code is not the hardest part');
    assertIncludes(systemPrompt, 'supporting it later');
  });

  it('prompt has approval checklist', () => {
    assertIncludes(systemPrompt, 'Approval Checklist');
    const checkItems = (systemPrompt.match(/- \[ \]/g) || []).length;
    assert(checkItems >= 15, `Expected 15+ checklist items, got ${checkItems}`);
  });

  it('prompt has SCORE output format', () => {
    assertIncludes(systemPrompt, 'SCORE: X/10');
  });

  it('prompt has market-specific considerations', () => {
    assertIncludes(systemPrompt, 'US vs UK');
    assertIncludes(systemPrompt, 'WalletConstants');
  });
});

// ========================================
// TEST SUITE 9: Learnings Data Integrity
// ========================================

describe('9. Learnings Data Integrity', () => {
  it('iOS learnings stats match pattern counts', () => {
    const l = mod.loadLearnings('ios');
    const critical = l.patterns.filter(p => p.severity === 'critical').length;
    const major = l.patterns.filter(p => p.severity === 'major').length;
    const minor = l.patterns.filter(p => p.severity === 'minor').length;
    assertEqual(l.stats.critical, critical, 'Critical count mismatch');
    assertEqual(l.stats.major, major, 'Major count mismatch');
    assertEqual(l.stats.minor, minor, 'Minor count mismatch');
  });

  it('Android learnings stats match pattern counts', () => {
    const l = mod.loadLearnings('android');
    const critical = l.patterns.filter(p => p.severity === 'critical').length;
    const major = l.patterns.filter(p => p.severity === 'major').length;
    const minor = l.patterns.filter(p => p.severity === 'minor').length;
    assertEqual(l.stats.critical, critical, 'Critical count mismatch');
    assertEqual(l.stats.major, major, 'Major count mismatch');
    assertEqual(l.stats.minor, minor, 'Minor count mismatch');
  });

  it('all pattern IDs are unique within platform', () => {
    for (const platform of ['ios', 'android']) {
      const l = mod.loadLearnings(platform);
      const ids = l.patterns.map(p => p.id);
      const unique = new Set(ids);
      assertEqual(ids.length, unique.size, `Duplicate IDs in ${platform} learnings`);
    }
  });

  it('severity values are valid', () => {
    const valid = ['critical', 'major', 'minor'];
    for (const platform of ['ios', 'android']) {
      const l = mod.loadLearnings(platform);
      for (const p of l.patterns) {
        assert(valid.includes(p.severity), `Invalid severity "${p.severity}" for ${p.id}`);
      }
    }
  });

  it('all patterns have PR source references', () => {
    for (const platform of ['ios', 'android']) {
      const l = mod.loadLearnings(platform);
      for (const p of l.patterns) {
        assertMatch(p.source, /PR #\d+/, `Pattern ${p.id} missing PR reference in source`);
      }
    }
  });

  it('category values are consistent', () => {
    const validCategories = [
      'architecture', 'type-safety', 'safety', 'performance',
      'compose-pattern', 'shared-code', 'constants', 'localization',
      'code-quality', 'ux', 'assets',
    ];
    for (const platform of ['ios', 'android']) {
      const l = mod.loadLearnings(platform);
      for (const p of l.patterns) {
        assert(validCategories.includes(p.category), `Invalid category "${p.category}" for ${p.id}`);
      }
    }
  });
});

// ========================================
// TEST SUITE 10: Integration — Full Review Simulation
// ========================================

describe('10. Integration — Full Review Flow', () => {
  it('iOS: full system prompt is under Claude token limit', () => {
    const prompt = mod.loadPrompt('ios');
    const learnings = mod.loadLearnings('ios');
    const full = mod.buildSystemPrompt(prompt, learnings);
    // Rough estimate: 1 token ≈ 4 chars. Claude's system prompt limit is ~200K tokens
    const estimatedTokens = full.length / 4;
    assert(estimatedTokens < 50000, `System prompt too large: ~${estimatedTokens} tokens`);
  });

  it('Android: full system prompt is under Claude token limit', () => {
    const prompt = mod.loadPrompt('android');
    const learnings = mod.loadLearnings('android');
    const full = mod.buildSystemPrompt(prompt, learnings);
    const estimatedTokens = full.length / 4;
    assert(estimatedTokens < 50000, `System prompt too large: ~${estimatedTokens} tokens`);
  });

  it('simulated CHANGES_REQUESTED review parses correctly', () => {
    const simulatedReview = `VERDICT: CHANGES_REQUESTED

SUMMARY: Multiple MVI violations and hardcoded values found.

CRITICAL:
- [WalletBuyViewModel.kt:Line 35]: ViewModel extends raw ViewModel() instead of BaseMviViewModel. Fix: Extend BaseMviViewModel<State, Event, Command>(WalletBuyFeature).
- [WalletProcessingViewModel.kt:Line 33]: Not consistent with MviViewModel. Fix: Use BaseMviViewModel.
- [WalletOrderReviewFeature.kt:Line 325]: Hardcoded status strings "COMPLETED", "ORDER_COMPLETED". Fix: Use sealed interface OrderStatus.

MAJOR:
- [WalletProcessingFragment.kt:Line 51]: Manual argument reading instead of SavedStateHandle. Fix: Inject SavedStateHandle in ViewModel constructor.
- [WalletCoinsSection.kt:Line 85]: Using Color.White instead of Theme token. Fix: Use Theme.colors.fillsSurfaceWhite.
- [WalletBuyScreen.kt:Line 15]: Missing @Preview composable. Fix: Add @Preview annotation with sample state.

MINOR:
- [WalletBuyFeature.kt:Line 57]: Long fully-qualified imports. Fix: Use short imports at file top.
- [WalletTransactionGrouper.kt:Line 11]: Useless comments. Fix: Delete self-evident comments.

SCORE: 4/10

POSITIVES: Good test coverage for WalletHomeFeature and WalletOrderReviewFeature.

NEXT_STEPS: Address all critical MVI violations first, then fix major issues. Re-push for review.`;

    const verdict = mod.parseVerdict(simulatedReview);
    assertEqual(verdict.status, 'CHANGES_REQUESTED');
    assertEqual(verdict.score, 4);
    assertEqual(verdict.criticalCount, 3);
    assertEqual(verdict.majorCount, 3);
    assertIncludes(verdict.summary, 'MVI violations');

    const comments = mod.extractComments(simulatedReview, '');
    assert(comments.length >= 7, `Expected 7+ comments, got ${comments.length}`);

    // Verify severity tagging
    const criticals = comments.filter(c => c.body.includes('CRITICAL'));
    const majors = comments.filter(c => c.body.includes('MAJOR'));
    assert(criticals.length >= 3, `Expected 3+ critical comments, got ${criticals.length}`);
    assert(majors.length >= 3, `Expected 3+ major comments, got ${majors.length}`);
  });

  it('simulated APPROVE review parses correctly', () => {
    const simulatedReview = `VERDICT: APPROVE

SUMMARY: Clean MVI implementation following all project patterns.

SCORE: 9/10

POSITIVES: Excellent use of BaseMviViewModel, proper SavedStateHandle injection, all screens have @Preview, Theme tokens used consistently.`;

    const verdict = mod.parseVerdict(simulatedReview);
    assertEqual(verdict.status, 'APPROVE');
    assertEqual(verdict.score, 9);
    assertEqual(verdict.criticalCount, 0);
    assertEqual(verdict.majorCount, 0);

    const comments = mod.extractComments(simulatedReview, '');
    assertEqual(comments.length, 0, 'Approved review should have no inline comments');
  });

  it('all prompt files exist and are non-empty', () => {
    const files = [
      'prompts/ios-review-prompt.md',
      'prompts/android-review-prompt.md',
      'learnings/ios-reviewer-a.json',
      'learnings/android-reviewer-b.json',
    ];
    for (const file of files) {
      const fullPath = path.join(__dirname, file);
      assert(fs.existsSync(fullPath), `Missing: ${file}`);
      const content = fs.readFileSync(fullPath, 'utf8');
      assert(content.length > 100, `File too small: ${file} (${content.length} chars)`);
    }
  });

  it('action.yml has correct outputs defined', () => {
    const actionYml = fs.readFileSync(path.join(__dirname, 'action.yml'), 'utf8');
    assertIncludes(actionYml, 'verdict');
    assertIncludes(actionYml, 'score');
    assertIncludes(actionYml, 'critical_count');
    assertIncludes(actionYml, 'major_count');
  });
});

// ========================================
// RESULTS
// ========================================

// Cleanup temp module
try { fs.unlinkSync(tmpPath); } catch {}
// Restore require
Module.prototype.require = originalRequire;

console.log('\n══════════════════════════════════════════');
console.log(`  RESULTS: ${passedTests}/${totalTests} passed`);
console.log(`  Score: ${Math.round((passedTests / totalTests) * 10)}/10`);
console.log('══════════════════════════════════════════');

if (failures.length > 0) {
  console.log('\n  FAILURES:');
  for (const f of failures) {
    console.log(`    ❌ ${f.name}: ${f.error}`);
  }
}

console.log('');
process.exit(failedTests > 0 ? 1 : 0);
