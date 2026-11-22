#!/usr/bin/env python3
"""asterisk-cdr-summary.py: summarize an Asterisk / FreePBX / PBXact CDR export.

Scenario: after a pledge drive, on-air event or outage, answer "how many calls
          did we get, did we drop any, do we need more trunks?" from the CDR.
          Gives totals by disposition, calls per day and hour, peak concurrent
          calls, and (with --trunks N) how long every trunk was busy.
Origin:   WDSE IT, PBXact phone system, 2026. Written 2026-11-21.

Input is Master.csv (no header, Asterisk cdr_csv column order) or an export
with a header row (FreePBX CDR Reports / mysql dump of asteriskcdrdb.cdr; needs
calldate or start, plus duration, billsec, disposition).

CDR rows are call legs. A call that rings a group or crosses a trunk and an
extension produces several rows, so peak concurrency counted over every row
overstates trunk use. Use --channel-match to count only trunk legs:

  asterisk-cdr-summary.py Master.csv
  asterisk-cdr-summary.py cdr.csv --since 2026-03-20 --until 2026-03-22 \\
      --channel-match 'PJSIP/(provider1|provider2)' --trunks 23 --answered-only

Deps: none (stdlib only).
"""
import argparse
import csv
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

MASTER = ["accountcode", "src", "dst", "dcontext", "clid", "channel", "dstchannel", "lastapp",
          "lastdata", "start", "answer", "end", "duration", "billsec", "disposition", "amaflags",
          "uniqueid", "userfield"]
FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
HEADER_HINTS = {"calldate", "start", "disposition", "billsec"}


def parse_ts(text):
    text = (text or "").strip()
    for fmt in FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def to_int(text):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def read_rows(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        first = next(csv.reader([fh.readline()]), [])
        fh.seek(0)
        if any(c.strip().lower() in HEADER_HINTS for c in first):
            for row in csv.DictReader(fh):
                yield {(k or "").strip().lower(): v for k, v in row.items()}
        else:
            for row in csv.reader(fh):
                yield dict(zip(MASTER, row))


def load_calls(path, since, until):
    calls, skipped = [], 0
    for row in read_rows(path):
        start = parse_ts(row.get("start") or row.get("calldate"))
        if start is None:
            skipped += 1
            continue
        if (since and start < since) or (until and start >= until):
            continue
        duration, billsec = to_int(row.get("duration")), to_int(row.get("billsec"))
        end = parse_ts(row.get("end")) or start + timedelta(seconds=duration)
        calls.append({
            "start": start, "end": end, "billsec": billsec,
            "disposition": (row.get("disposition") or "UNKNOWN").strip().upper(),
            "src": (row.get("src") or "").strip(), "dst": (row.get("dst") or "").strip(),
            "chan": f"{row.get('channel') or ''} {row.get('dstchannel') or ''}",
        })
    return calls, skipped


def concurrency(calls, trunks):
    """Sweep line over call intervals. Returns (peak, peak_time, seconds_at_or_above_trunks)."""
    events = []
    for c in calls:
        if c["end"] > c["start"]:
            events += [(c["start"], 1), (c["end"], -1)]
    events.sort(key=lambda e: (e[0], e[1]))  # ends sort before starts at the same instant
    level = peak = 0
    peak_at = prev = None
    saturated = 0.0
    for when, delta in events:
        if prev is not None and trunks and level >= trunks:
            saturated += (when - prev).total_seconds()
        level += delta
        if level > peak:
            peak, peak_at = level, when
        prev = when
    return peak, peak_at, saturated


def bar(count, top, width=40):
    return "#" * (round(width * count / top) if top else 0)


def main():
    ap = argparse.ArgumentParser(description="Summarize an Asterisk CDR export")
    ap.add_argument("csv")
    ap.add_argument("--since", help="YYYY-MM-DD[ HH:MM[:SS]] inclusive")
    ap.add_argument("--until", help="YYYY-MM-DD[ HH:MM[:SS]] exclusive")
    ap.add_argument("--channel-match", metavar="REGEX",
                    help="only count legs whose channel/dstchannel matches (e.g. your trunk names)")
    ap.add_argument("--answered-only", action="store_true", help="concurrency counts ANSWERED legs only")
    ap.add_argument("--trunks", type=int, help="trunk/channel limit; report time spent at or above it")
    ap.add_argument("--short", type=int, default=5, help="answered calls under N billsec count as short")
    args = ap.parse_args()

    since, until = parse_ts(args.since), parse_ts(args.until)
    if (args.since and not since) or (args.until and not until):
        print("[ERROR] bad --since/--until, use YYYY-MM-DD[ HH:MM[:SS]]", file=sys.stderr)
        return 2
    try:
        calls, skipped = load_calls(args.csv, since, until)
        pattern = re.compile(args.channel_match) if args.channel_match else None
    except (OSError, re.error) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if pattern:
        calls = [c for c in calls if pattern.search(c["chan"])]
    if not calls:
        print("[WARN] no CDR rows in range" + (f" ({skipped} unparseable)" if skipped else ""))
        return 1

    first, last = min(c["start"] for c in calls), max(c["end"] for c in calls)
    print(f"Rows: {len(calls)}  ({first:%Y-%m-%d %H:%M} to {last:%Y-%m-%d %H:%M})"
          + (f"  [{skipped} unparseable rows skipped]" if skipped else ""))

    print("\nDisposition")
    dispo = Counter(c["disposition"] for c in calls)
    for name, n in dispo.most_common():
        print(f"  {name:<14}{n:>7}  {100 * n / len(calls):5.1f}%")

    print("\nPer day (answered / total)")
    per_day, per_day_ans = Counter(), Counter()
    for c in calls:
        per_day[c["start"].date()] += 1
        per_day_ans[c["start"].date()] += c["disposition"] == "ANSWERED"
    for day in sorted(per_day):
        print(f"  {day}  {per_day_ans[day]:>6} / {per_day[day]:<6}")

    print("\nPer hour of day")
    per_hour = Counter(c["start"].hour for c in calls)
    top = max(per_hour.values())
    for hour in range(24):
        if per_hour[hour]:
            print(f"  {hour:02d}:00  {per_hour[hour]:>6}  {bar(per_hour[hour], top)}")

    answered = [c for c in calls if c["disposition"] == "ANSWERED"]
    if answered:
        longest = max(answered, key=lambda c: c["billsec"])
        avg = sum(c["billsec"] for c in answered) / len(answered)
        short = sum(1 for c in answered if c["billsec"] < args.short)
        print(f"\nAnswered: {len(answered)}  avg {avg:.0f}s  longest {longest['billsec']}s "
              f"({longest['src']} -> {longest['dst']} at {longest['start']:%Y-%m-%d %H:%M})")
        print(f"Short answered calls (<{args.short}s): {short}")

    pool = answered if args.answered_only else calls
    peak, peak_at, saturated = concurrency(pool, args.trunks)
    print(f"\nPeak concurrent legs: {peak}" + (f" at {peak_at:%Y-%m-%d %H:%M:%S}" if peak_at else ""))
    if args.trunks:
        print(f"Time at or above {args.trunks} concurrent: {saturated / 60:.1f} min"
              + ("  <- trunks were exhausted" if saturated else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # e.g. piped into head
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
