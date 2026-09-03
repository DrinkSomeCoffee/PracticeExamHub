#!/usr/bin/env python3
"""
generate_exam.py — merge a canonical "chrome" template with a per-exam
"content" JSON file into one self-contained, static exam HTML file.

The output is byte-for-byte the same kind of file the NBME exam builders
have always produced (single self-contained HTML, no shared JS/CSS, no
runtime build step) — this script only runs at authoring time, on my/your
machine, to avoid hand-copying the chrome into every exam file and hand-
patching every one of them again whenever the chrome changes.

Usage:
    python3 generate_exam.py <chrome.html> <content.json> <output.html>

Content JSON shape — single-block exam (has "questions"):
    {
      "subject": "Pediatrics",
      "form": "Form 3",
      "pageTitle": "Pediatrics Form 3 - NBME Practice Exam",
      "questionCount": 49,
      "questions": [ { "id":1, "correct":"B", "stem":"...", "choices":[...],
                       "explanation":"...", "image":"assets/item1_x.jpg" }, ... ]
    }

Content JSON shape — 4-block exam (has "blocks"):
    {
      "subject": "NBME Step 2 CK",
      "form": "Form 13",
      "pageTitle": "NBME Step 2 Form 13",
      "itemsPerBlock": 50,
      "numBlocks": 4,
      "blocks": { "1": [ ...50 items... ], "2": [...], "3": [...], "4": [...] }
    }

The chrome file must contain the sentinel comment pairs this script looks
for (CONTENT:TITLE, CONTENT:QUESTIONS or CONTENT:BLOCK_QUESTIONS,
CONTENT:SUBJECT) — both bundled chrome files already have them. Don't
remove the sentinels from a chrome file; the generator can't find its
insertion points without them.
"""

import json
import re
import sys


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def replace_between(src, start_marker, end_marker, new_inner, label):
    pattern = re.compile(
        re.escape(start_marker) + r".*?" + re.escape(end_marker), re.S
    )
    matches = pattern.findall(src)
    if len(matches) != 1:
        die(f"expected exactly 1 '{label}' sentinel block, found {len(matches)}")
    return pattern.sub(lambda m: new_inner, src, count=1)


def js_string(s):
    return json.dumps(s)


def generate(chrome_path, content_path, output_path):
    with open(chrome_path, encoding="utf-8") as f:
        chrome = f.read()
    with open(content_path, encoding="utf-8") as f:
        content = json.load(f)

    subject = content["subject"]
    page_title = content.get("pageTitle") or f"{subject} - NBME Practice Exam"
    is_4block = "blocks" in content

    # 1. Title
    chrome = replace_between(
        chrome,
        "<!-- CONTENT:TITLE:START -->",
        "<!-- CONTENT:TITLE:END -->",
        f"<!-- CONTENT:TITLE:START -->\n<title>{page_title}</title>\n<!-- CONTENT:TITLE:END -->",
        "TITLE",
    )

    # 2. Subject
    chrome = replace_between(
        chrome,
        "// === CONTENT:SUBJECT:START ===",
        "// === CONTENT:SUBJECT:END ===",
        "// === CONTENT:SUBJECT:START ===\n"
        f"  const SUBJECT = {js_string(subject)};\n"
        "  // === CONTENT:SUBJECT:END ===",
        "SUBJECT",
    )

    # 3. Questions / Block questions
    if is_4block:
        blocks = content["blocks"]
        for key in ("1", "2", "3", "4"):
            if key not in blocks:
                die(f"content file is missing block '{key}'")
        items_per_block = content.get("itemsPerBlock", len(blocks["1"]))
        for key, items in blocks.items():
            if len(items) != items_per_block:
                die(
                    f"block {key} has {len(items)} items, expected {items_per_block}"
                )
        block_json = json.dumps(blocks, indent=2, ensure_ascii=False)
        chrome = replace_between(
            chrome,
            "// === CONTENT:BLOCK_QUESTIONS:START ===",
            "// === CONTENT:BLOCK_QUESTIONS:END ===",
            "// === CONTENT:BLOCK_QUESTIONS:START ===\n"
            f"  const BLOCK_QUESTIONS = {block_json};\n"
            "  // === CONTENT:BLOCK_QUESTIONS:END ===",
            "BLOCK_QUESTIONS",
        )
    else:
        questions = content["questions"]
        expected_count = content.get("questionCount", len(questions))
        if len(questions) != expected_count:
            die(
                f"content file declares questionCount={expected_count} but "
                f"has {len(questions)} questions"
            )
        questions_json = json.dumps(questions, indent=2, ensure_ascii=False)
        chrome = replace_between(
            chrome,
            "// === CONTENT:QUESTIONS:START ===",
            "// === CONTENT:QUESTIONS:END ===",
            "// === CONTENT:QUESTIONS:START ===\n"
            f"  const QUESTIONS = {questions_json};\n"
            "  // === CONTENT:QUESTIONS:END ===",
            "QUESTIONS",
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(chrome)
    print(f"Generated: {output_path}")


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    generate(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
