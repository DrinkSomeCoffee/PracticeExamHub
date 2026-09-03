#!/usr/bin/env node
/*
 * verify_click_through.js — the strongest available check that a generated
 * exam actually scores correctly: drives the real UI (not just the data),
 * clicking the correct answer on every item via the same DOM elements a
 * test-taker would click, ends the block, and asserts the resulting score
 * is N/N. This is a stronger signal than extract_questions.js + scan_garbling.py
 * alone — those check the *data* is well-formed and ungarbled, but never
 * confirm the answer-selection/scoring wiring actually works end to end for
 * this specific generated file.
 *
 * Why this exists: building Internal Medicine Form 4/5 for real (as opposed
 * to a sample/dry-run) surfaced that the structural+garbling scan is
 * necessary but not sufficient — it can't catch a mismatched `correct`
 * letter, a choices array in the wrong order, or a generator/chrome wiring
 * bug, because none of those "garble" the text. Actually clicking through
 * and checking the score does.
 *
 * Requires jsdom, same as extract_questions.js: `npm install jsdom` in the
 * directory you run this from (the project root, not a scratch folder —
 * Node resolves node_modules from the current working directory).
 *
 * Usage:
 *   node verify_click_through.js path/to/exam.html
 *
 * Exit code 0 + "PASS" printed means every item scored correctly. Non-zero
 * exit or "FAIL" means something is wrong — investigate before presenting
 * the exam as finished.
 *
 * IMPORTANT gotcha: the exam's own chrome starts a live `setInterval` for
 * the elapsed-time timer display. That interval keeps Node's event loop
 * alive forever, so this script (and extract_questions.js, which loads the
 * same chrome) will hang *after* finishing all real work and printing its
 * result. Always run this under a timeout and treat a timeout-triggered
 * exit code (124 under the `timeout` command) as normal, NOT a failure —
 * check whether "PASS"/"FAIL" was already printed to stdout before the kill,
 * that's the actual result. Example:
 *   timeout 25 node assets/verify_click_through.js dependencies/exam.html
 */
const fs = require('fs');
let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch (e) {
  console.error('jsdom is not installed. Run: npm install jsdom (in the project root you run this from)');
  process.exit(1);
}

const filePath = process.argv[2];
if (!filePath) {
  console.error('Usage: node verify_click_through.js path/to/exam.html');
  process.exit(1);
}

const html = fs.readFileSync(filePath, 'utf8');
const match = html.match(/<script>([\s\S]*)<\/script>/);
if (!match) {
  console.error('No <script> block found in ' + filePath);
  process.exit(1);
}
const originalScript = match[1];

// Same technique as extract_questions.js: QUESTIONS is declared `const`
// inside a top-level IIFE, so it's invisible from outside. Splice a line
// that exposes it on `window` in just before the IIFE's closing `})();` so
// it shares scope with the declaration.
const extractionSnippet = `\nwindow.__Q = (typeof QUESTIONS !== 'undefined') ? QUESTIONS : undefined;\n`;
const iifeCloseRe = /\}\)\(\);\s*$/;
const patchedScript = iifeCloseRe.test(originalScript)
  ? originalScript.replace(iifeCloseRe, (m) => extractionSnippet + m)
  : originalScript + extractionSnippet;
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
  process.exit(1);
}
const { window } = dom;
const { document } = window;

function click(el) {
  el.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function main() {
  const QUESTIONS = window.__Q;
  if (!Array.isArray(QUESTIONS) || !QUESTIONS.length) {
    console.error('Could not read QUESTIONS from window.__Q — this script only supports single-block exams (nbme-exam-builder-markdown), not the 4-block sibling.');
    process.exit(1);
  }
  const total = QUESTIONS.length;
  console.log('Total items:', total);

  for (let i = 0; i < total; i++) {
    const q = QUESTIONS[i];
    const row = document.querySelector(`.answer-row[data-letter="${q.correct}"]`);
    if (!row) {
      console.error(`FAIL: item ${i} (id ${q.id}) — no answer row found for correct letter "${q.correct}". Check the choices array has that letter.`);
      process.exit(1);
    }
    click(row);
    if (i < total - 1) {
      click(document.getElementById('btn-next'));
    }
  }

  click(document.getElementById('btn-endblock'));
  click(document.getElementById('btn-endblock-confirm'));

  const fractionEl = document.getElementById('results-fraction');
  const scoreEl = document.getElementById('results-score');
  const actual = fractionEl ? fractionEl.textContent.trim() : '(missing)';
  console.log('Score:', scoreEl ? scoreEl.textContent : '(missing)', 'Fraction:', actual);

  if (actual !== `${total}/${total}`) {
    console.error(`FAIL: expected ${total}/${total} but got ${actual}. This means at least one item's "correct" letter doesn't match what the scoring engine recorded as selected — re-check the content JSON's correct/choices fields for a mismatch, don't assume this script itself is wrong.`);
    process.exit(1);
  }

  console.log(`PASS: all ${total} items scored correctly.`);
}

setTimeout(main, 300); // let the IIFE finish its initial synchronous render first
