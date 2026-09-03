#!/usr/bin/env node
/*
 * extract_questions.js — dumps an exam file's question data as normalized JSON,
 * for scan_garbling.py to consume.
 *
 * Works with both shapes this skill family produces:
 *   - nbme-exam-builder:   a single `QUESTIONS` array (one 50-item block)
 *   - nbme-step2-builder:  a `BLOCK_QUESTIONS` object with keys 1-4, each a 50-item array
 *
 * Requires jsdom (the same dependency this skill's validation workflow already asks
 * you to install): `npm install jsdom` if not already present in the working directory
 * you run this from.
 *
 * Why jsdom and not a plain `Function` sandbox: the exam's top-level script calls
 * `document.querySelectorAll(...)` etc. immediately (icon painting, event wiring)
 * before the question-data declaration even runs, so a bare sandbox throws
 * "document is not defined" before getting anywhere. jsdom provides a real (headless)
 * document so the script runs to completion exactly like it would in a browser.
 *
 * Why we inject an extraction line just before the script's closing `})();` rather
 * than appending after the whole script, or reading `window.QUESTIONS` afterwards:
 * the entire exam script is wrapped in a top-level IIFE `(function(){ ... })();` for
 * encapsulation, and QUESTIONS/BLOCK_QUESTIONS are declared with `const` *inside* it.
 * Both are therefore invisible from outside that IIFE (top-level `let`/`const` don't
 * become `window` properties even without an IIFE, and an IIFE adds a second layer of
 * scoping on top of that). Splicing the extraction line in immediately before the
 * IIFE's closing `})();` runs it inside that same scope, where the declarations are
 * actually visible.
 *
 * Usage:
 *   node extract_questions.js path/to/exam.html > questions.json
 *
 * Output shape (always a flat JSON array, regardless of source shape):
 *   [
 *     { "id": "6009", "stem": "...", "choices": [["A","..."], ["B","..."]], "explanation": "..." },
 *     ...
 *   ]
 * `id` is prefixed with the block number for 4-block exams (e.g. "b1-6009") so items
 * from different blocks never collide when scan_garbling.py reports on them.
 */
const fs = require('fs');
let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch (e) {
  console.error('jsdom is not installed. Run: npm install jsdom (in the directory you run this from)');
  process.exit(1);
}

const filePath = process.argv[2];
if (!filePath) {
  console.error('Usage: node extract_questions.js path/to/exam.html > questions.json');
  process.exit(1);
}

const html = fs.readFileSync(filePath, 'utf8');
const match = html.match(/<script>([\s\S]*)<\/script>/);
if (!match) {
  console.error('No <script> block found in ' + filePath);
  process.exit(1);
}
const originalScript = match[1];

const extractionSnippet = `
window.__extracted_QUESTIONS = (typeof QUESTIONS !== 'undefined') ? QUESTIONS : undefined;
window.__extracted_BLOCK_QUESTIONS = (typeof BLOCK_QUESTIONS !== 'undefined') ? BLOCK_QUESTIONS : undefined;
`;

// Find the IIFE's closing `})();` at the very end of the script (allow trailing
// whitespace/newlines after it) and splice the extraction snippet in just before it.
// Fall back to appending at the very end if no such wrapper is found (covers a future
// template that doesn't use an IIFE) — either way the snippet ends up in a position
// that at least has a chance of sharing scope with the top-level declarations.
const iifeCloseRe = /\}\)\(\);\s*$/;
let patchedScript;
if (iifeCloseRe.test(originalScript)) {
  patchedScript = originalScript.replace(iifeCloseRe, (m) => extractionSnippet + m);
} else {
  patchedScript = originalScript + extractionSnippet;
}

const patchedHtml =
  html.slice(0, match.index) +
  '<script>' + patchedScript + '</script>' +
  html.slice(match.index + match[0].length);

const url = 'http://localhost/' + filePath;
let dom;
try {
  dom = new JSDOM(patchedHtml, { runScripts: 'dangerously', url, pretendToBeVisual: true });
} catch (e) {
  console.error('Failed to execute the exam script: ' + e.message);
  console.error('(This usually means a syntax error — run the plain syntax check first:');
  console.error(`  node -e "new Function(require('fs').readFileSync('${filePath}','utf8').match(/<script>([\\s\\S]*)<\\/script>/)[1])"`);
  process.exit(1);
}

const win = dom.window;

function normalizeItem(q, idPrefix) {
  const choices = (q.choices || []).map(c => [c.letter, c.text]);
  const item = {
    id: idPrefix + String(q.id),
    stem: q.stem || '',
    choices,
    explanation: q.explanation || ''
  };
  // Pass through every lab panel (labValues, labValues2, labValues3, ...) so
  // scan_garbling.py's "[[LAB_TABLE]] marker with no populated labValues"
  // structural check can actually see them. Without this, every question that
  // legitimately uses a lab table is reported as a structural issue.
  for (const key of Object.keys(q)) {
    if (/^labValues(\d+)?$/.test(key) && Array.isArray(q[key])) {
      item[key] = q[key];
    }
  }
  return item;
}

let out = [];
if (Array.isArray(win.__extracted_QUESTIONS) && win.__extracted_QUESTIONS.length) {
  out = win.__extracted_QUESTIONS.map(q => normalizeItem(q, ''));
} else if (win.__extracted_BLOCK_QUESTIONS && typeof win.__extracted_BLOCK_QUESTIONS === 'object') {
  for (const blockNum of Object.keys(win.__extracted_BLOCK_QUESTIONS).sort()) {
    const block = win.__extracted_BLOCK_QUESTIONS[blockNum];
    if (!Array.isArray(block)) continue;
    for (const q of block) {
      out.push(normalizeItem(q, `b${blockNum}-`));
    }
  }
} else {
  console.error('Neither QUESTIONS nor BLOCK_QUESTIONS was found (or both were empty) in ' + filePath);
  process.exit(1);
}

console.log(JSON.stringify(out, null, 2));
