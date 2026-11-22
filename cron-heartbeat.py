#!/usr/bin/env python3
"""cron-heartbeat.py: dead man's switch for cron jobs (Cron Guardian MVP).

Scenario: nightly backups, cert renewals, report exports and other cron jobs
          that fail silently. Cron only tells you when a job runs, never when
          it stops running.
Origin:   Cyguin "Cron Guardian" product concept, 2026. Fits any Linux server
          with cron-driven backups, WDSE-style or otherwise.
Written:  2026-11-21

A job pings http://host:port/ping/<name> when it finishes. If a monitor goes
quiet for longer than interval + grace seconds, a DOWN alert is printed and,
with --webhook, POSTed as JSON ({"event","monitor","detail","text"}). The next
ping after an alert fires a RECOVERED alert.

  cron-heartbeat.py add backup --interval 86400 --grace 600
  cron-heartbeat.py serve --port 8080 --webhook https://hooks.example/abc
  # crontab:  0 2 * * * /usr/local/bin/backup.sh && curl -fsS http://host:8080/ping/backup
  cron-heartbeat.py list
  cron-heartbeat.py check      # one-shot check (exit 1 if anything went down)

GET /status returns all monitors as JSON. State lives in a SQLite file
(--db, default heartbeat.db). There is no auth: bind to localhost or put it
behind a reverse proxy.

Deps: none (stdlib only).
"""
import argparse
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

SCHEMA = """CREATE TABLE IF NOT EXISTS monitors (
    name TEXT PRIMARY KEY,
    interval INTEGER NOT NULL,
    grace INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    last_ping REAL,
    alerted INTEGER NOT NULL DEFAULT 0,
    pings INTEGER NOT NULL DEFAULT 0)"""
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


@contextmanager
def db(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def notify(event, name, detail, webhook):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{event.upper()}] {name}: {detail}"
    print(line, flush=True)
    if not webhook:
        return
    body = json.dumps({"event": event, "monitor": name, "detail": detail, "text": line}).encode()
    req = urllib.request.Request(webhook, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as exc:
        print(f"[WARN] webhook failed: {exc}", file=sys.stderr, flush=True)


def check(path, webhook, now=None):
    """Mark overdue monitors as down and alert. Returns [(name, detail)]."""
    now = time.time() if now is None else now
    fired = []
    with db(path) as conn:
        for r in conn.execute("SELECT * FROM monitors WHERE alerted = 0").fetchall():
            base = r["last_ping"] or r["created"]
            if now - base > r["interval"] + r["grace"]:
                conn.execute("UPDATE monitors SET alerted = 1 WHERE name = ?", (r["name"],))
                fired.append((r["name"], f"no ping for {int(now - base)}s "
                                         f"(expected every {r['interval']}s, grace {r['grace']}s)"))
    for name, detail in fired:
        notify("down", name, detail, webhook)
    return fired


def record_ping(path, name, webhook, now=None):
    now = time.time() if now is None else now
    with db(path) as conn:
        row = conn.execute("SELECT alerted FROM monitors WHERE name = ?", (name,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE monitors SET last_ping = ?, pings = pings + 1, alerted = 0 WHERE name = ?",
                     (now, name))
    if row["alerted"]:
        notify("recovered", name, "ping received after alert", webhook)
    return True


def make_handler(path, webhook):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, text):
            data = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def handle_any(self):
            parts = [unquote(p) for p in urlparse(self.path).path.split("/") if p]
            if len(parts) == 2 and parts[0] == "ping":
                ok = record_ping(path, parts[1], webhook)
                return self.reply(200 if ok else 404, "ok\n" if ok else "unknown monitor\n")
            if parts == ["status"]:
                with db(path) as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM monitors ORDER BY name")]
                return self.reply(200, json.dumps(rows, indent=2) + "\n")
            self.reply(404, "not found\n")

        do_GET = do_POST = handle_any

        def log_message(self, *args):
            pass

    return Handler


def cmd_serve(args):
    def loop():
        while True:
            try:
                check(args.db, args.webhook)
            except Exception as exc:
                print(f"[ERROR] check failed: {exc}", file=sys.stderr, flush=True)
            time.sleep(args.check_every)

    threading.Thread(target=loop, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.db, args.webhook))
    print(f"[INFO] listening on {args.host}:{args.port}, db={args.db}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    return 0


def cmd_add(args):
    if not NAME.match(args.name):
        print("[ERROR] name must match [A-Za-z0-9_.-]+", file=sys.stderr)
        return 2
    with db(args.db) as conn:
        conn.execute(
            "INSERT INTO monitors (name, interval, grace, created) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET interval = excluded.interval, grace = excluded.grace",
            (args.name, args.interval, args.grace, time.time()))
    print(f"[INFO] monitor {args.name}: every {args.interval}s, grace {args.grace}s")
    return 0


def cmd_remove(args):
    with db(args.db) as conn:
        n = conn.execute("DELETE FROM monitors WHERE name = ?", (args.name,)).rowcount
    print(f"[INFO] removed {args.name}" if n else f"[WARN] no such monitor: {args.name}")
    return 0 if n else 1


def cmd_list(args):
    now = time.time()
    with db(args.db) as conn:
        rows = conn.execute("SELECT * FROM monitors ORDER BY name").fetchall()
    print(f"{'NAME':<24}{'EVERY':>8}{'GRACE':>7}{'LAST PING':>12}{'PINGS':>7}  STATE")
    for r in rows:
        age = f"{int(now - r['last_ping'])}s ago" if r["last_ping"] else "never"
        if r["alerted"]:
            state = "DOWN"
        elif r["last_ping"] is None:
            state = "WAITING"
        else:
            state = "OK"
        print(f"{r['name']:<24}{r['interval']:>8}{r['grace']:>7}{age:>12}{r['pings']:>7}  {state}")
    return 0


def cmd_check(args):
    return 1 if check(args.db, args.webhook) else 0


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default="heartbeat.db")
    common.add_argument("--webhook", help="POST JSON alerts to this URL")

    ap = argparse.ArgumentParser(description="Cron job dead man's switch")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", parents=[common], help="run the ping server and checker")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--check-every", type=int, default=15, help="seconds between checks")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("add", parents=[common], help="create or update a monitor")
    p.add_argument("name")
    p.add_argument("--interval", type=int, required=True, help="expected seconds between pings")
    p.add_argument("--grace", type=int, default=0, help="extra seconds before alerting")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("remove", parents=[common])
    p.add_argument("name")
    p.set_defaults(fn=cmd_remove)

    sub.add_parser("list", parents=[common]).set_defaults(fn=cmd_list)
    sub.add_parser("check", parents=[common], help="one-shot overdue check").set_defaults(fn=cmd_check)

    args = ap.parse_args()
    if getattr(args, "interval", 1) <= 0:
        ap.error("--interval must be positive")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
