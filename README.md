# PythonDump
 Dump of python things

Newer scripts below. Each file's docstring has the full usage, the scenario it
was written for, and where it came from. The single-file scripts have exit codes
you can script against (0 ok, 1 finding or change, 2 bad input). `md-to-docx.py` needs `python-docx`; `smoke-qa/` needs Playwright,
and `clawlib-inventory.py` invokes the Git command-line tool.

Older, unchanged: `crawler.py`, `dice-roller.py`, `job-search.py`, `StudyGlanceLabsClone/`.

## Sysadmin and phone-system scripts (WDSE IT, April 2026 at the latest)

| Script | Scenario for use | Origin | Deps |
|---|---|---|---|
| `asterisk-cdr-summary.py` | After a pledge drive, on-air event or outage: how many calls, any dropped, did the trunks run out? Totals by disposition, calls per day and hour, unique callers (queue retries collapsed) and how many never reached a human, why unanswered legs went unanswered (by dialplan context), peak concurrent legs, minutes spent at the trunk limit. `--log` also scans the Asterisk full log, plain or .gz, for cause 34 and CONGESTION. Works on Master.csv or a FreePBX CDR export. | WDSE, PBXact phone system, April 2026 at the latest | stdlib |
| `iptables-drift.py` | CentOS/PBXact box where rules were added live but never persisted with `iptables-save > /etc/sysconfig/iptables`. Run before a reboot or NIC swap, or from cron, to catch rules that would silently vanish. | WDSE, PBXact hardening (fail2ban plus custom iptables), April 2026 at the latest | stdlib |
| `pjsip-direct-media-audit.py` | One-way or no audio between phones and the SIP provider. Lists every PJSIP endpoint whose effective `direct_media` is yes (it defaults to yes) and prints the `pjsip.endpoint_custom_post.conf` override. | WDSE, phone VLAN and firewall migration, April 2026 at the latest | stdlib |
| `port-check.py` | Right after a firewall, VLAN, switch or NIC change: do the services I need answer, and are the ports that must stay blocked still blocked? Pass/fail per line, scriptable exit code. | WDSE, network and phone-system migration checks, April 2026 at the latest | stdlib |
| `md-to-docx.py` | Keep SOPs, runbooks and policies as markdown in git and regenerate the Word versions in bulk, for example when a whole document set is re-issued after an owner, header or date change. | WDSE policy, SOP and governance doc set, April 2026 | python-docx |

## Cyguin scripts (2026)

| Script | Scenario for use | Origin | Deps |
|---|---|---|---|
| `cron-heartbeat.py` | Backups, cert renewals and report jobs that fail silently. Jobs ping a URL when they finish; a monitor that goes quiet raises a DOWN alert (stdout and optional webhook), then a RECOVERED alert on the next ping. SQLite state, no dependencies. | Cyguin "Cron Guardian" product concept, 2026 | stdlib |
| `site-watch.py` | Watch a vendor pricing or terms page, firmware release notes, a status page or an agency notice without checking by hand. Prints a unified diff of the visible text and exits 1 on change. | Cyguin "website change monitor" concept, 2026 | stdlib |
| `smoke-qa/` | Before shipping a web app: crawl every internal page, fill and submit every form with valid and hostile input, collect console and network errors and screenshots, merge it into one report, then optionally have an LLM triage the findings into a task list and feed it to OpenCode in a fix, re-test, repeat loop. See `smoke-qa/README.md`. | Cyguin "opencode-smoke-qa" pipeline, March 2026 | playwright; optional openai |
| `der-dump.py` | Inspect CMS/PKCS#7 and X.509 structures and see exactly which attribute, length or INTEGER encoding a verifier is choking on. Flags non-minimal lengths and INTEGERs, bad BOOLEANs and BER indefinite lengths. | Cyguin adversarial conformance research: PSCertPatterns (May 2026), PSCMSPatterns (June 2026) | stdlib |

## Additional reconstructed utilities (prepared November 2026)

These scripts implement problems discussed previously; they are **reconstructions**, not recovered original source files. The month and year below refer to the discussion, not the Git commit date.

| Script | Scenario for use | Origin | Deps |
|---|---|---|---|
| `indeed-csv-analyzer.py` | Deduplicate an exported job-listing CSV by job key or URL, normalize company/title/salary/rating fields, and rank listings by rating and minimum salary. Does not scrape job boards. | Job-search data analysis discussion, April 2023; reconstructed November 2026 | stdlib |
| `mtg-deck-simulator.py` | Compare exact hypergeometric and Monte Carlo probabilities of drawing a chosen number of lands in an opening hand. Configurable deck size, hand size, land count, and random seed. | MTG deck probability discussion, February 2025; reconstructed November 2026 | stdlib |
| `clawlib-inventory.py` | Scan a local directory for Git repositories and export their paths, branches, remotes, and commit IDs to JSON; optionally flag dirty working trees. Read-only; does not pull or update repositories. | ClawLib repository-inventory discussion, February 2026; reconstructed November 2026 | stdlib + Git CLI |

Example commands:

```bash
python indeed-csv-analyzer.py jobs.csv -o ranked.csv --min-rating 4.0
python mtg-deck-simulator.py --deck 60 --lands 24 --hand 7 --trials 100000
python clawlib-inventory.py ~/clawlib -o sources.json --include-dirty
```

The three additions were syntax-checked but have not been end-to-end tested against real input datasets. They use exit code 0 for success and 2 for invalid input; the general exit-code convention above describes other utilities that may also return 1 for findings or changes.

## Notes

- No internal addresses, hostnames or credentials appear in any script; the
  examples use documentation ranges and placeholder names.
- Files use hyphenated names to match the older scripts in this repo.
- The original batch of newer single-file scripts was written 2026-11-21 as clean, generalized
  versions of earlier work. The three additional reconstructed utilities were prepared in November 2026. The origin dates above are when that work happened,
  not commit dates. The WDSE items are from April 2026 at the latest.
- `smoke-qa/` is different: it was recovered on 2026-11-21 from the March 2026
  build record, not rewritten. Two small fixes were made during recovery and are
  listed in `smoke-qa/README.md`.
