#!/usr/bin/env python3
"""asterisk-cdr-summary.py: summarize an Asterisk / FreePBX / PBXact CDR export.

Scenario: after a pledge drive, on-air event or outage, answer "how many calls
          did we get, did we drop any, do we need more trunks?" from the CDR
          and, optionally, the Asterisk full log. Gives totals by disposition,
          calls per day and hour, unique callers (queue retries collapsed),
          why unanswered legs went unanswered, peak concurrent calls, how long
          the trunks were full (--trunks N), and whether the log shows trunk
          congestion (--log).
Origin:   WDSE IT, PBXact phone system, April 2026 at the latest (CDR analysis
          for pledge-drive and event call volume). The script itself was
          written 2026-11-21 from that work.

Input is Master.csv (no header, Asterisk cdr_csv column order) or an export
with a header row (FreePBX CDR Reports / mysql dump of asteriskcdrdb.cdr; needs
calldate or start, plus duration, billsec, disposition; dcontext is used when
present).

CDR rows are call legs. A call that rings a group or crosses a trunk and an
extension produces several rows, so peak concurrency counted over every row
overstates trunk use, and "unique callers" would include your own extensions.
Use --channel-match to count only trunk legs:

  asterisk-cdr-summary.py Master.csv
  asterisk-cdr-summary.py cdr.csv --since 2026-03-20 --until 2026-03-22 \\
      --channel-match 'PJSIP/(provider1|provider2)' --trunks 23 --answered-only
  asterisk-cdr-summary.py cdr.csv --channel-match 'PJSIP/provider1' \\
      --log /var/log/asterisk/full --since 2026-03-20 --until 2026-03-21

Unique callers: callers hitting an unanswered queue retry automatically, so one
person shows up as the same number 2-4 times about 20 seconds apart. Rows from
one number count as one caller until that number goes quiet for more than
--unique-window seconds (default 300). "Never reached a human" means no
ANSWERED leg with billsec > 0 in that caller's burst. ANSWERED with billsec 0
is a hand-off leg (IVR, queue or transfer), not a person picking up.

Unanswered legs are grouped by dialplan context. Standard FreePBX contexts get
a hint: ext-queues is a queue nobody answered (staffing), from-did-direct a
direct extension nobody answered, ext-local an internal routing miss, and
from-pstn a failure at the trunk or inbound route, which deserves a look.

--log scans an Asterisk full log (plain or .gz, lines starting
[YYYY-MM-DD HH:MM:SS]) for "trunk full" evidence: cause 34 / circuit
congestion, CONGESTION, "no available channels" and "all circuits busy". Cause
17 is counted but is also ordinary user-busy, so it never changes the exit
code. --since/--until apply to the log as well; lines without a parseable
stamp are skipped when a range is given and scanned when it is not.

Exit codes: 0 ok, 1 no rows in range or congestion found in the log, 2 bad
input.

Deps: none (stdlib only).
"""
import argparse
import csv
import gzip
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

CONTEXT_HINTS = {
    "ext-queues": "queue, nobody answered (staffing or queue timeout)",
    "from-did-direct": "direct extension call, nobody answered",
    "ext-local": "internal routing miss",
    "from-pstn": "failed at trunk or inbound route, worth a look",
}

# Log evidence that a trunk ran out of channels. Order is the print order.
CONGESTION = [
    ("cause 34 / circuit congestion", re.compile(r"cause[=: ]+34\b|Circuit/channel congestion", re.I)),
    ("CONGESTION dial status", re.compile(r"CONGESTION")),
    ("no available channels", re.compile(r"no available channels", re.I)),
    ("all circuits busy", re.compile(r"all circuits busy", re.I)),
    ("cause 17 (also plain busy)", re.compile(r"cause[=: ]+17\b", re.I)),
]
WEAK = "cause 17 (also plain busy)"
LOG_STAMP = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


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
    calls, skipped, parsed = [], 0, 0
    for row in read_rows(path):
        start = parse_ts(row.get("start") or row.get("calldate"))
        if start is None:
            skipped += 1
            continue
        parsed += 1
        if (since and start < since) or (until and start >= until):
            continue
        duration, billsec = to_int(row.get("duration")), to_int(row.get("billsec"))
        end = parse_ts(row.get("end")) or start + timedelta(seconds=duration)
        calls.append({
            "start": start, "end": end, "billsec": billsec,
            "disposition": (row.get("disposition") or "UNKNOWN").strip().upper(),
            "src": (row.get("src") or "").strip(), "dst": (row.get("dst") or "").strip(),
            "ctx": (row.get("dcontext") or "").strip(),
            "chan": f"{row.get('channel') or ''} {row.get('dstchannel') or ''}",
        })
    return calls, skipped, parsed


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


def unique_callers(calls, window):
    """Collapse repeat rows from one number into one caller.

    A row from the same src belongs to the caller's current burst while it starts
    within `window` seconds of that src's previous row; a longer silence starts a new
    caller. Rows with no src cannot be matched and count one each.
    Returns (callers, callers_who_never_reached_a_human, rows_without_caller_id).
    """
    open_bursts = {}  # src -> [start of last row, reached a human]
    reached = []      # one flag per finished caller
    anonymous = 0
    for c in sorted(calls, key=lambda c: c["start"]):
        human = c["disposition"] == "ANSWERED" and c["billsec"] > 0
        if not c["src"]:
            anonymous += 1
            reached.append(human)
            continue
        cur = open_bursts.get(c["src"])
        if cur and (c["start"] - cur[0]).total_seconds() <= window:
            cur[0] = c["start"]
            cur[1] = cur[1] or human
        else:
            if cur:
                reached.append(cur[1])
            open_bursts[c["src"]] = [c["start"], human]
    reached += [b[1] for b in open_bursts.values()]
    return len(reached), reached.count(False), anonymous


def scan_log(path, since, until, samples):
    """Count congestion strings in an Asterisk full log (plain or .gz)."""
    opener = gzip.open if path.endswith(".gz") else open
    ranged = bool(since or until)
    res = {"lines": 0, "undated": 0, "hits": Counter(), "strong": 0, "samples": [],
           "first": None, "last": None}
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            res["lines"] += 1
            m = LOG_STAMP.match(line)
            when = parse_ts(m.group(1)) if m else None
            if when:
                res["first"] = min(res["first"], when) if res["first"] else when
                res["last"] = max(res["last"], when) if res["last"] else when
                if (since and when < since) or (until and when >= until):
                    continue
            else:
                res["undated"] += 1
                if ranged:
                    continue
            labels = [label for label, rx in CONGESTION if rx.search(line)]
            for label in labels:
                res["hits"][label] += 1
            if any(label != WEAK for label in labels):
                res["strong"] += 1
                if len(res["samples"]) < samples:
                    res["samples"].append(line.rstrip()[:200])
    res["ranged"] = ranged
    return res


def print_log(res, path):
    span = (f"{res['first']:%Y-%m-%d %H:%M} to {res['last']:%Y-%m-%d %H:%M}"
            if res["first"] else "no timestamps found")
    print(f"\nTrunk congestion check ({os.path.basename(path)}: {res['lines']} lines, log covers {span})")
    for label, _ in CONGESTION:
        print(f"  {label:<32}{res['hits'][label]:>7}")
    if res["undated"]:
        print(f"  [{res['undated']} lines without a [YYYY-MM-DD HH:MM:SS] stamp "
              f"{'skipped' if res['ranged'] else 'scanned'}]")
    for line in res["samples"]:
        print(f"    {line}")
    if res["strong"]:
        print(f"  {res['strong']} lines show trunk congestion  <- trunks were exhausted")
    else:
        print("  no congestion evidence in this window (confirm the log covers the period above)")


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
    ap.add_argument("--unique-window", type=int, default=300, metavar="SECONDS",
                    help="a number quiet for longer than this starts a new caller (default 300)")
    ap.add_argument("--log", metavar="PATH", help="Asterisk full log (plain or .gz) to scan for trunk congestion")
    ap.add_argument("--log-samples", type=int, default=3, help="congestion log lines to print (default 3)")
    args = ap.parse_args()

    since, until = parse_ts(args.since), parse_ts(args.until)
    if (args.since and not since) or (args.until and not until):
        print("[ERROR] bad --since/--until, use YYYY-MM-DD[ HH:MM[:SS]]", file=sys.stderr)
        return 2
    if args.unique_window < 0:
        print("[ERROR] --unique-window must be 0 or more", file=sys.stderr)
        return 2
    try:
        calls, skipped, parsed = load_calls(args.csv, since, until)
        pattern = re.compile(args.channel_match) if args.channel_match else None
        log = scan_log(args.log, since, until, args.log_samples) if args.log else None
    except (OSError, re.error, EOFError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if parsed == 0 and skipped:
        print(f"[ERROR] none of the {skipped} rows in {args.csv} has a readable start/calldate; "
              "wrong file, or columns not in Master.csv order and no header row", file=sys.stderr)
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
        handoff = sum(1 for c in answered if c["billsec"] == 0)
        print(f"\nAnswered: {len(answered)}  avg {avg:.0f}s  longest {longest['billsec']}s "
              f"({longest['src']} -> {longest['dst']} at {longest['start']:%Y-%m-%d %H:%M})")
        print(f"Short answered calls (<{args.short}s): {short}")
        print(f"ANSWERED with billsec 0 (hand-off legs, not a human answer): {handoff}")

    callers, never, anonymous = unique_callers(calls, args.unique_window)
    print(f"\nUnique callers ({args.unique_window}s quiet gap starts a new caller): {callers}"
          f"  from {len(calls)} rows")
    print(f"  never reached a human (no ANSWERED leg with billsec > 0): {never}")
    if anonymous:
        print(f"  includes {anonymous} rows with no caller ID, counted one each")

    missed = Counter((c["disposition"], c["ctx"] or "(none)") for c in calls if c["disposition"] != "ANSWERED")
    if missed:
        print("\nUnanswered legs by dialplan context")
        for (disp, ctx), n in sorted(missed.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {disp:<12}{ctx:<18}{n:>6}  {CONTEXT_HINTS.get(ctx, '')}".rstrip())

    pool = answered if args.answered_only else calls
    peak, peak_at, saturated = concurrency(pool, args.trunks)
    print(f"\nPeak concurrent legs: {peak}" + (f" at {peak_at:%Y-%m-%d %H:%M:%S}" if peak_at else ""))
    if args.trunks:
        print(f"Time at or above {args.trunks} concurrent: {saturated / 60:.1f} min"
              + ("  <- trunks were exhausted" if saturated else ""))

    if log:
        print_log(log, args.log)
        if log["strong"]:
            return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # e.g. piped into head
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
