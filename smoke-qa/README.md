# smoke-qa

A four-script smoke test for a web app running on localhost, built in March 2026
for the Cyguin OpenCode sprint workflow ("opencode-smoke-qa"). It finds what is
broken, writes it up in a shape an LLM can act on, and can loop: triage, hand the
tasks to OpenCode, re-run the smoke test, repeat.

```
crawl.py  ->  form_test.py  ->  report.py  ->  triage.py [--loop]
 pages,        every form,       one merged     LLM turns findings into tasks,
 console       valid and         handoff JSON   injects them into OpenCode,
 and network   hostile input                    re-runs the three scripts
 errors
```

## Run it

```
pip install playwright && playwright install chromium
# start your app on port 3000 (or set QA_PORT), then:
python3 crawl.py && python3 form_test.py && python3 report.py
python3 triage.py                  # one triage pass, writes a task list, changes nothing
python3 triage.py --inject-only    # triage, then hand the tasks to OpenCode, no re-test
python3 triage.py --loop           # fix, re-test, repeat (QA_MAX_ITERATIONS, default 5)
python3 triage.py --loop --severity WARN
python3 triage.py --loop --warn-iterations 2
```

`--loop` stops once no FAIL tasks remain when run non-interactively. To keep going
on WARN items use `--severity WARN`, or `--warn-iterations N` for N extra passes.

## Configuration (environment variables)

| Variable | Default | Used by |
|---|---|---|
| `QA_PORT` | 3000 | crawl, form_test, triage |
| `QA_BASE_URL` | `http://localhost:$QA_PORT` | crawl, form_test |
| `QA_MAX_PAGES`, `QA_MAX_DEPTH` | 50, 3 | crawl |
| `QA_SCREENSHOT_DIR` | `/tmp/qa-screenshots` | crawl |
| `QA_REPORT_OUT` | `/tmp/qa-crawl-report.json` | crawl (writes) |
| `QA_CRAWL_REPORT`, `QA_FORM_REPORT` | `/tmp/qa-crawl-report.json`, `/tmp/qa-form-report.json` | form_test, report |
| `QA_FINAL_REPORT` | `/tmp/qa-final-report.json` | report (writes), triage (reads) |
| `QA_SERVER_LOG` | `/tmp/qa-server.log` | report |
| `QA_REPORT_DIR`, `QA_PROJECT_DIR` | `/tmp/qa-reports`, cwd | triage |
| `QA_MAX_ITERATIONS`, `QA_FIX_SEVERITY`, `QA_TRIAGE_MODEL` | 5, `FAIL`, auto | triage |
| `OPENCODE_GO_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | unset | triage (first match wins, see its docstring) |

If the triage call fails or no backend is found, `triage.py` prints the error and
falls back to simple tasks built directly from the report.

## Recovery notes (2026-11-21)

The scripts were rebuilt from the March 2026 build record, then run end to end
against a local test site in real Chrome. Differences from the original:

1. `triage.py`: `run_loop()` needed `global FIX_SEVERITY`. Without it `--loop`
   died with `UnboundLocalError` on its first line.
2. `triage.py`: `OPENCODE_GO_BASE_URL` pointed at the full `/chat/completions`
   URL, and the openai client appends that path itself, so requests went to
   `.../chat/completions/chat/completions`. It now stops at `/v1` (checked
   against a mock server).

## Known rough edges

- Not re-verified since March: the OpenCode Go endpoint and model names, and the
  `opencode run --print` call used by the inject and delegate paths. The current
  OpenCode docs list `opencode run [message]` with `--model` and `--format`, and
  do not list `--print`. If injection fails, drop that flag.
- The delegate path runs `opencode` through a shell (`shell=True`). Fine for a
  local dev box, not something to point at untrusted input.
- `crawl.py` flags any page with under 20 visible characters as "Blank page",
  which is a false positive for a minimal contact or redirect page.
- `datetime.utcnow()` deprecation warnings on current Python.
- The form fixtures include a test password and a 555 phone number; they are
  throwaway values for submitting to your own app only.
