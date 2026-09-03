# Notes for future NBME exam builds (screenshot-captured PDFs)

Lessons from building Pediatrics Form 8, then Form 7. Attach this file (or paste its
contents) at the start of a future exam-build chat, or add it to project knowledge, so
these don't need to be rediscovered.

## Environment constraints

- Shell commands here have a hard ~45s timeout, and background/`nohup` processes do
  **not** survive between calls (they die when that call's process namespace tears
  down). For long jobs (rendering 100+ pages, OCR'ing all of them), don't try to
  background them — write the script to be idempotent (skip files that already exist)
  and just re-invoke it synchronously across several calls until it reports done.
- Check `/tmp` for stale files from unrelated prior sessions before writing there
  (they can be owned by a different user and cause permission errors). Use a fresh
  directory.
- `pdftotext`/`pdftoppm`/`pdfimages`/`pdfinfo` (poppler) and `tesseract` may not be
  preinstalled — check with `which` before assuming. `brew install poppler` pulls in a
  newer `libtiff`, which breaks an existing `tesseract`/`leptonica` install (dyld error:
  `Library not loaded: .../libtiff.5.dylib`) since it was linked against the old major
  version — fix with `brew reinstall leptonica tesseract` to relink against the current
  one. Also install `Pillow`/`numpy` via `pip3 install --user` if missing; there's no
  `node`/`npm` in this environment, so plan validation around Python + a real browser
  rather than the `node -e`/`jsdom` approach described below.
- `pdfinfo`'s page count is authoritative — a PDF-reading tool's own page estimate can
  be wildly wrong (seen: reported 237 pages for a 112-page file) if it's guessing from
  file size rather than actually parsing the page tree.

## OCR pipeline

1. Try `pdftotext -layout` first — if the PDF is a real screenshot capture with no
   text layer, it'll return junk (just a repeated watermark). Confirm before assuming
   OCR is needed.
2. Rasterize with `pdftoppm -png -r 150` and OCR with `tesseract`. Use **numpy**
   (vectorized) for any pixel-level image cleanup, not a raw Python `for` loop over
   pixels — the loop version can time out on a single page.
3. **Yellow-highlighted text silently defeats tesseract** — it drops the whole line,
   not just garbles it. Fix: threshold out yellow pixels (high R, high G, low-ish B)
   to white before OCR. This alone fixed most missing-choice issues.
4. **Gray strikethrough text** (eliminated answer choices in review-mode screenshots)
   also breaks OCR, but isn't fixable by color threshold — it needs a direct image
   view to transcribe. These pages are usually predictable (table-based questions,
   any page where an answer count looks short) — spot-check with the image tool.
5. Sample a handful of varied pages **before** committing to a parsing pipeline: one
   normal page, one table/matrix-style question, one image-referencing question, one
   with visible strikethrough. This surfaces the above failure modes early instead of
   discovering them mid-parse and having to patch after the fact.
6. A personal-study-notes export (highlighter used for emphasis *throughout the
   vignette*, not just to mark the correct choice, plus a strikethrough on
   user-eliminated choices) needs the yellow-threshold fix applied to the **whole
   page**, not just the choice-list region — otherwise stem sentences silently lose
   words too.
7. The small checkmark/flag icon in the page's top-left corner OCRs as a stray leading
   token glued in front of the item number — seen as `v`, `¥`, `vi`, `_`, etc., either
   space-separated ("v 12. A 10-year-old...") or fully glued with no space at all
   ("_Apreviously healthy..."). It shows up on nearly every page, not just ones with
   other markup, so strip it unconditionally rather than only when something else
   looks wrong. Strip in stages against the **joined** stem text (see next point), not
   against `lines[0]`, since a preserved leading blank line can shift which physical
   line actually holds the prefix.
8. Blank lines matter — they're the only signal for paragraph breaks in the
   explanation. A noise-line filter that treats "empty string" as noise and drops it
   (e.g. `if not line.strip(): return True`) silently collapses the entire multi-page
   explanation into one run-on paragraph. Filter noise *content* lines, but always
   preserve blank lines as-is.
9. The vignette's leading article routinely glues to the next word/number
   ("Apreviously", "A22-month-old", "A2495-g"). Fix by checking the stem's first
   whitespace-delimited token: if it's longer than "A"/"An" but still starts with one
   of them, re-insert the space — but only after ruling out that it's already a
   correctly-spaced "An" (an unconditional regex insert after a bare leading "A"
   before any lowercase letter will wrongly split a fine "An 18-year-old..." into
   "A n18-year-old...").
10. `I` (choice/correct-answer letter, roman-numeral-adjacent contexts) is frequently
    OCR'd as a bare `|` — "Correct Answer: |.", "(Choice |)", "Renal tubular acidosis"
    losing its `I)` marker entirely. Don't assume extended-matching lists stop at `G`;
    one seen here ran to `I` (9 choices). A choice-line regex anchored to `[A-G]` will
    silently drop every choice at or past `H`.
11. The **selected/highlighted** choice's radio icon is a second, independent source of
    leading-junk-before-the-letter — sometimes a stray symbol, sometimes a fully
    different misread letter ("J D) Cardioversion", "| s C) Fetal alcohol syndrome").
    A choice-start regex needs a generously lazy junk-skip (up to ~6 chars) in front of
    the real `LETTER)` pattern, not just a tight 1-3-char symbol class.

## Parsing OCR text into questions

- Figure out which item each page belongs to from the page **header** ("Item N of 50"),
  not from the numbered stem line — the header survives OCR far more reliably. Search
  the header pattern in the whole page (not just line 1; it sometimes lands on line 2-3)
  and forward-fill the item number for any page where it's missing entirely. But don't
  trust the forward-fill blindly: a page can still be a genuine new-item start even when
  its header OCR'd to nothing (cross-check against a loose "next sequential number
  followed by '. ' and a capital letter" match in the page's own text before assuming
  it's a continuation).
- Multi-page-per-item captures can overlap in more than one way:
  - A later page re-showing the tail of the previous page's content before continuing
    (classic scroll-capture overlap).
  - **A deliberate recap**: every continuation page in this source restated
    "Correct Answer: X." plus the *entire first explanation paragraph* again before
    going on to new content ("Incorrect Answers...", etc). Detect this by watching for
    a *second* "Correct Answer:" line appearing after the first one within the same
    item's explanation span, and drop that line plus the paragraph immediately after it
    (the recap), not just dedup by prefix matching.
  - Sometimes the recap repeats a *tail of the choice list* too, gluing straight into
    the restated "Correct Answer: X." with no paragraph break — e.g. "...D) Type 1
    collagen E) Type 2 collagen Correct Answer: B." embedded mid-sentence. Strip from
    the start of whichever paragraph contains an embedded "Correct Answer:" through the
    marker itself, not just the marker line alone.
  - Even the *very last* item (no following page to recap onto) can still show this
    exact duplicate-paragraph pattern with no "Correct Answer:" marker at all if the
    source simply repeats content across the page break. Keep a general safety net: drop
    any paragraph whose first ~80 characters already appear in an earlier kept
    paragraph, checked via substring containment (not just exact-prefix), after the
    marker-based passes above.
- Build the header/footer noise filter via **frequency analysis**: count short lines
  (<60 chars) across all pages — anything repeating dozens of times is UI chrome
  (nav bar, watermark, footer icons), never real question content. This is faster and
  more complete than hand-guessing regex patterns for garbled OCR text one at a time.
  Never include an empty string in this filter — see the blank-line note above.
- Watch for choices that got merged onto one OCR line (e.g. "Measles F ) Meningococcemia")
  — split on embedded `letter)` markers that aren't already used.
- **Page-overlap can also duplicate a choice**, not just explanation text — a
  continuation page re-showing the last 1-2 choices from the bottom of the previous
  page before continuing the list. Parse choices into a letter-keyed dict (later
  occurrence overwrites earlier), not a plain append-only list, so a repeat just
  no-ops instead of producing a duplicate entry — **but** this same overwrite behavior
  will silently corrupt a choice if an unrelated garbled line gets misread as an
  *already-used* letter with *unrelated* text (seen: a mangled "E" reading as "B",
  overwriting the real choice B with choice E's text and leaving E missing entirely).
  There's no fully general fix for this one — after auto-parsing, cross-check every
  `(Choice X)` mentioned in the explanation against the same letter's parsed choice
  text (first few significant words should appear near the mention); a mismatch means
  manual correction against the source image, not another regex tweak.
- After parsing, sanity-check per item: choice letters should be a set of unique
  consecutive-ish values (extended-matching lists can legitimately skip a letter if the
  user struck it through — see below — so don't require a perfectly consecutive run
  starting at A, just no duplicates), the `correct` letter should be among the parsed
  choices, and every explanation should contain "Educational Objective" (its natural
  end marker) and should **not** still contain a literal "Correct Answer:" (a sign a
  recap didn't get stripped). Flag anything that doesn't for manual review against the
  source image.
- **A struck-through (user-eliminated) choice is invisible to every fix above** — it's
  not a color-threshold problem, so it silently vanishes from the choice list, and its
  garbled remnant (closing paren OCR'd as `}` instead of `)`, e.g. "A} Addison
  disease") usually leaks onto the *previous* successfully-parsed choice's text as a
  trailing suffix instead of being recognized as its own choice. This class of bug
  passes every structural sanity check (letters can still look consecutive if the
  struck choice isn't first/last) — the only way to catch it is opening the source
  image for any item where the choice count looks short for its answer-lettering
  range, or where the last choice's text looks longer than a normal answer option.
- **Don't fully trust an OCR'd "Incorrect Answers: A, C, D, and E." line as a
  cross-check** for which letter is correct — in one item here it directly contradicted
  the highlighted/`Correct Answer:` letter shown in the source image (the image is the
  authoritative one, since that's what actually drives the interactive quiz's answer
  key). This looks like a genuine error in the source material itself, not an OCR
  artifact — leave the explanation prose as transcribed rather than silently rewriting
  it to match, and flag the discrepancy to the user.
- A source PDF that's a genuine "Answers" export (screenshots of the Score Report /
  Review Mode screen, one item per 2-4 pages, question+choices+explanation all
  together) needs *no* separate answer-key guessing step — every item already states
  "Correct Answer: X." directly. Reserve the "best-effort placeholder, flag it" approach
  for source documents that genuinely lack this.
- Watch for a handful of **specific OCR letter-confusions** that show up character-by-
  character rather than as a whole missing word — worth a targeted regex pass over the
  finished stems/choices/explanations rather than assuming the general cleanup already
  caught them: `lgA`/`lgG`/`lgM`/`lgE` → `IgA` etc. (capital I misread as lowercase l),
  `C|-` → `Cl-` (lowercase L in "chloride" misread as a pipe), a bare `|t` → `It` at a
  sentence start, a bare `|` standing in for the letter `I` (both as a choice/answer
  letter and mid-word, e.g. "Factor XII|" → "Factor XII"), and a run of digits sometimes
  losing/gaining a leading digit (spot-checked "5-year-old" OCR'ing as "65-year-old",
  and a digit being misread as a similar-looking letter, e.g. "7-year-old" as
  "T-year-old"). A page-image spot-check beats guessing on any of these.
- A lab-table or answer-choice **matrix question** (multiple columns of values per
  lettered choice, e.g. four development-domain ratings per choice, or four electrolyte
  values per choice) reliably breaks the simple `LETTER) text` choice parser, since each
  "choice" is really a row of several short fields rather than one sentence. These need
  a hand-built choice list read straight off the source image — don't trust the
  auto-parse for any item where the choices render as a table in the screenshot.

## Validating the finished file

- No `node`/`npm` in this environment (see above), so skip the `node -e`/`jsdom`
  approach entirely and drive the page in a real browser tab instead — the Browser
  tool's `javascript_tool` can `dispatchEvent(new MouseEvent('click'))` on live DOM
  elements exactly like a jsdom script would, without needing to expose anything past
  the template's IIFE closure (no injected exposer snippet needed — you're driving the
  UI, not reaching into its internal variables).
- Answer every item correctly in one pass (`.answer-row[data-letter="X"]` click, then
  `#btn-next`, repeating with each item's real `correct` letter) and confirm the results
  screen reads 100% / N of N. This is a strong end-to-end check — it round-trips every
  item's `choices` + `correct` field through the app's actual scoring logic, not just a
  Python-side structural check, and will surface a corrupted-choice bug (see above) if
  the `correct` letter's choice text was accidentally overwritten with something else's.
- After scoring, click into Review Test and check `#app` gained the `review-mode` class,
  then jump to each image-bearing item via its `.sidebar-item` (`loadItem` is 0-indexed,
  so sidebar item N is `document.querySelectorAll('.sidebar-item')[N-1]`) and confirm
  `#question-img` has a non-zero `naturalWidth` — a broken/missing image path still
  renders an `<img>` tag, so checking for the element's existence alone isn't enough.
- Click "End Review" and check `localStorage.getItem('nbmeExamState:<filename>')` is now
  set, then reload the same URL and confirm it boots straight into `review-mode` with
  the "End Review" label — this proves the resume-on-reopen path actually round-trips,
  not just that `saveExamState()`/`restoreExamStateIfPresent()` exist in the code.
- **This particular preview/browser tool caches `file://` pages that live outside its
  own project sandbox** — reusing a tab and calling `navigate` to the *same* URL (even
  with different query params or a different hash) can silently re-serve a stale
  snapshot instead of truly reloading and re-running the page's script. Symptoms: a
  URL's query string gets silently dropped, `localStorage` reads back unchanged values
  right after a write that should have altered them, or a `.click()` on a real link
  does nothing. Work around it by opening a **fresh tab** for anything that depends on
  a real reload (a `?reset=1`-style flow, or reopening a file to check restored state),
  and treat one-shot `javascript_tool` calls against the *currently loaded* document as
  the reliable ground truth instead of trusting subsequent `navigate` calls to that
  same file.

## PDF family: born-digital "[wide]" Answers exports (e.g. Surgery 6 - Answers v1 [wide].pdf)

These are landscape, born-digital exports (page size ~3584x1968 pt, real text layer,
one item per page, each page carrying its stem + choices + "Correct Answer" + full
explanation). `extract.py` takes its fast text-layer path on them, but two layout
quirks broke it badly the first time and are now fixed in `extract.py` (2026-07 update;
original saved as `extract.py.orig-backup`). Fingerprint to recognize the family:
`source: text-layer`, page_size ~[3584,1968], `explanations_have_educational_objective:
false`, and a chunk of items going through choice reconstruction.

1. **Two-column choice layout (the dangerous one).** The choice LETTERS render in one
   on-page column and the choice TEXTS in a separate column, so the text layer emits
   `A)\nB)\nC)\n...\n<textA>\n<textB>...`. The old per-line parser paired each bare
   `A)` with nothing and mislabeled the texts, producing a DOUBLED list
   (`A)="A)", B)="<textB>", ... F)="<textA>"...`) that still passed every structural
   check — consecutive letters, answer letter present — so it shipped as a **silent
   false-negative**. On Surgery 6 this hit items 7, 13, 14, 18, 21, 23, 29, 37, 42, 43
   and, combined with quirk 2, wiped items 30/47/48 to empty. Fix: detect a run of >=2
   consecutive bare-letter lines followed by an equal-length text block and zip
   letter[k] <- text[k]. Two new validators (`choice-text-is-bare-letter`,
   `duplicate-choice-text`) now flag the wreckage if the zip ever fails on a new form.

2. **Glued `CorrectAnswer:` (no space).** Some items render the label with no space
   between "Correct" and "Answer". `CORRECT_PAT` required `\s+` and missed it, so the
   answer key was lost AND the explanation boundary was missed (the whole explanation
   glued onto the last choice). Hit Surgery 6 items 8, 15, 30, 34, 47, 50. Fix:
   `Correct\s*Answer:`.

3. **Trailing drawn-rule artifact on a choice** (`...(group A),_~---------------`).
   The long rule pushed the line under the noise-line letter-ratio threshold, so a
   real choice (Surgery 6 item 28's answer E) was discarded as junk. Fix: strip a
   trailing 6+char rule run in `clean_text_layer` before the noise test.

4. **Image detection still misses ~1 in 4.** The connected-component detector silently
   returned [] for item 45's abdominal x-ray (grayscale, right-column). A new
   `image-referenced-but-missing` validator now cross-checks the stem's own "is shown"
   / "photograph" wording against whether anything was actually cropped, so a miss
   shows up in `review.json` instead of being lost. Still verify every cropped image
   against its question by eye.

5. **Lab tables leak into the explanation.** When a lab block sits *after* the choices
   in the source, its values land at the head of the explanation (items 31, 40, 44) or
   inline mid-stem (13, 18, 46). Pair labels to values by position and move them into a
   `[[LAB_TABLE]]`/`labValues` block in the stem; double-check the label count equals
   the value count first (Surgery 6 item 40 is 7-and-7 only if you remember K+).

6. **Three lab-table failure modes that survive a clean read-through** (Pediatrics Form 3
   items 19, the jaundice item / item 43-of-the-PDF, and item 44). All three are now
   caught by `scan_garbling.py` (classes 9-11); the underlying content mistakes to avoid:

   - **Serum/Plasma sub-header merged into an analyte.** A stacked OCR block emits all
     the label lines, then all the value lines. When a bare fluid sub-header ("Serum")
     sits above its indented analytes, there is one MORE label line than value line, so
     naive row-by-row pairing glues the header onto the next analyte — item 19 shipped
     `"Serum urea nitrogen"` as one row with `"Creatinine"` left un-indented. Correct
     shape: a header row `{"label":"Serum","value":""}` followed by the analytes with a
     four-`&nbsp;` indent prefix on their labels (mirrors the `"Urine"` header in item 11).

   - **Rare multi-column (time-series) tables.** The jaundice item's panel is 3 columns
     (label + `At 36 Hours of Age` + `Now`); OCR flattened it to a single stacked list and
     dropped the Hematocrit row's values entirely, so it was rewritten into stem prose and
     never became a table. The chrome now renders multi-column panels: give a row a
     `values: [...]` array instead of `value`, and add a `{"header":true,"label":"","values":[...]}`
     row for the column titles. Recover any OCR-dropped cells from the source page image.

   - **Second panel's data missing.** A two-panel stem (`...show:[[LAB_TABLE]] ... shows:[[LAB_TABLE_2]]`)
     needs BOTH `labValues` and `labValues2`; a missing `labValues2` renders the marker as
     literal `[[LAB_TABLE_2]]` text. Every marker must have its field and vice versa.

**Residual source garbles** (the text layer was OCR'd upstream): `EchocardiograEJhy`,
`AsP,ergilloma`, `exi:iloration`, `Dii:Jhenhydramine`, `Omei:>razole`, `moq:>hine`,
`Fallo!`, `conjunctiva!`, `{Choice`, `lncorrectAnswers`, `AAl\s`, `he arin`, etc. These
are cosmetic (don't affect scoring) but must still be swept by the mandatory garbling
scan on the generated exam before shipping.
