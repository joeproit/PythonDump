#!/usr/bin/env python3
"""site-watch.py: detect text changes on a web page and print a unified diff.

Scenario: watch vendor pricing and terms pages, firmware release notes, status
          pages or agency notices without checking by hand. Cron it, alert on
          exit code 1.
Origin:   Cyguin "website change monitor" product concept, 2026.
Written:  2026-11-21

The first run saves a baseline. Later runs compare the page's visible text to
the last snapshot. Exit codes: 0 unchanged or baseline saved, 1 changed,
2 fetch error. That makes it usable from cron, CI or a shell loop.

  site-watch.py https://example.com/pricing
  site-watch.py https://example.com/status --ignore '^Last updated' --ignore '\\d{2}:\\d{2}'
  site-watch.py https://example.com/terms --keep-baseline

--ignore REGEX drops any line matching the pattern (timestamps, counters,
rotating banners). With --keep-baseline the stored snapshot is not replaced,
so every run diffs against the original. State lives in
~/.site-watch/<hash of url>.json (override with --state-dir).

Deps: none (stdlib only).
"""
import argparse
import difflib
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

SKIP = {"script", "style", "noscript", "template", "svg", "head"}
BREAK = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article",
         "header", "footer", "nav", "main", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
MAX_BYTES = 5_000_000


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip_depth += 1
        elif tag in BREAK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "site-watch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def normalize(html, ignore):
    parser = TextExtractor()
    parser.feed(html)
    parser.close()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in "".join(parser.parts).splitlines()]
    return [ln for ln in lines if ln and not any(rx.search(ln) for rx in ignore)]


def main():
    ap = argparse.ArgumentParser(description="Diff a web page against its last snapshot")
    ap.add_argument("url")
    ap.add_argument("--ignore", action="append", default=[], metavar="REGEX")
    ap.add_argument("--state-dir", type=Path, default=Path.home() / ".site-watch")
    ap.add_argument("--timeout", type=float, default=20)
    ap.add_argument("--keep-baseline", action="store_true")
    args = ap.parse_args()

    try:
        ignore = [re.compile(p) for p in args.ignore]
    except re.error as exc:
        print(f"[ERROR] bad --ignore pattern: {exc}", file=sys.stderr)
        return 2

    try:
        lines = normalize(fetch(args.url, args.timeout), ignore)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[ERROR] fetch failed: {exc}", file=sys.stderr)
        return 2

    args.state_dir.mkdir(parents=True, exist_ok=True)
    state_file = args.state_dir / (hashlib.sha1(args.url.encode()).hexdigest()[:16] + ".json")
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    snapshot = {"url": args.url, "checked": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "sha256": digest, "lines": lines}

    if not state_file.exists():
        state_file.write_text(json.dumps(snapshot, indent=1))
        print(f"[INFO] baseline saved ({len(lines)} lines): {state_file}")
        return 0

    old = json.loads(state_file.read_text())
    if old["sha256"] == digest:
        print(f"[INFO] unchanged since {old['checked']}")
        return 0

    print(f"[CHANGED] {args.url} (previous check {old['checked']})")
    for ln in difflib.unified_diff(old["lines"], lines, "previous", "current", lineterm="", n=2):
        print(ln)
    if not args.keep_baseline:
        state_file.write_text(json.dumps(snapshot, indent=1))
    return 1


if __name__ == "__main__":
    sys.exit(main())
