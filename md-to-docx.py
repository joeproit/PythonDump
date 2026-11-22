#!/usr/bin/env python3
"""md-to-docx.py: convert Markdown to .docx with python-docx.

Scenario: keep SOPs, runbooks and policies as markdown in git, then regenerate
          the Word versions in bulk, e.g. when a whole document set is re-issued
          after an owner, header or date change.
Origin:   WDSE IT policy/SOP and governance doc set, April 2026.
Written:  2026-11-21, from that work

Handles headings, paragraphs, bullet and numbered lists (two levels), fenced
code blocks, block quotes, pipe tables, horizontal rules, and inline
**bold**, *italic*, `code` and [links](url).

Numbered items are written as literal "N." text with a hanging indent. Word's
built-in List Number style shares one counter across the whole document, so
separate lists would keep counting from the previous one.

Usage:  md-to-docx.py input.md [-o output.docx] [--font Calibri] [--size 11]
Deps:   pip install python-docx
"""
import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)")
NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)")
FENCE = re.compile(r"^\s*(```|~~~)")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
MONO = "Consolas"


def add_inline(par, text, size=None):
    """Append text to a paragraph, honoring inline markdown."""
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = par.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = par.add_run(part[1:-1])
            run.font.name = MONO
        elif part.startswith("[") and "](" in part:
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", part).groups()
            run = par.add_run(f"{label} ({url})")
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            run = par.add_run(part[1:-1])
            run.italic = True
        else:
            run = par.add_run(part)
        if size:
            run.font.size = Pt(size)


def shade(par, fill="F2F2F2"):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    par._p.get_or_add_pPr().append(shd)


def rule(doc):
    par = doc.add_paragraph()
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, val in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "999999")):
        bottom.set(qn(f"w:{key}"), val)
    border.append(bottom)
    par._p.get_or_add_pPr().append(border)


def add_table(doc, rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not TABLE_SEP.match(r)]
    if not cells:
        return
    width = max(len(r) for r in cells)
    table = doc.add_table(rows=len(cells), cols=width)
    table.style = "Table Grid"
    for i, row in enumerate(cells):
        for j in range(width):
            par = table.cell(i, j).paragraphs[0]
            add_inline(par, row[j] if j < len(row) else "")
            if i == 0:
                for run in par.runs:
                    run.bold = True
    doc.add_paragraph()


def convert(lines, doc):
    i, n = 0, len(lines)
    para = []

    def flush():
        if para:
            add_inline(doc.add_paragraph(), " ".join(s.strip() for s in para))
            para.clear()

    while i < n:
        line = lines[i].rstrip("\n")

        if FENCE.match(line):
            flush()
            marker, block = FENCE.match(line).group(1), []
            i += 1
            while i < n and not lines[i].lstrip().startswith(marker):
                block.append(lines[i].rstrip("\n"))
                i += 1
            par = doc.add_paragraph()
            shade(par)
            run = par.add_run("\n".join(block))
            run.font.name = MONO
            run.font.size = Pt(9)
            i += 1
            continue

        if not line.strip():
            flush()
        elif HEADING.match(line):
            flush()
            level, text = HEADING.match(line).groups()
            add_inline(doc.add_heading("", len(level)), text)
        elif RULE.match(line):
            flush()
            rule(doc)
        elif line.lstrip().startswith("|"):
            flush()
            block = []
            while i < n and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            add_table(doc, block)
            continue
        elif line.lstrip().startswith(">"):
            flush()
            add_inline(doc.add_paragraph(style="Quote"), line.lstrip()[1:].strip())
        elif BULLET.match(line):
            flush()
            indent, text = BULLET.match(line).groups()
            level = 2 if len(indent.replace("\t", "  ")) >= 2 else 1
            style = "List Bullet" if level == 1 else "List Bullet 2"
            add_inline(doc.add_paragraph(style=style), text)
        elif NUMBERED.match(line):
            flush()
            indent, num, text = NUMBERED.match(line).groups()
            level = 1 if len(indent.replace("\t", "  ")) >= 2 else 0
            par = doc.add_paragraph()
            par.paragraph_format.left_indent = Inches(0.25 * (level + 1))
            par.paragraph_format.first_line_indent = Inches(-0.25)
            add_inline(par, f"{num}. {text}")
        else:
            para.append(line)
        i += 1
    flush()


def main():
    ap = argparse.ArgumentParser(description="Convert Markdown to .docx")
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--font", default="Calibri")
    ap.add_argument("--size", type=float, default=11)
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"[ERROR] not found: {args.input}", file=sys.stderr)
        return 2
    out = args.output or args.input.with_suffix(".docx")

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = args.font
    normal.font.size = Pt(args.size)
    normal.font.color.rgb = RGBColor(0, 0, 0)

    convert(args.input.read_text(encoding="utf-8").splitlines(), doc)
    doc.save(out)
    print(f"[INFO] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
