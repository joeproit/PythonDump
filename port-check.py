#!/usr/bin/env python3
"""port-check.py: TCP reachability matrix with expected-open and expected-closed checks.

Scenario: right after a firewall rule change, VLAN move, switch swap or NIC
          swap, confirm from this box that the services you need answer and
          the ones that must stay blocked still do. One command, pass/fail per
          line, exit code for scripting.
Origin:   WDSE IT, network and phone-system migration checks, 2026.
Written:  2026-11-21

Targets are host:port on the command line or one per line in --file
("#" comments allowed, optional label after the target). Prefix with ! when the
port is expected to be closed or filtered. IPv6 literals go in brackets.

  port-check.py 10.0.0.1:443 example.com:5060 '!10.0.0.9:3306'
  port-check.py --file targets.txt --timeout 2

targets.txt:
  gateway.example.com:443   firewall admin
  pbx.example.com:5060      SIP
  !db.example.com:3306      must not be reachable from here

TCP only. UDP services (most SIP trunks, NTP, DNS) cannot be verified by a plain
connect, so a closed UDP port will not show up here.
Exit 0 = every expectation met, 1 = at least one failed, 2 = bad input.

Deps: none (stdlib only).
"""
import argparse
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor

TARGET = re.compile(r"^(!)?(\[[^\]]+\]|[^:\s]+):(\d{1,5})(?:\s+(.*))?$")


def parse_target(line):
    m = TARGET.match(line.strip())
    if not m or not 0 < int(m.group(3)) < 65536:
        raise ValueError(f"bad target: {line.strip()!r}")
    expect_closed, host, port, label = m.groups()
    return {"closed": bool(expect_closed), "host": host.strip("[]"), "port": int(port),
            "label": (label or "").strip()}


def probe(target, timeout):
    started = time.monotonic()
    try:
        with socket.create_connection((target["host"], target["port"]), timeout=timeout):
            state = "OPEN"
    except socket.gaierror:
        state = "DNSFAIL"
    except ConnectionRefusedError:
        state = "CLOSED"
    except (socket.timeout, TimeoutError):
        state = "TIMEOUT"
    except OSError as exc:
        state = f"ERROR({exc.errno})"
    ms = (time.monotonic() - started) * 1000
    passed = state in ("CLOSED", "TIMEOUT") if target["closed"] else state == "OPEN"
    return {**target, "state": state, "ms": ms, "passed": passed}


def main():
    ap = argparse.ArgumentParser(description="TCP reachability check with expectations")
    ap.add_argument("targets", nargs="*", help="host:port, prefix ! if expected closed")
    ap.add_argument("--file", help="file with one target per line")
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    lines = list(args.targets)
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as fh:
                lines += [ln.split("#", 1)[0] for ln in fh]
        except OSError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    lines = [ln for ln in lines if ln.strip()]
    try:
        targets = [parse_target(ln) for ln in lines]
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if not targets:
        ap.error("no targets given")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda t: probe(t, args.timeout), targets))

    for r in results:
        want = "closed" if r["closed"] else "open"
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['host'] + ':' + str(r['port']):<32}"
              f"{r['state']:<12}{r['ms']:7.0f} ms  want {want:<7}{r['label']}")
    failed = sum(not r["passed"] for r in results)
    print(f"\n{len(results) - failed}/{len(results)} as expected")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
