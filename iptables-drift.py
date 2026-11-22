#!/usr/bin/env python3
"""iptables-drift.py: diff live iptables rules against the persisted config.

Scenario: on CentOS-family boxes (PBXact/FreePBX, Sangoma) rules added with
          iptables -I/-A live only in memory until someone runs
          "iptables-save > /etc/sysconfig/iptables". After a reboot or a NIC
          swap the unsaved rules vanish and nobody notices. Run this before any
          reboot, or from cron to catch drift.
Origin:   WDSE IT, PBXact hardening with fail2ban plus custom iptables
          (PBX firewall module disabled), 2026. Written 2026-11-21.

Counters and comments are ignored. Lines matching fail2ban chains (f2b-) are
ignored by default because bans change constantly. Exit 0 = in sync, 1 = drift,
2 = could not read a side.

  iptables-drift.py                 # runs iptables-save, compares to /etc/sysconfig/iptables
  iptables-drift.py --v6            # ip6tables-save vs /etc/sysconfig/ip6tables
  iptables-drift.py --live live.txt --saved saved.txt    # compare two files

Deps: none (stdlib only). Needs root to run iptables-save.
"""
import argparse
import difflib
import re
import subprocess
import sys

COUNTERS = re.compile(r"\s*\[\d+:\d+\]")


def normalize(text, ignore):
    out = []
    for line in text.splitlines():
        line = COUNTERS.sub("", line).strip()
        if not line or line.startswith("#"):
            continue
        if any(rx.search(line) for rx in ignore):
            continue
        out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser(description="Diff live iptables rules against the saved config")
    ap.add_argument("--v6", action="store_true", help="use ip6tables instead")
    ap.add_argument("--live", help="read live rules from this file instead of running iptables-save")
    ap.add_argument("--saved", help="persisted rules file (default /etc/sysconfig/ip[6]tables)")
    ap.add_argument("--ignore", action="append", default=[], metavar="REGEX",
                    help="also drop lines matching this regex (repeatable)")
    ap.add_argument("--no-default-ignore", action="store_true", help="do not ignore f2b- lines")
    args = ap.parse_args()

    tool = "ip6tables" if args.v6 else "iptables"
    saved_path = args.saved or f"/etc/sysconfig/{tool}"
    patterns = args.ignore + ([] if args.no_default_ignore else [r"f2b-"])
    try:
        ignore = [re.compile(p) for p in patterns]
    except re.error as exc:
        print(f"[ERROR] bad --ignore pattern: {exc}", file=sys.stderr)
        return 2

    try:
        if args.live:
            live_text = open(args.live, encoding="utf-8").read()
        else:
            proc = subprocess.run([f"{tool}-save"], check=True, capture_output=True, text=True)
            live_text = proc.stdout
            if not live_text.strip():
                raise OSError(f"{tool}-save returned no rules ({proc.stderr.strip() or 'run as root?'})")
        saved_text = open(saved_path, encoding="utf-8").read()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    saved, live = normalize(saved_text, ignore), normalize(live_text, ignore)
    if saved == live:
        print(f"[INFO] in sync: {len(live)} lines")
        return 0

    print(f"[DRIFT] '-' = only in saved config, '+' = only in live rules")
    for line in difflib.unified_diff(saved, live, "saved", "live", lineterm="", n=1):
        print(line)
    print(f"\nTo persist the live rules: {tool}-save > {saved_path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
