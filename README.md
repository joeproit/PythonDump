# PythonDump
 Dump of python things

Newer scripts below. Each file's docstring has the full usage, the scenario it
was written for, and where it came from. All are single-file, with exit codes
you can script against (0 ok, 1 finding or change, 2 bad input). Only
`md-to-docx.py` needs a third-party package (`python-docx`).

Older, unchanged: `crawler.py`, `dice-roller.py`, `job-search.py`, `StudyGlanceLabsClone/`.

## Sysadmin and phone-system scripts (WDSE IT, April 2026 at the latest)

| Script | Scenario for use | Origin | Deps |
|---|---|---|---|
| `asterisk-cdr-summary.py` | After a pledge drive, on-air event or outage: how many calls, any dropped, did the trunks run out? Totals by disposition, calls per day and hour, peak concurrent legs, minutes spent at the trunk limit. Works on Master.csv or a FreePBX CDR export. | WDSE, PBXact phone system, April 2026 at the latest | stdlib |
| `iptables-drift.py` | CentOS/PBXact box where rules were added live but never persisted with `iptables-save > /etc/sysconfig/iptables`. Run before a reboot or NIC swap, or from cron, to catch rules that would silently vanish. | WDSE, PBXact hardening (fail2ban plus custom iptables), April 2026 at the latest | stdlib |
| `pjsip-direct-media-audit.py` | One-way or no audio between phones and the SIP provider. Lists every PJSIP endpoint whose effective `direct_media` is yes (it defaults to yes) and prints the `pjsip.endpoint_custom_post.conf` override. | WDSE, phone VLAN and firewall migration, April 2026 at the latest | stdlib |
| `port-check.py` | Right after a firewall, VLAN, switch or NIC change: do the services I need answer, and are the ports that must stay blocked still blocked? Pass/fail per line, scriptable exit code. | WDSE, network and phone-system migration checks, April 2026 at the latest | stdlib |
| `md-to-docx.py` | Keep SOPs, runbooks and policies as markdown in git and regenerate the Word versions in bulk, for example when a whole document set is re-issued after an owner, header or date change. | WDSE policy, SOP and governance doc set, April 2026 | python-docx |

## Cyguin scripts (2026)

| Script | Scenario for use | Origin | Deps |
|---|---|---|---|
| `cron-heartbeat.py` | Backups, cert renewals and report jobs that fail silently. Jobs ping a URL when they finish; a monitor that goes quiet raises a DOWN alert (stdout and optional webhook), then a RECOVERED alert on the next ping. SQLite state, no dependencies. | Cyguin "Cron Guardian" product concept, 2026 | stdlib |
| `site-watch.py` | Watch a vendor pricing or terms page, firmware release notes, a status page or an agency notice without checking by hand. Prints a unified diff of the visible text and exits 1 on change. | Cyguin "website change monitor" concept, 2026 | stdlib |
| `der-dump.py` | Inspect CMS/PKCS#7 and X.509 structures and see exactly which attribute, length or INTEGER encoding a verifier is choking on. Flags non-minimal lengths and INTEGERs, bad BOOLEANs and BER indefinite lengths. | Cyguin adversarial conformance research: PSCertPatterns (May 2026), PSCMSPatterns (June 2026) | stdlib |

## Notes

- No internal addresses, hostnames or credentials appear in any script; the
  examples use documentation ranges and placeholder names.
- Files use hyphenated names to match the older scripts in this repo.
- The scripts were written 2026-11-21 as clean, generalized versions of earlier
  work. The origin dates above are when that work happened, not commit dates.
  The WDSE items are from April 2026 at the latest.
