#!/usr/bin/env python3
"""
scan_garbling.py — mandatory post-parse QA scan for OCR'd NBME-style exam data.

Why this exists: text extracted from scanned/OCR'd PDFs (via tesseract, or via a PDF's
own embedded OCR text layer) reliably produces several classes of errors that a syntax
check and a casual read-through both miss:

  1. "Word-soup" garbling — scattered noise tokens dropped into otherwise-correct
     text (background watermark fragments, misread glyphs, stray punctuation runs).
  2. Structural corruption — a duplicate/garbled answer choice glued onto a real one
     (e.g. "Amphotericin B ' legs oo eee", or a whole extra choice "G" that's just a
     mangled copy of choice "C"), missing choices, or choice letters that skip a
     letter (A,B,C,D,E,G instead of A,B,C,D,E,F).
  3. Single-character misreads that hide *inside* an otherwise normal-looking word —
     a stray comma/semicolon/"!"/"/" glued into the middle of a token (no whitespace
     on one or both sides). These are the most dangerous class: the surrounding text
     still reads as fluent medical prose, so a "does this paragraph make sense?" read
     will not catch "AcY,clovir", "brachia! plexus", or "vagina/is" — but a downstream
     reader trying to actually use these answer choices will hit an obvious typo.
  4. Digit-run corruption inside common NBME stem openers — a missing space ("A47-
     year-old") or an extra one splitting a number in half ("A 4 7-year-old").
  5. A single letter standing in for a digit inside anatomical-level notation next to
     "nerve root" (e.g. "CB nerve root" instead of "C8 nerve root") — invisible to a
     dictionary check because the misread token is itself a plausible-looking acronym.
  6. A slash in numeric vital-sign notation misread as a letter/digit, or dropped
     outright — "104lmin"/"20lmin" instead of "104/min"/"20/min" (pulse and
     respirations), and "100162 mm Hg" instead of "100/62 mm Hg" (blood pressure).
     Invisible to every prior check: word_is_suspicious() exempts any token
     containing a digit, and the existing slash-token scan only matches
     word/word tokens, never number/word or number/number.
  7. A vital sign that parses fine syntactically (correct "NN/min" or "NNN/NN mm Hg"
     shape) but is physiologically implausible — e.g. a pulse of 12/min, a systolic
     pressure lower than the diastolic. Catches the specific blind spot called out
     above in the "IMPORTANT" note: a digit silently misread as a different valid
     digit (e.g. "72" -> "12") leaves no structural trace, but if the resulting
     number is outside a living patient's physiologic range (or the two numbers in
     a blood pressure are in the wrong order), that's still catchable — just via
     medical-knowledge plausibility rather than text pattern matching.
  8. A lab/study panel left inline as stem prose instead of being lifted into a
     [[LAB_TABLE]] marker + labValues array (e.g. "Laboratory studies show: Hemoglobin
     11.9 g/dL Leukocyte count 12,200/mm3 ..." run together in the stem). It renders as
     an unbroken paragraph instead of the expected table. Invisible to every other
     check: the flattened text is fluent, all tokens are individually fine, and no
     prior check ever inspected lab panels — the extraction rule lived only as a manual
     note in ocr-exam-build-notes.md.

  9. A [[LAB_TABLE_N]] marker with no populated labValues field (or a labValues
     field with no marker) — the chrome then renders the marker as literal
     "[[LAB_TABLE_2]]" text, or silently never shows a transcribed panel. Class 8
     only ever checked the intro->marker direction, never marker->data.
 10. A section-header fluid ("Serum", "Plasma", ...) glued onto the next analyte
     inside a labValues label ("Serum urea nitrogen") because a stacked OCR block
     had one more label line than value lines. Nothing here inspected labValues
     labels before, so a merged sub-header was invisible.
 11. A whole lab panel flattened into stem prose with the intro COLON removed
     ("...now show a total bilirubin concentration of 8.2 mg/dL...") — the colon
     is class 8's only discriminator, so a reworded intro slips past it entirely.

Classes 9-11 were added after Pediatrics Form 3 shipped three lab-table defects the
earlier checks structurally could not see: item 19 (a "Serum" sub-header merged into
"Urea nitrogen"), the jaundice item (a rare 3-column time-series table dropped and its
values reworded into prose), and a two-panel stem whose second panel's data was never
verified to exist. All three live in labValues content or the marker<->data contract,
which nothing before class 9 ever inspected.

Both classes 1-2 were the original scope of this script. Classes 3-5 were added after
a real build (Internal Medicine Form 6) shipped with seven uncaught instances of class
3 alone — every one of them slipped past the original word-suspicion scan for a
specific, identifiable reason (see comments on each check below). Classes 6-7 were
added after Pediatrics Form 3 shipped with an uncaught glued-slash error in a vital
sign ("100162 mm Hg" for "100/62 mm Hg") that fell into the same kind of gap: numeric
tokens are exempted from the word-suspicion scan entirely, and slash-specific checks
only ever looked at word/word tokens. Class 8 was added after the same form's item 11
shipped with an entire lab panel flattened into stem prose instead of a [[LAB_TABLE]]
table — a rule that had only ever been a manual note, never an automated check. If you are improving this script further because
a NEW garbling shape got through, add a comment here explaining exactly why the
existing checks missed it, the same way the checks below document their own blind
spots — that history is what keeps this scanner improving instead of quietly
regressing.

IMPORTANT — this script narrows the search space, it does not replace it. It cannot
catch every possible OCR error (a digit silently misread as a different valid digit,
e.g. "72" -> "12", produces no structural or lexical anomaly at all and is invisible to
any text-only scan). Treat a clean run as "no *known* garbling patterns found," not as
a proof of correctness — the mandatory step 7/8 spot-check against source page images
for every flagged item (and a periodic broader spot-check of unflagged items) is what
actually closes that gap, not this script by itself.

  - A dictionary-based word-suspicion scan (via pyspellchecker) flags short tokens
    that are neither real English words nor known medical abbreviations.
  - A set of "always real" structural checks catches specific corruption patterns:
    non-sequential choice letters, stems that don't end in "?" or ":", stray "|"
    characters (misread Roman numeral I), stray "!" characters (misread lowercase
    "l"/"i" — NBME stems/explanations never contain a genuine exclamation point, so
    any "!" found anywhere is essentially guaranteed to be a misread letter, not
    punctuation), a comma/semicolon glued into the middle of a word with no
    surrounding whitespace, glued-together choice markers (e.g. "£}", "6}", "DB}"),
    merged words from a missing space ("ofthe", "Apreviously"), split or glued digit
    runs in "A NN-year-old"-style stem openers, a two-uppercase-letter token standing
    directly in front of "nerve root" (spinal levels are letter+digit, e.g. C8/L4/T1/
    S1 — a letter+letter here is a misread digit), and a choice's own text containing
    the literal substring "Choice" (leaked distractor commentary).
  - A separate "review" tier for word/word tokens joined by a slash with no
    surrounding whitespace: most of these are legitimate ("subacute/chronic cough",
    "and/or"), but a rare few are a misread letter standing in for a slash-adjacent
    character ("vagina/is" for "vaginalis"). Unlike the checks above this one can't be
    auto-classified as "always real," so it's reported separately for a quick human
    skim rather than folded into the definite-fix list.
  - Two vital-sign-specific checks scoped to appear right after "pulse"/
    "respirations"/"heart rate"/"RR" or "blood pressure"/"BP": a rate whose slash was
    misread as a letter/digit ("104lmin"), and a blood pressure whose slash was
    misread as a stray character or dropped outright, gluing the two numbers together
    ("100162" for "100/62"). Both are "always real" — correctly formatted vitals never
    match either pattern.
  - A medical-knowledge plausibility check on any vital sign that IS correctly
    slash-formatted: flags a temperature/pulse/respiratory-rate/blood-pressure value
    outside a living patient's physiologic range, or a blood pressure where the
    diastolic number is not lower than the systolic. This is the one check in the
    script that isn't purely a text-pattern match — it's a sanity check grounded in
    what a real vital sign can be.

Usage:
    pip install pyspellchecker --break-system-packages   # one-time, if not installed
    python3 scan_garbling.py questions.json

Input format (produced by extract_questions.js, or write your own): a JSON list of
objects, each shaped:
    {
      "id": "6009" | "s1-item9" | anything stable/printable,
      "stem": "...",
      "choices": [["A", "text"], ["B", "text"], ...]
                 -- OR --
                 [{"letter": "A", "text": "..."}, {"letter": "B", "text": "..."}, ...],
      "explanation": "..."   // optional, empty string if not yet written
    }
`choices` may be either shape — a list of [letter, text] pairs (this script's
original documented shape) or a list of {"letter", "text"} dicts (the shape this
project's own dependencies/content/*.json files actually use). normalize_choices()
converts either into a uniform list of tuples before any check runs; see its
docstring for why this mattered — the dict shape was silently misread by every
choice-aware check until it was added.

Output: a prioritized report to stdout. Structural issues are always shown (they are
never false positives). Word-suspicion hits are ranked by score; skim from the top
until the ratio drops into noise (legitimate items top out around 0.02-0.03 ratio in
practice — see the sample lists of common false positives below before assuming a low
hit is real garbling). Slash-token hits are a third, separate list — skim all of them,
there are normally only a handful per exam.
"""
import sys
import json
import re
import string

try:
    from spellchecker import SpellChecker
    SPELL = SpellChecker()
    HAVE_SPELLCHECKER = True
except ImportError:
    SPELL = None
    HAVE_SPELLCHECKER = False

# Common short medical abbreviations / units that a general English dictionary
# doesn't know, so they'd otherwise all get flagged as "suspicious short words."
# Extend this list if a build's real vocabulary produces new false positives —
# don't loosen the core detection to compensate.
MEDICAL_WHITELIST = set("""
eg ie vs etc iv im po prn stat npo od os ou hs qd bid tid qid gtt
bpm ecg ekg cxr mri ct us hpv hbv hcv hsv cmv ebv rsv dna rna pcr
esr crp ana rf hla abo rh copd chf cad mi dvt pe uti cns pns cva tia
gi gu er icu or nicu picu na cl ca mg alt ast alp inr ptt pt ph
oz lb lbs ft ok hx dx tx rx fx sx px
ig iga igg igm ige igd hr wt ht wk wks mo mos yr yrs
mm cm kg dl ml mcg meq iu spp coli stis utis rbcs wbcs von
""".split())

# word/word slash tokens that are known-legitimate lab/vital-sign unit ratios —
# never worth surfacing even in the review tier. Extend this if a build's real
# vocabulary produces new false positives.
SLASH_UNIT_WHITELIST_RE = re.compile(
    r"^(mg|mcg|ng|g|kg|lb|iu|meq|mmol|mol|u|units?|ml|dl|l|cells|copies|breaths|"
    r"beats|min|hr|hpf|mm3|hr|kcal|cal|wbc|rbc|hb|hgb|hct|plt)\s*/\s*"
    r"(dl|dL|l|L|min|hr|kg|m2|m|hpf|mm3|day|wk|week|cell|cells)$",
    re.IGNORECASE,
)

def strip_punct(word):
    return re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", word)

def is_known_word(lower_word):
    if lower_word in MEDICAL_WHITELIST:
        return True
    if HAVE_SPELLCHECKER:
        return lower_word in SPELL
    return True  # without a dictionary, don't flag anything on this axis

def word_is_suspicious(raw_word):
    core = strip_punct(raw_word)
    if not core:
        return False
    if re.search(r"\d", core):
        return False
    if core.isupper():
        return False  # acronyms
    if len(core) == 1:
        return False
    low = core.lower()
    if core.isalpha() and len(core) <= 4 and not is_known_word(low):
        return True
    if core.isalpha() and len(core) >= 5 and not re.search(r"[aeiouyAEIOUY]", core):
        return True  # long vowel-less token — not a real word in English or Latin-derived medical terms
    return False

def word_suspicion_scan(text):
    words = text.split()
    if not words:
        return 0.0, []
    hits = [w for w in words if word_is_suspicious(w)]
    return len(hits) / max(1, len(words)), hits

MERGED_WORD_RE = re.compile(
    r"\b(ofthe|tothe|isa|isthe|withthe|inthe|forthe|andthe|onthe|fromthe|"
    r"toa|asa|ofa|bythe|thatthe|ofan|witha|toan)\b"
)
GLUED_MARKER_RE = re.compile(r"[£§†‡¥]|(?<=\s)\d\}|(?<=\s)[A-Z]\}")
LEADING_A_MERGE_RE = re.compile(r"^(A[a-z]{3,}(?:-year-old)?)\b")

# --- Checks added after Internal Medicine Form 6 shipped 7 uncaught mid-word
# --- misreads. Each comment explains the specific blind spot in the ORIGINAL
# --- word-suspicion scan that let that exact error through, so the reasoning
# --- doesn't get lost if this script is touched again later.

# "!" standing in for a misread "l"/"i" (e.g. "brachia!" for "brachial",
# "urticaria!" for "urticarial", "mucosa!" for "mucosal"). BLIND SPOT: strip_punct()
# strips a trailing "!" before word_is_suspicious() ever looks at the token, turning
# "brachia!" into "brachia" — which is itself a real word (Latin plural of
# "brachium"), so it sailed past both the dictionary check and the vowel-less check.
# NBME-style stems/choices/explanations never contain a genuine exclamation point, so
# this is a zero-false-positive check: any "!" anywhere is real garbling.
BANG_RE = re.compile(r"!")

# A comma or semicolon glued directly between two letters with no surrounding
# whitespace (e.g. "AcY,clovir", "hyP,oxemia"). BLIND SPOT: word_is_suspicious()
# only evaluates a token once it passes `core.isalpha()`; a token containing an
# internal comma/semicolon fails that check immediately and is never scored at all,
# regardless of how garbled it looks. Requiring letters (not digits) on both sides
# means this never fires on a legitimate numeric separator like "1,000".
MID_WORD_COMMA_RE = re.compile(r"[A-Za-z],[A-Za-z]|[A-Za-z];[A-Za-z]")

# A single uppercase letter standing in for a misread digit in spinal/nerve-root
# notation (e.g. "CB nerve root" for "C8 nerve root"). BLIND SPOT: word_is_suspicious()
# exempts ANY all-uppercase token as a presumed acronym (`core.isupper()`), and "CB"
# is indistinguishable from a real acronym by spelling alone — only the surrounding
# context ("nerve root", where a letter+digit spinal level is anatomically expected)
# reveals it. Scoped tightly to that context to avoid flagging real 2-letter acronyms
# elsewhere (e.g. "TB", "BP") that have nothing to do with nerve levels.
BAD_SPINAL_LEVEL_RE = re.compile(r"\b([A-Z])([A-Z])\b(?=\s+nerve\s+root)")

# A stray space splitting a two-digit number inside a "NN-year-old"-style stem
# opener (e.g. "A 4 7-year-old" for "A 47-year-old"). BLIND SPOT: this isn't a
# malformed *word* at all — "4", "7-year-old" are each individually fine looking
# tokens — so no dictionary-based word check could ever catch it; it needed a
# dedicated numeric-pattern check.
SPLIT_AGE_NUMBER_RE = re.compile(r"\b(\d) (\d+)-(year|month|week|day)s?-old\b")

# The missing-space counterpart (e.g. "A47-year-old" for "A 47-year-old").
# BLIND SPOT: word_is_suspicious() exempts any token containing a digit outright
# (meant to avoid flagging legitimate measurements/lab values), which also silently
# waved through this glued "A" + age merge.
MISSING_SPACE_AGE_RE = re.compile(r"\bA(\d+-(?:year|month|week|day)s?-old)\b")

# A lab/study panel that was left inline as prose in the stem instead of being
# lifted into a [[LAB_TABLE]] marker + labValues array. BLIND SPOT: nothing in this
# scanner ever looked at lab panels at all — the rule ("move a lab block into a
# [[LAB_TABLE]]/labValues block in the stem") lived only in ocr-exam-build-notes.md
# as a manual instruction, so a build that skipped it (Pediatrics Form 3 item 11)
# shipped with the whole panel — "Laboratory studies show: Hemoglobin 11.9 g/dL
# Leukocyte count 12,200/mm3 ..." — flattened into one run of stem prose, which reads
# as fluent text and passes every word/structural check. The reliable signal, verified
# across this exam: NBME writes the panel intro with a COLON ("...studies show:",
# "...analysis ... shows:") ONLY when a table follows, and the correct content always
# places a [[LAB_TABLE]] marker immediately after that colon. A lab-context intro whose
# colon is NOT immediately followed by a [[LAB_TABLE...]] marker is therefore a panel
# that never got extracted. (Genuine inline prose like "Urinalysis shows 4+ protein..."
# has NO colon and so never matches — the colon is the discriminator.)
LAB_PANEL_INTRO_RE = re.compile(
    r"\b(?:laboratory|serum|plasma|blood|urine|urinalysis|cerebrospinal fluid|csf|"
    r"hematologic|coagulation|arterial blood gas|venous blood gas|thyroid function|"
    r"pulmonary function|liver function|iron|lipid|other laboratory)"
    r"[^:.?!]{0,60}?shows?\s*:",
    re.IGNORECASE,
)
LAB_TABLE_MARKER_RE = re.compile(r"\[\[LAB_TABLE(?:_\d+)?\]\]")

# Every [[LAB_TABLE_N]] marker in a stem, with its panel number captured, so a
# check can pair each marker against the labValues field the chrome will look
# for when it renders (panel 1 -> "labValues", panel 2 -> "labValues2", ...).
LAB_TABLE_NUMBERED_RE = re.compile(r"\[\[LAB_TABLE(?:_(\d+))?\]\]")

# Class 9 (marker <-> data consistency). BLIND SPOT this closes: class 8 only
# ever checked that a lab intro's colon is FOLLOWED by a marker. It never checked
# the other half of the chrome's contract — that every marker actually has a
# populated labValues field, and every labValues field has a marker. When they
# don't line up, the chrome (renderStemWithHighlights) leaves the marker as
# literal visible "[[LAB_TABLE_2]]" text in the stem (missing data) or silently
# never renders a panel that was transcribed (orphan data). Pediatrics Form 3
# item 43 (a "Serum studies show:[[LAB_TABLE]] ... Arterial blood gas ...
# shows:[[LAB_TABLE_2]]" two-panel stem) is exactly this shape, and nothing here
# verified the second panel's data existed. This is a deterministic, zero-false-
# positive structural check: it's the chrome's own marker->field mapping, not a
# heuristic. `panelNum -> field name` mirrors chrome_single_block.html exactly.
def _lab_field_for_panel(panel_num):
    return "labValues" if panel_num == 1 else ("labValues" + str(panel_num))

# Class 10 (section-header word glued into an analyte label). BLIND SPOT: a
# stacked lab block that OCR emits as "...label lines... then ...value lines..."
# loses the visual hierarchy the PDF had (a bare "Serum"/"Plasma" SUB-HEADER
# sitting flush-left above its indented analytes). With one more label line than
# value lines, the row-by-row pairing that builds labValues silently glues the
# header onto the next analyte — Pediatrics Form 3 item 19 shipped "Serum urea
# nitrogen" as one row (and left "Creatinine" un-indented) instead of a bare
# "Serum" header with "Urea nitrogen"/"Creatinine" indented beneath it. Nothing
# ever inspected labValues LABELS, so this was invisible. The reliable, low-
# false-positive signal: inside a panel whose fluid is already named by its
# intro ("Serum studies show:"), an individual row never re-states the fluid —
# so a row label that BEGINS with a fluid/section keyword AND carries additional
# analyte words after it (i.e. it's not the bare header itself) is a merged
# header. A bare "Serum" header row (label == the keyword, empty value) is the
# CORRECT shape and is explicitly NOT flagged. "Blood" is deliberately excluded
# from the keyword set because legitimate single labels start with it ("Blood
# urea nitrogen", "Blood glucose"); the fluids kept here are ones that only ever
# appear in these panels as a standalone sub-header.
LAB_SECTION_HEADER_WORDS = ("Serum", "Plasma", "Urine", "Cerebrospinal fluid", "CSF")
_LAB_SECTION_HEADER_RE = re.compile(
    r"^(?:Serum|Plasma|Urine|Cerebrospinal fluid|CSF)\b(?P<rest>.*)$"
)

# Class 11 (a whole lab panel flattened into stem prose with the intro colon
# REMOVED). BLIND SPOT: class 8 keys on the intro colon ("...studies show:") as
# its discriminator, precisely so it won't fire on genuine qualitative inline
# prose ("Urinalysis shows 4+ protein..."). But when the panel can't be turned
# into a table at build time (e.g. Pediatrics Form 3 item 43-of-the-PDF, a rare
# 3-column time-series table OCR mangled), the values can get rewritten INTO the
# intro sentence as flowing prose — "Laboratory studies at 36 hours of age and
# now show a total bilirubin concentration of 8.2 mg/dL..." — which drops the
# colon and so slips under class 8 entirely. Signal used here (kept specific to
# avoid re-flagging legit single-value prose): a lab-panel intro keyword whose
# stem has NO lab-table marker AT ALL, yet contains two or more quantitative
# unit-bearing values — a lab panel never rendered as a table.
LAB_INTRO_KEYWORD_RE = re.compile(
    r"\b(?:laboratory studies|serum studies|plasma studies|blood studies|"
    r"arterial blood gas analysis|venous blood gas analysis|coagulation studies|"
    r"laboratory studies at)\b[^.?!]{0,80}?\bshows?\b",
    re.IGNORECASE,
)
LAB_UNIT_VALUE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*"
    r"(?:mg/dL|mg/dl|mEq/L|g/dL|g/dl|ng/mL|ng/dl|µg/dL|mcg/dL|U/L|IU/L|"
    r"/mm3|mm\s*Hg|mOsm(?:/kg)?)",
    re.IGNORECASE,
)

# A slash in "NN/min"-style vital-sign rate notation (pulse, respirations) misread
# as a letter "l"/"I" or digit "1" and glued directly onto the unit (e.g. "104lmin"
# for "104/min", "20lmin" for "20/min"). BLIND SPOT: word_is_suspicious() exempts
# ANY token containing a digit outright (to avoid flagging real measurements), so a
# malformed token like "104lmin" was never even scored; the existing slash-token
# checks (SLASH_TOKEN_RE, SLASH_UNIT_WHITELIST_RE) only match word/word tokens
# ([A-Za-z]/[A-Za-z]) and never look at number/word combinations at all. Scoped to
# directly follow a rate keyword so it can't misfire on an unrelated "104l..." token.
VITAL_RATE_CONTEXT_RE = re.compile(
    r"\b(?:pulse|respirations?|heart rate|RR)\s+(?:is|are|was|were)?\s*"
    r"(\d{1,3})\s*[lI1](?:min|hr|sec|hour)\b",
    re.IGNORECASE,
)

# The blood-pressure counterpart: a slash between systolic and diastolic misread as
# a stray letter/digit ("100" + "1" + "62" -> "100162" for "100/62"), or dropped
# outright with the two numbers concatenated into one run and no separator at all.
# Same blind spot as VITAL_RATE_CONTEXT_RE — numeric tokens are invisible to the
# word-suspicion scan, and no prior check looked at number/number notation. Both are
# scoped to follow "blood pressure"/"BP" so a coincidental digit run elsewhere
# (a lab value, a page number) can never trigger them.
_BP_CONTEXT = r"\b(?:blood pressure|BP)\s+(?:is|are|was|were|of)?\s*"
GLUED_BP_STRAY_CHAR_RE = re.compile(
    _BP_CONTEXT + r"(\d{2,3})[lI1](\d{2,3})\s*mm\s*/?\s*Hg", re.IGNORECASE,
)
GLUED_BP_NOSEP_RE = re.compile(
    _BP_CONTEXT + r"(\d{4,6})\s*mm\s*/?\s*Hg", re.IGNORECASE,
)

def suggest_bp_split(digits):
    """Given a glued blood-pressure digit run with no stray separator character
    (e.g. '10062'), try every split point and return the first one where both
    halves fall in a physiologically plausible range (systolic 70-260, diastolic
    30-150, systolic > diastolic). Returns None if no split looks plausible —
    the item is still flagged, just without a concrete suggested fix."""
    for i in range(2, len(digits) - 1):
        sys_part, dia_part = digits[:i], digits[i:]
        if len(sys_part) > 3 or len(dia_part) > 3:
            continue
        sys_val, dia_val = int(sys_part), int(dia_part)
        if 70 <= sys_val <= 260 and 30 <= dia_val <= 150 and sys_val > dia_val:
            return f"{sys_val}/{dia_val}"
    return None

# Medical-knowledge plausibility check (class 7, see module docstring): once a
# vital sign IS correctly slash-formatted, verify the value itself is something a
# living patient could actually have. This is the one check here that isn't a text
# pattern — the point is to catch digit-for-digit OCR misreads (e.g. "72" -> "12")
# that leave no textual trace at all and so are invisible to every other check in
# this file, per the "IMPORTANT" caveat in the module docstring.
TEMP_C_RE = re.compile(r"temperature is (\d{1,3}(?:\.\d)?)\s*°?\s*C", re.IGNORECASE)
PULSE_RE = re.compile(r"pulse is (\d{1,3})\s*/\s*min", re.IGNORECASE)
RESP_RE = re.compile(r"respirations? (?:are|is) (\d{1,3})\s*/\s*min", re.IGNORECASE)
BP_VALID_RE = re.compile(r"blood pressure is (\d{2,3})\s*/\s*(\d{2,3})\s*mm\s*Hg", re.IGNORECASE)

def vital_plausibility_checks(full_text):
    issues = []
    m = TEMP_C_RE.search(full_text)
    if m:
        val = float(m.group(1))
        if not (34.0 <= val <= 42.5):
            issues.append(f"implausible temperature: {val}°C (physiologic range ~34-42.5°C) — check for a digit misread")
    m = PULSE_RE.search(full_text)
    if m:
        val = int(m.group(1))
        if not (25 <= val <= 240):
            issues.append(f"implausible pulse: {val}/min (physiologic range ~25-240/min) — check for a digit misread")
    m = RESP_RE.search(full_text)
    if m:
        val = int(m.group(1))
        if not (5 <= val <= 80):
            issues.append(f"implausible respiratory rate: {val}/min (physiologic range ~5-80/min) — check for a digit misread")
    m = BP_VALID_RE.search(full_text)
    if m:
        sys_val, dia_val = int(m.group(1)), int(m.group(2))
        if not (60 <= sys_val <= 300):
            issues.append(f"implausible systolic blood pressure: {sys_val} mm Hg (physiologic range ~60-300) — check for a digit misread")
        if not (20 <= dia_val <= 180):
            issues.append(f"implausible diastolic blood pressure: {dia_val} mm Hg (physiologic range ~20-180) — check for a digit misread")
        if dia_val >= sys_val:
            issues.append(f"diastolic ({dia_val}) is not lower than systolic ({sys_val}) mm Hg — physiologically implausible, check for a digit or order error")
    return issues

def normalize_choices(choices):
    """Accepts `choices` in either shape this project's data actually comes in — a
    list of [letter, text] pairs (this script's originally documented shape) or a
    list of {"letter": ..., "text": ...} dicts (the shape dependencies/content/*.json
    really uses) — and returns a uniform list of (letter, text) tuples so every
    check below can stay agnostic to which one the caller passed.

    BLIND SPOT this fixes: a 2-key dict is itself iterable, so the old
    `for l, t in choices` line didn't error on a dict-shaped choice — it silently
    unpacked each {"letter": "A", "text": "Cefazolin"} dict's KEYS instead of its
    values, giving l="letter" and t="text" for literally every choice in every
    item. That's why "non-sequential choice letters" fired on all 49 items of
    Pediatrics Form 3 (every `letters` list came out as ['letter','letter',...])
    while producing zero real signal — the actual corruption checks this was
    meant to catch were never running against this project's real content shape
    at all, just against a constant self-inflicted false positive.
    """
    normalized = []
    for c in choices:
        if isinstance(c, dict):
            normalized.append((c.get("letter", ""), c.get("text", "")))
        elif isinstance(c, (list, tuple)) and len(c) == 2:
            normalized.append((c[0], c[1]))
        else:
            # Unknown per-choice shape — don't let one bad entry crash the whole
            # scan; fold it in as an empty pair so it still surfaces (as a
            # letter-sequence/blank-text mismatch) instead of vanishing silently.
            normalized.append(("", ""))
    return normalized

def structural_checks(item):
    issues = []
    stem = item.get("stem", "") or ""
    choices = normalize_choices(item.get("choices", []) or [])
    explanation = item.get("explanation", "") or ""
    full_text = stem + " " + " ".join(t for _, t in choices) + " " + explanation

    stripped_stem = stem.strip()
    if stripped_stem and not stripped_stem.endswith("?") and not stripped_stem.endswith(":"):
        issues.append(f"stem does not end in '?' or ':' (possible truncation) — ends: ...{stripped_stem[-40:]!r}")

    if "|" in full_text:
        idx = full_text.find("|")
        issues.append(f"stray '|' character (usually a misread Roman numeral I) near: ...{full_text[max(0,idx-30):idx+30]!r}...")

    m = BANG_RE.search(full_text)
    if m:
        idx = m.start()
        issues.append(f"stray '!' character (usually a misread 'l'/'i' — this text style never has real exclamation points) near: ...{full_text[max(0,idx-20):idx+20]!r}...")

    m = MID_WORD_COMMA_RE.search(full_text)
    if m:
        idx = m.start()
        issues.append(f"comma/semicolon glued into the middle of a word near: ...{full_text[max(0,idx-20):idx+20]!r}...")

    m = GLUED_MARKER_RE.search(full_text)
    if m:
        idx = m.start()
        issues.append(f"glued-choice marker '{m.group()}' near: ...{full_text[max(0,idx-30):idx+30]!r}...")

    m = MERGED_WORD_RE.search(full_text)
    if m:
        issues.append(f"merged word (missing space) found: {m.group()!r}")

    m = SPLIT_AGE_NUMBER_RE.search(full_text)
    if m:
        issues.append(f"stray space splitting an age number: {m.group()!r} (likely should be {m.group(1)}{m.group(2)}-{m.group(3)}-old)")

    m = MISSING_SPACE_AGE_RE.search(full_text)
    if m:
        issues.append(f"missing space before an age number: {m.group()!r}")

    m = BAD_SPINAL_LEVEL_RE.search(full_text)
    if m:
        idx = m.start()
        issues.append(f"letter-letter token directly before 'nerve root' (spinal levels are letter+digit, e.g. C8/L4/T1/S1) near: ...{full_text[max(0,idx-20):idx+30]!r}...")

    for m in VITAL_RATE_CONTEXT_RE.finditer(full_text):
        idx = m.start()
        issues.append(
            f"vital-sign rate missing its slash (likely misread as 'l'/'I'/'1'): "
            f"{m.group()!r} — should read {m.group(1)!r} + '/min' (or /hr) near: "
            f"...{full_text[max(0,idx-20):idx+40]!r}..."
        )

    m = GLUED_BP_STRAY_CHAR_RE.search(full_text)
    if m:
        idx = m.start()
        issues.append(
            f"blood pressure missing its slash (likely misread as 'l'/'I'/'1'): "
            f"{m.group()!r} — should read '{m.group(1)}/{m.group(2)} mm Hg' near: "
            f"...{full_text[max(0,idx-20):idx+40]!r}..."
        )
    else:
        m = GLUED_BP_NOSEP_RE.search(full_text)
        if m:
            idx = m.start()
            digits = m.group(1)
            suggestion = suggest_bp_split(digits)
            issues.append(
                f"blood pressure digits glued together with no slash: {digits!r}"
                + (f" — likely '{suggestion} mm Hg'" if suggestion else " (no plausible split found, check source image)")
                + f" near: ...{full_text[max(0,idx-20):idx+40]!r}..."
            )

    issues.extend(vital_plausibility_checks(full_text))

    # Lab panel left inline instead of extracted to a [[LAB_TABLE]] marker. Scoped to
    # the stem, since that's the only field the marker/labValues mechanism populates.
    for m in LAB_PANEL_INTRO_RE.finditer(stem):
        after = stem[m.end():]
        if not LAB_TABLE_MARKER_RE.match(after.lstrip()):
            idx = m.start()
            issues.append(
                f"lab/study panel intro ends in ':' but is NOT followed by a "
                f"[[LAB_TABLE]] marker — the panel values look left inline in the stem "
                f"instead of extracted into a labValues table (see ocr-exam-build-notes.md, "
                f"'Lab tables leak into the explanation'): intro {m.group().strip()!r}, "
                f"then: ...{after[:60]!r}..."
            )

    # Class 9: every [[LAB_TABLE_N]] marker must have populated data, and every
    # labValues* field must have a marker. Deterministic — this is the chrome's
    # own marker->field contract, so any mismatch is a real render bug.
    markers_present = {}  # panel_num -> field name
    for m in LAB_TABLE_NUMBERED_RE.finditer(stem):
        panel_num = int(m.group(1)) if m.group(1) else 1
        markers_present[panel_num] = _lab_field_for_panel(panel_num)
    for panel_num, field in sorted(markers_present.items()):
        data = item.get(field)
        if not (isinstance(data, list) and len(data) > 0):
            issues.append(
                f"[[LAB_TABLE{'' if panel_num == 1 else '_' + str(panel_num)}]] marker in "
                f"the stem has no populated {field!r} array — the chrome renders the marker as "
                f"literal '[[LAB_TABLE...]]' text instead of a table (missing/empty panel data)."
            )
    for field in list(item.keys()):
        if field == "labValues" or (field.startswith("labValues") and field[len("labValues"):].isdigit()):
            data = item.get(field)
            if not (isinstance(data, list) and len(data) > 0):
                continue
            panel_num = 1 if field == "labValues" else int(field[len("labValues"):])
            if panel_num not in markers_present:
                marker = "[[LAB_TABLE]]" if panel_num == 1 else f"[[LAB_TABLE_{panel_num}]]"
                issues.append(
                    f"{field!r} has data but the stem has no matching {marker} marker — the panel "
                    f"is never rendered (orphan lab data). Add the marker where the table should appear."
                )

    # Class 10: a section-header fluid glued onto an analyte inside a labValues
    # label (e.g. "Serum urea nitrogen"). A bare header row (label == the fluid,
    # empty value) is correct and NOT flagged.
    for field in list(item.keys()):
        if field != "labValues" and not (field.startswith("labValues") and field[len("labValues"):].isdigit()):
            continue
        rows = item.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = (row.get("label") or "").replace(" ", " ").strip()
            hm = _LAB_SECTION_HEADER_RE.match(label)
            if hm and hm.group("rest").strip():
                issues.append(
                    f"{field!r} row label {label!r} begins with a section-header fluid "
                    f"({label.split()[0]!r}) but carries an analyte after it — a bare "
                    f"'{label.split()[0]}' sub-header likely got glued onto the next analyte "
                    f"(should be a header row with empty value, then the analyte indented beneath). "
                    f"See ocr-exam-build-notes.md, 'Serum/Plasma sub-header merged into an analyte'."
                )

    # Class 11: a lab panel flattened into stem prose with the intro colon removed
    # (so class 8 can't see it) — a lab intro + no marker anywhere + two or more
    # quantitative unit-bearing values.
    if not LAB_TABLE_MARKER_RE.search(stem) and LAB_INTRO_KEYWORD_RE.search(stem):
        unit_hits = LAB_UNIT_VALUE_RE.findall(stem)
        if len(unit_hits) >= 2:
            im = LAB_INTRO_KEYWORD_RE.search(stem)
            idx = im.start()
            issues.append(
                f"lab-panel intro {im.group().strip()!r} appears with NO [[LAB_TABLE]] marker in "
                f"the stem, yet the stem carries {len(unit_hits)} inline unit-bearing values — a lab "
                f"panel was probably flattened into prose instead of built as a labValues table "
                f"(this is the colon-removed variant class 8's colon check can't catch) near: "
                f"...{stem[max(0,idx-10):idx+80]!r}..."
            )

    m = LEADING_A_MERGE_RE.match(stripped_stem)
    if m and not re.match(r"^A\s", stripped_stem) and m.group(1) not in ("A",):
        # crude check: "Apreviously", "Astudy", "Arandomized" etc. — a capital A directly
        # glued to a lowercase word with no space, at the very start of the stem
        first_word = stripped_stem.split(" ", 1)[0]
        if re.match(r"^A[a-z]{3,}$", first_word) and first_word.lower() not in ("a",):
            issues.append(f"possible missing space after leading 'A': {first_word!r}")

    letters = [l for l, t in choices]
    expected = list(string.ascii_uppercase)[:len(letters)]
    if letters != expected:
        issues.append(f"non-sequential choice letters: {letters} (expected {expected})")

    for l, t in choices:
        if "Choice" in t:
            issues.append(f"choice {l} text itself contains the word 'Choice' (leaked distractor commentary): {t!r}")

    return issues

# word/word (or word/word/word) tokens joined by a slash with no surrounding
# whitespace. Most are legitimate medical shorthand ("and/or", "subacute/chronic",
# "hypovolemic/hemorrhagic") so this is NOT folded into the "always real" structural
# list — it's a short, separate review list. Known unit ratios (mg/dL, mEq/L, etc.)
# are excluded via SLASH_UNIT_WHITELIST_RE since those are never worth a human look.
SLASH_TOKEN_RE = re.compile(r"\b[A-Za-z]{2,}(?:/[A-Za-z]{2,}){1,2}\b")

def slash_token_scan(full_text):
    hits = []
    for m in SLASH_TOKEN_RE.finditer(full_text):
        token = m.group()
        if SLASH_UNIT_WHITELIST_RE.match(token):
            continue
        idx = m.start()
        hits.append((token, full_text[max(0, idx - 25):idx + len(token) + 25]))
    return hits

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 scan_garbling.py questions.json", file=sys.stderr)
        sys.exit(1)

    if not HAVE_SPELLCHECKER:
        print("NOTE: pyspellchecker is not installed — word-level suspicion scoring is",
              file=sys.stderr)
        print("disabled for this run (structural checks still run in full). Install it",
              file=sys.stderr)
        print("with: pip install pyspellchecker --break-system-packages\n", file=sys.stderr)

    with open(sys.argv[1], encoding="utf-8") as f:
        items = json.load(f)

    structural_hits = []
    word_hits = []
    slash_hits = []

    for item in items:
        item_id = item.get("id", "?")
        issues = structural_checks(item)
        if issues:
            structural_hits.append((item_id, issues))

        stem = item.get("stem", "") or ""
        choices = normalize_choices(item.get("choices", []) or [])
        explanation = item.get("explanation", "") or ""
        full_text = stem + " " + " ".join(t for _, t in choices) + " " + explanation
        ratio, hits = word_suspicion_scan(full_text)
        if hits:
            word_hits.append((ratio, item_id, len(hits), hits))

        s_hits = slash_token_scan(full_text)
        if s_hits:
            slash_hits.append((item_id, s_hits))

    print("=" * 70)
    print(f"STRUCTURAL ISSUES ({len(structural_hits)} item(s)) — always real, fix every one")
    print("=" * 70)
    if not structural_hits:
        print("(none found)")
    for item_id, issues in structural_hits:
        print(f"\nitem {item_id}:")
        for issue in issues:
            print(f"  - {issue}")

    print()
    print("=" * 70)
    print(f"WORD-SUSPICION SCAN ({len(word_hits)} item(s) with >=1 hit) — ranked, skim from top")
    print("=" * 70)
    word_hits.sort(reverse=True)
    for ratio, item_id, n, hits in word_hits[:60]:
        print(f"{ratio:.3f}  item {item_id}  n_sus={n}  sample={hits[:12]}")

    print()
    print("=" * 70)
    print(f"SLASH-JOINED TOKENS ({sum(len(h) for _, h in slash_hits)} hit(s) in {len(slash_hits)} item(s)) — review each, most are legitimate")
    print("=" * 70)
    if not slash_hits:
        print("(none found)")
    for item_id, hits in slash_hits:
        for token, context in hits:
            print(f"item {item_id}  {token!r}  ...{context!r}...")

    total_flagged = len(structural_hits) + len([h for h in word_hits if h[0] >= 0.02])
    print()
    print("=" * 70)
    print(f"SUMMARY: {len(structural_hits)} structural issue(s), "
          f"{len([h for h in word_hits if h[0] >= 0.02])} item(s) above the 0.02 word-suspicion "
          f"threshold, {sum(len(h) for _, h in slash_hits)} slash-token hit(s) to review.")
    print("Next step: for each flagged item, view the corresponding source page image")
    print("(Read tool) and cross-check/fix the stem, choices, and explanation directly")
    print("in the exam's question data. Re-run this script until structural issues are")
    print("zero, remaining word-suspicion hits are confirmed false positives (legit")
    print("medical abbreviations, not garbling), and every slash-token hit has been")
    print("looked at. A clean run means no *known* garbling pattern was found — it is")
    print("not a substitute for spot-checking flagged items against the source page")
    print("images, since some OCR errors (e.g. one valid digit misread as another)")
    print("leave no textual trace at all.")
    print("=" * 70)

if __name__ == "__main__":
    main()
