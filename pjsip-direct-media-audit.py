#!/usr/bin/env python3
"""pjsip-direct-media-audit.py: find PJSIP endpoints that will send media direct.

Scenario: one-way or no audio when phones and the SIP provider cannot reach each
          other directly (phones on a voice VLAN, trunk behind NAT/firewall).
          Asterisk's direct_media defaults to yes, so an endpoint with no
          setting is affected too. This lists every endpoint whose effective
          direct_media is yes and prints the override stanza to drop into
          pjsip.endpoint_custom_post.conf.
Origin:   WDSE IT, PBXact phone system, VLAN/firewall migration, 2026.
Written:  2026-11-21

Config files are applied in the order given; later files override earlier ones,
and templates ("[ext](tmpl)") are resolved. FreePBX load order is roughly:
pjsip.endpoint.conf, pjsip.endpoint_custom.conf, pjsip.endpoint_custom_post.conf.

  pjsip-direct-media-audit.py /etc/asterisk/pjsip.endpoint.conf \\
      /etc/asterisk/pjsip.endpoint_custom.conf /etc/asterisk/pjsip.endpoint_custom_post.conf
  pjsip-direct-media-audit.py --fix <files> >> /etc/asterisk/pjsip.endpoint_custom_post.conf
  # then: fwconsole reload

Exit 0 = clean, 1 = endpoints at risk, 2 = unreadable input.

Deps: none (stdlib only).
"""
import argparse
import re
import sys

SECTION = re.compile(r"^\[([^\]]+)\](?:\(([^)]*)\))?")


class Section:
    def __init__(self):
        self.templates, self.opts, self.is_template = [], {}, False


def parse(paths):
    """Merge endpoint sections from all files. Blocks that declare a type other
    than endpoint (aor, auth, transport...) share ids with endpoints in PJSIP,
    so they are dropped rather than merged in."""
    sections = {}
    for path in paths:
        blocks, in_comment = [], False
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if in_comment:
                    in_comment = "--;" not in line
                    continue
                if line.startswith(";--"):
                    in_comment = "--;" not in line
                    continue
                line = line.split(";", 1)[0].strip()
                if not line or line.startswith("#"):
                    continue
                m = SECTION.match(line)
                if m:
                    flags = [x.strip() for x in (m.group(2) or "").split(",") if x.strip()]
                    blocks.append((m.group(1), flags, {}))
                elif blocks and "=" in line:
                    key, _, val = line.partition("=")
                    blocks[-1][2][key.strip().lower()] = val.strip().lstrip(">").strip()
        for name, flags, opts in blocks:
            if opts.get("type", "endpoint") != "endpoint":
                continue
            sec = sections.setdefault(name, Section())
            for item in flags:
                if item == "!":
                    sec.is_template = True
                elif item != "+" and item not in sec.templates:
                    sec.templates.append(item)
            sec.opts.update(opts)
    return sections


def resolve(sections, name, key, seen=()):
    """Effective value of key for section name, honoring template inheritance."""
    sec = sections.get(name)
    if sec is None or name in seen:
        return None
    if key in sec.opts:
        return sec.opts[key]
    for parent in reversed(sec.templates):
        val = resolve(sections, parent, key, seen + (name,))
        if val is not None:
            return val
    return None


def main():
    ap = argparse.ArgumentParser(description="Audit PJSIP endpoints for direct_media=yes")
    ap.add_argument("files", nargs="+", help="pjsip config files in load order")
    ap.add_argument("--fix", action="store_true", help="print override stanzas only")
    args = ap.parse_args()

    try:
        sections = parse(args.files)
    except OSError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    endpoints = sorted(n for n, s in sections.items()
                       if not s.is_template and resolve(sections, n, "type") == "endpoint")
    risky = []
    for name in endpoints:
        value = (resolve(sections, name, "direct_media") or "").lower()
        if value in ("", "yes", "true", "1", "on"):
            risky.append((name, value or "unset (default yes)"))

    if args.fix:
        for name, _ in risky:
            print(f"[{name}](+)\ndirect_media=no\n")
        return 1 if risky else 0

    print(f"[INFO] {len(endpoints)} endpoints, {len(risky)} with direct_media effectively yes")
    for name, value in risky:
        print(f"  {name:<20} {value}")
    if risky:
        print("\nRe-run with --fix for override stanzas (pjsip.endpoint_custom_post.conf).")
    return 1 if risky else 0


if __name__ == "__main__":
    sys.exit(main())
