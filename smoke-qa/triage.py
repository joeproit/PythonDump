#!/usr/bin/env python3
"""
opencode-smoke-qa: LLM Self-Triage + Recursive Fix Loop

Phase 1: Reads the compiled QA report, calls the triage LLM, produces a
         prioritized task_list[] and injects tasks into OpenCode via CLI.

Phase 2 (--loop): fix cycle -> re-smoke -> re-triage -> repeat until
         no FAIL-severity tasks remain or max iterations is hit.

Model resolution order (first match wins):
  1. OPENCODE_GO_API_KEY set          -> OpenCode Go endpoint (kimi-k2.5 default)
  2. opencode.json config has model   -> detect provider, use that provider's API key
  3. Known API key env var present    -> call that provider directly (Anthropic, OpenAI, etc.)
  4. opencode binary available        -> delegate to OpenCode with no --model flag
  5. Hard fail with instructions      -> nothing usable found

Environment:
  QA_FINAL_REPORT     -- path to compiled report JSON (default: /tmp/qa-final-report.json)
  QA_REPORT_DIR       -- archive directory (default: /tmp/qa-reports)
  QA_PROJECT_DIR      -- path to the app being tested (default: cwd)
  QA_PORT             -- port the app runs on (default: 3000)
  QA_MAX_ITERATIONS   -- max fix-retest cycles in loop mode (default: 5)
  QA_FIX_SEVERITY     -- min severity to auto-fix: FAIL or WARN (default: FAIL)
  QA_TRIAGE_MODEL     -- override model for triage (default: auto-detect)
  OPENCODE_GO_API_KEY -- OpenCode Go subscription API key
  ANTHROPIC_API_KEY   -- direct Anthropic access (used if detected as session provider)
  OPENAI_API_KEY      -- direct OpenAI access (used if detected as session provider)
  GEMINI_API_KEY      -- direct Gemini access (used if detected as session provider)

OpenCode Go models (opencode.ai/docs/go/):
  kimi-k2.5    -- best reasoning/triage, OpenAI-compat endpoint  [DEFAULT]
  glm-5        -- strong coder, OpenAI-compat endpoint
  minimax-m2.7 -- high throughput, Anthropic-compat endpoint
  minimax-m2.5 -- cheapest/highest volume, Anthropic-compat endpoint

Recovery note (2026-11-21): rebuilt from the March 2026 chat record, edit by edit. Changes
from what was written then: `global FIX_SEVERITY` in run_loop(), because without it --loop
raised UnboundLocalError on its first line, and OPENCODE_GO_BASE_URL now stops at /v1,
because the openai client appends /chat/completions itself and the original doubled it
(checked against a mock server). The opencode CLI flags (`run`, `--model`,
`--print`) and the OpenCode Go endpoint come from OpenCode as of March 2026 and have not
been re-checked. In the current OpenCode docs `opencode run` takes the message as a
positional argument and `--print` is not a listed flag, so drop it if the injection or
delegate paths fail.
"""

import json, os, sys, uuid, subprocess, time, argparse, shutil
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"  # recovery fix: the openai client appends /chat/completions itself
OPENCODE_GO_API_KEY  = os.environ.get("OPENCODE_GO_API_KEY", "")
ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY       = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY       = os.environ.get("GEMINI_API_KEY", "")
TRIAGE_MODEL         = os.environ.get("QA_TRIAGE_MODEL", "")  # empty = auto-detect

FINAL_REPORT   = os.environ.get("QA_FINAL_REPORT",  "/tmp/qa-final-report.json")
REPORT_DIR     = os.environ.get("QA_REPORT_DIR",    "/tmp/qa-reports")
PROJECT_DIR    = os.environ.get("QA_PROJECT_DIR",   os.getcwd())
QA_PORT        = os.environ.get("QA_PORT",          "3000")
MAX_ITERATIONS = int(os.environ.get("QA_MAX_ITERATIONS", "5"))
FIX_SEVERITY   = os.environ.get("QA_FIX_SEVERITY",  "FAIL")

os.makedirs(REPORT_DIR, exist_ok=True)

SEVERITY_RANK = {"FAIL": 3, "WARN": 2, "INFO": 1}

def meets_fix_threshold(severity):
    return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK.get(FIX_SEVERITY, 3)

# ---------------------------------------------------------------------------
# Triage prompt
# ---------------------------------------------------------------------------

TRIAGE_PROMPT = """You are a senior QA engineer triaging automated smoke test results for a web application.

You will be given a structured JSON QA report. Your job is to:
1. Analyze every FAIL and WARN finding
2. Group related failures where probable cause is the same (one task per root cause, not per symptom)
3. Rank by severity: FAIL first, WARN second, INFO last
4. For each issue, identify the most likely root cause and write a specific, actionable fix instruction
   suitable for an AI coding agent (OpenCode) that has NO memory of this conversation

Fix instructions must be:
- Specific to the file, function, or route where the issue likely lives
- Actionable without additional context
- Concrete: "Add null check for user in handleSubmit() before accessing user.id" not "Fix the form"
- If multiple symptoms share a root cause, group them and list all affected locations

Severity rules:
- FAIL: app-breaking -- crashes, 5xx responses, unhandled exceptions, blank pages on primary routes
- WARN: degraded behavior -- missing validation, 404 on secondary routes, console errors, edge case failures
- INFO: observation only -- never auto-fixed

Return ONLY a JSON array. No preamble, no explanation, no markdown fences. Just the raw array.

Schema for each task:
{
  "task_id": "T01",
  "severity": "FAIL | WARN | INFO",
  "location": "<route, component, or likely file>",
  "symptom": "<what the smoke test observed>",
  "probable_cause": "<one sentence root cause hypothesis>",
  "fix_instruction": "<specific actionable instruction for OpenCode>",
  "evidence": ["<console error text, HTTP status, or screenshot path>"],
  "auto_fix": true
}

Set auto_fix: false only for INFO items or issues requiring human judgment
(ambiguous behavior that might be intentional, auth edge cases, data loss risk).

QA Report:
"""

# ---------------------------------------------------------------------------
# Session detection — find the active OpenCode model without a Go key
# ---------------------------------------------------------------------------

def _read_opencode_config():
    """
    Read opencode.json from project dir, then global config.
    Returns the merged dict (project overrides global).
    """
    candidates = [
        os.path.join(PROJECT_DIR, "opencode.json"),
        os.path.expanduser("~/.config/opencode/opencode.json"),
    ]
    merged = {}
    for path in reversed(candidates):  # global first, project overrides
        if os.path.exists(path):
            try:
                with open(path) as f:
                    merged.update(json.load(f))
            except Exception:
                pass
    return merged

def _detect_session_model():
    """
    Determine the active provider/model string from OpenCode config.
    Returns (provider, model_id) or (None, None) if undetectable.

    Config priority mirrors OpenCode itself:
      project opencode.json > global opencode.json > last-used (not accessible here)
    """
    cfg = _read_opencode_config()
    model_str = cfg.get("model", "")  # format: "provider/model-id"

    if model_str and "/" in model_str:
        provider, model_id = model_str.split("/", 1)
        return provider.lower(), model_id

    # No explicit model set -- infer from which API keys are present in the environment.
    # OpenCode's own priority when auto-detecting: checks env vars in roughly this order.
    if OPENCODE_GO_API_KEY:
        return "opencode-go", "kimi-k2.5"
    if ANTHROPIC_API_KEY:
        return "anthropic", "claude-sonnet-4-20250514"
    if OPENAI_API_KEY:
        return "openai", "gpt-4o"
    if GEMINI_API_KEY:
        return "google", "gemini-2.0-flash"

    return None, None

def _resolve_triage_backend():
    """
    Resolve the triage backend to use. Returns a dict describing the chosen path.

    Priority:
      1. OPENCODE_GO_API_KEY present              -> Go endpoint
      2. Config model is opencode-go/*            -> Go endpoint (key required, warn if missing)
      3. Config model is anthropic/* + key        -> direct Anthropic
      4. Config model is openai/* + key           -> direct OpenAI
      5. Config model is google/* + key           -> direct Gemini (openai-compat)
      6. opencode binary available                -> delegate to opencode run (no --model override)
      7. Any known API key present                -> use that provider directly
      8. Fail with actionable message
    """
    # Explicit Go key always wins
    if OPENCODE_GO_API_KEY:
        model = TRIAGE_MODEL or "kimi-k2.5"
        return {"method": "go", "model": model, "label": f"OpenCode Go ({model})"}

    provider, model_id = _detect_session_model()

    # Go provider detected in config but no key
    if provider == "opencode-go":
        if OPENCODE_GO_API_KEY:
            model = TRIAGE_MODEL or model_id or "kimi-k2.5"
            return {"method": "go", "model": model, "label": f"OpenCode Go ({model})"}
        # fall through -- no key, try other paths

    # Direct Anthropic
    if provider == "anthropic" and ANTHROPIC_API_KEY:
        m = TRIAGE_MODEL or model_id or "claude-sonnet-4-20250514"
        return {"method": "anthropic", "model": m, "label": f"Anthropic ({m})"}

    # Direct OpenAI
    if provider == "openai" and OPENAI_API_KEY:
        m = TRIAGE_MODEL or model_id or "gpt-4o"
        return {"method": "openai", "model": m, "label": f"OpenAI ({m})"}

    # Direct Gemini via OpenAI-compat
    if provider == "google" and GEMINI_API_KEY:
        m = TRIAGE_MODEL or model_id or "gemini-2.0-flash"
        return {"method": "gemini", "model": m, "label": f"Gemini ({m})"}

    # Delegate to OpenCode binary -- let it use whatever it has configured
    if shutil.which("opencode"):
        model_hint = TRIAGE_MODEL or (f"{provider}/{model_id}" if provider else None)
        return {"method": "opencode_delegate", "model": model_hint, "label": f"OpenCode session ({model_hint or 'auto'})"}

    # Last resort: any key we have
    if ANTHROPIC_API_KEY:
        m = TRIAGE_MODEL or "claude-sonnet-4-20250514"
        return {"method": "anthropic", "model": m, "label": f"Anthropic fallback ({m})"}
    if OPENAI_API_KEY:
        m = TRIAGE_MODEL or "gpt-4o"
        return {"method": "openai", "model": m, "label": f"OpenAI fallback ({m})"}

    return {"method": "none", "model": None, "label": "none"}

# ---------------------------------------------------------------------------
# LLM backends
# ---------------------------------------------------------------------------

def call_triage_llm(report_context):
    backend = _resolve_triage_backend()
    print(f"[triage] Backend: {backend['label']}")

    if backend["method"] == "go":
        return _call_opencode_go(report_context, backend["model"])
    elif backend["method"] == "anthropic":
        return _call_anthropic(report_context, backend["model"])
    elif backend["method"] == "openai":
        return _call_openai(report_context, backend["model"])
    elif backend["method"] == "gemini":
        return _call_gemini(report_context, backend["model"])
    elif backend["method"] == "opencode_delegate":
        return _call_via_opencode_run(report_context, backend["model"])
    else:
        raise RuntimeError(
            "No usable LLM backend found for triage.\n"
            "Options:\n"
            "  - Set OPENCODE_GO_API_KEY for OpenCode Go\n"
            "  - Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY\n"
            "  - Ensure 'opencode' is in PATH (will delegate to session model)\n"
            "  - Set model in ~/.config/opencode/opencode.json"
        )

def _call_opencode_go(report_context, model):
    try:
        import openai
    except ImportError:
        os.system("pip install openai --quiet")
        import openai

    client = openai.OpenAI(api_key=OPENCODE_GO_API_KEY, base_url=OPENCODE_GO_BASE_URL)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": TRIAGE_PROMPT + report_context}],
        max_tokens=2000,
        temperature=0.2,
    )
    return _parse_json(response.choices[0].message.content.strip())

def _call_anthropic(report_context, model):
    try:
        import anthropic
    except ImportError:
        os.system("pip install anthropic --quiet")
        import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": TRIAGE_PROMPT + report_context}],
    )
    return _parse_json(msg.content[0].text.strip())

def _call_openai(report_context, model):
    try:
        import openai
    except ImportError:
        os.system("pip install openai --quiet")
        import openai

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": TRIAGE_PROMPT + report_context}],
        max_tokens=2000,
        temperature=0.2,
    )
    return _parse_json(response.choices[0].message.content.strip())

def _call_gemini(report_context, model):
    # Gemini supports OpenAI-compat endpoint
    try:
        import openai
    except ImportError:
        os.system("pip install openai --quiet")
        import openai

    client = openai.OpenAI(
        api_key=GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": TRIAGE_PROMPT + report_context}],
        max_tokens=2000,
        temperature=0.2,
    )
    return _parse_json(response.choices[0].message.content.strip())

def _call_via_opencode_run(report_context, model_hint):
    """
    Delegate triage to the active OpenCode session by calling:
      opencode run [--model <hint>] "<triage prompt>"

    Used when no direct API key is available but opencode is in PATH.
    OpenCode will use whatever provider/model it currently has configured.
    The response is expected to be JSON matching the task_list schema.
    """
    oc = shutil.which("opencode")
    prompt = TRIAGE_PROMPT + report_context

    # Write prompt to temp file to avoid shell quoting issues with large payloads
    prompt_file = os.path.join(REPORT_DIR, "triage-prompt.txt")
    with open(prompt_file, "w") as f:
        f.write(prompt)

    cmd = [oc, "run"]
    if model_hint:
        cmd += ["--model", model_hint]
    cmd += ["--print", f"$(cat {prompt_file})"]

    # Simpler and more reliable: pipe via stdin using shell
    cmd_str = f'{oc} run {"--model " + model_hint + " " if model_hint else ""}--print "$(cat {prompt_file})"'

    try:
        result = subprocess.run(
            cmd_str, shell=True, cwd=PROJECT_DIR,
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(f"opencode run failed (exit {result.returncode}): {result.stderr[:300]}")
        return _parse_json(result.stdout.strip())
    except subprocess.TimeoutExpired:
        raise RuntimeError("opencode run triage timed out after 120s")

def _parse_json(raw):
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ---------------------------------------------------------------------------
# Report context
# ---------------------------------------------------------------------------

def build_report_context(report):
    ctx = {
        "overall_status": report.get("overall_status"),
        "app_url": report.get("app_url"),
        "summary": report.get("summary"),
        "recommendations": report.get("recommendations", []),
        "server_log_tail": (report.get("server_log_tail") or "")[-2000:],
        "failed_routes": [r for r in report.get("crawl_results", []) if r.get("result") == "FAIL"],
        "failed_forms": [r for r in report.get("form_results", []) if r.get("result") == "FAIL"],
    }
    return json.dumps(ctx, indent=2)

# ---------------------------------------------------------------------------
# OpenCode CLI injection
# ---------------------------------------------------------------------------

def opencode_binary():
    return shutil.which("opencode")

def inject_to_opencode(task_list, run_id):
    """Inject fixable tasks into OpenCode via: opencode run --print "<spec>"."""
    oc = opencode_binary()
    if not oc:
        print("[triage] opencode not found in PATH -- skipping injection")
        return False

    fixable = [t for t in task_list if t.get("auto_fix", True) and meets_fix_threshold(t["severity"])]
    if not fixable:
        print("[triage] No auto-fixable tasks.")
        return False

    spec = format_opencode_spec(fixable, run_id)
    spec_path = os.path.join(REPORT_DIR, f"{run_id}-opencode-spec.txt")
    with open(spec_path, "w") as f:
        f.write(spec)

    backend = _resolve_triage_backend()
    print(f"\n[triage] Injecting {len(fixable)} tasks into OpenCode ({backend['label']})...")

    cmd = [oc, "run"]
    # Only pass --model if we have a specific model to target.
    # If backend is opencode_delegate, omit it and let the session model handle fixes too.
    if backend["method"] == "go" and backend.get("model"):
        cmd += ["--model", f"opencode-go/{backend['model']}"]
    elif backend["method"] not in ("opencode_delegate", "none") and backend.get("model"):
        # For direct providers, pass the full provider/model string
        provider_map = {"anthropic": "anthropic", "openai": "openai", "gemini": "google"}
        provider_id = provider_map.get(backend["method"], backend["method"])
        cmd += ["--model", f"{provider_id}/{backend['model']}"]
    # else: no --model flag, opencode uses whatever its session is configured with

    cmd += ["--print", spec]

    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=600
        )
        log_path = os.path.join(REPORT_DIR, f"{run_id}-opencode.log")
        with open(log_path, "w") as f:
            f.write(result.stdout + "\n--- STDERR ---\n" + result.stderr)

        if result.returncode == 0:
            print(f"[triage] OpenCode fix pass done. Log: {log_path}")
            return True
        else:
            print(f"[triage] OpenCode exited {result.returncode}. Log: {log_path}")
            return False
    except subprocess.TimeoutExpired:
        print("[triage] OpenCode timed out (10 min).")
        return False
    except Exception as e:
        print(f"[triage] Injection error: {e}")
        return False

# ---------------------------------------------------------------------------
# Recursive fix loop
# ---------------------------------------------------------------------------

def run_smoke_suite():
    """Re-run the full smoke suite (crawl -> forms -> report)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env = {**os.environ, "QA_PORT": QA_PORT, "QA_PROJECT_DIR": PROJECT_DIR}

    for script, label in [
        ("crawl.py",     "Crawl"),
        ("form_test.py", "Forms"),
        ("report.py",    "Report"),
    ]:
        path = os.path.join(script_dir, script)
        print(f"[loop]   Running {label}...")
        r = subprocess.run([sys.executable, path], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[loop]   {label} error: {r.stderr[-300:]}")

    with open(FINAL_REPORT) as f:
        return json.load(f)

def run_loop(warn_iterations=None):
    global FIX_SEVERITY  # recovery fix, see module docstring
    print(f"\n{'='*55}")
    print(f"RECURSIVE FIX LOOP — max {MAX_ITERATIONS} iterations | threshold: {FIX_SEVERITY}+")
    print(f"{'='*55}")

    history = []
    warned_already = False  # track whether we have prompted about WARN pass

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n--- Iteration {iteration}/{MAX_ITERATIONS} ---")

        with open(FINAL_REPORT) as f:
            report = json.load(f)

        run_id  = f"{report.get('qa_run_id', 'x')}-i{iteration}"
        overall = report.get("overall_status", "UNKNOWN")
        print(f"[loop] Status: {overall}")

        try:
            task_list = call_triage_llm(build_report_context(report))
        except Exception as e:
            print(f"[loop] Triage failed: {e}. Aborting.")
            break

        report["task_list"] = task_list
        report["opencode_task_spec"] = format_opencode_spec(
            [t for t in task_list if t.get("auto_fix", True) and meets_fix_threshold(t["severity"])],
            run_id
        )
        with open(FINAL_REPORT, "w") as f:
            json.dump(report, f, indent=2)

        fail_n = sum(1 for t in task_list if t["severity"] == "FAIL")
        warn_n = sum(1 for t in task_list if t["severity"] == "WARN")
        fixable = [t for t in task_list if t.get("auto_fix", True) and meets_fix_threshold(t["severity"])]

        history.append({
            "iteration": iteration, "run_id": run_id,
            "overall": overall, "fail": fail_n, "warn": warn_n,
        })

        write_markdown_tasks(task_list, run_id, overall)
        print(f"[loop] FAIL: {fail_n} | WARN: {warn_n} | Auto-fixable: {len(fixable)}")

        if not fixable:
            # FAILs (or current threshold) are clear.
            # Check if there are WARNs worth addressing before we celebrate.
            warn_tasks = [t for t in task_list if t["severity"] == "WARN" and t.get("auto_fix", True)]

            if not warn_tasks or FIX_SEVERITY == "WARN":
                # Nothing left at any level, or we were already running at WARN threshold
                print(f"\n✅ All issues resolved. Loop complete at iteration {iteration}.")
                break

            # FAILs are clear but WARNs remain. Decide whether to continue.
            print(f"\n✅ No FAIL issues remaining after iteration {iteration}.")
            print(f"   {len(warn_tasks)} WARN item(s) still present:")
            for t in warn_tasks[:5]:
                print(f"     [{t['task_id']}] {t['location']} — {t['symptom'][:80]}")
            if len(warn_tasks) > 5:
                print(f"     ... and {len(warn_tasks) - 5} more (see task list)")

            if warn_iterations is not None and not warned_already:
                # Caller specified up front how many WARN iterations to run
                warned_already = True
                remaining = MAX_ITERATIONS - iteration
                actual_warn_iters = min(warn_iterations, remaining)
                print(f"\n[loop] --warn-iterations {warn_iterations} specified. "
                      f"Continuing WARN pass for up to {actual_warn_iters} more iteration(s).")
                FIX_SEVERITY = "WARN"
                continue

            # Interactive prompt — only when attached to a real TTY
            if sys.stdin.isatty() and not warned_already:
                warned_already = True
                print(f"\nContinue into WARN fixes?")
                print(f"  [y]    Yes, fix WARNs (will run up to {MAX_ITERATIONS - iteration} more iteration(s))")
                print(f"  [N]    No, exit now (WARNs remain in task list for manual review)")
                print(f"  [1-9]  Yes, but limit to this many WARN iterations")
                try:
                    answer = input("  > ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = "n"

                if answer == "y":
                    FIX_SEVERITY = "WARN"
                    continue
                elif answer.isdigit() and 1 <= int(answer) <= 9:
                    warn_cap = int(answer)
                    warn_budget = [warn_cap]  # mutable for closure-like tracking

                    # Patch meets_fix_threshold temporarily for WARN
                    FIX_SEVERITY = "WARN"
                    print(f"[loop] Continuing with WARN fixes, capped at {warn_cap} iteration(s).")

                    # Run the requested number of WARN iterations inline
                    for w_iter in range(warn_cap):
                        print(f"\n--- WARN iteration {w_iter + 1}/{warn_cap} ---")
                        with open(FINAL_REPORT) as f2:
                            w_report = json.load(f2)
                        w_run_id = f"{w_report.get('qa_run_id', 'x')}-w{w_iter + 1}"
                        try:
                            w_tasks = call_triage_llm(build_report_context(w_report))
                        except Exception as e2:
                            print(f"[loop] WARN triage failed: {e2}")
                            break
                        w_fixable = [t for t in w_tasks if t.get("auto_fix", True) and t["severity"] == "WARN"]
                        if not w_fixable:
                            print("✅ No WARN issues remaining.")
                            break
                        history.append({
                            "iteration": f"W{w_iter+1}", "run_id": w_run_id,
                            "overall": w_report.get("overall_status"),
                            "fail": 0,
                            "warn": len(w_fixable),
                        })
                        w_ok = inject_to_opencode(w_tasks, w_run_id)
                        if not w_ok:
                            break
                        time.sleep(2)
                        run_smoke_suite()
                    break  # done with main loop after WARN pass

                else:
                    print("[loop] Skipping WARN fixes. Task list preserved for manual review.")
                    break
            else:
                # Non-interactive (CI, piped input) — exit cleanly, don't block
                print("[loop] Non-interactive mode. Stopping after FAILs cleared.")
                print(f"       Re-run with --severity WARN or --warn-iterations N to address WARNs.")
                break

        ok = inject_to_opencode(task_list, run_id)
        if not ok:
            print("[loop] Injection failed. Aborting.")
            break

        # Archive iteration snapshot
        archive = os.path.join(REPORT_DIR, f"iteration-{iteration:02d}.json")
        with open(FINAL_REPORT) as f, open(archive, "w") as af:
            af.write(f.read())

        time.sleep(2)
        print(f"[loop] Re-running smoke suite...")
        run_smoke_suite()

    else:
        print(f"\n⚠️  Max iterations ({MAX_ITERATIONS}) reached. Review required.")

    history_path = os.path.join(REPORT_DIR, "loop-history.json")
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    print(f"\n{'='*55}\nLOOP SUMMARY")
    for h in history:
        print(f"  i{h['iteration']:02d} | {h['overall']:5s} | FAIL:{h['fail']} WARN:{h['warn']}")
    print(f"{'='*55}\n")
    return history

# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def format_opencode_spec(fixable_tasks, run_id):
    if not fixable_tasks:
        return f"QA run {run_id}: No issues to fix."

    lines = [
        f"Fix the following bugs identified by automated smoke QA (run: {run_id}).",
        f"Fix FAIL items first, then WARN. Do NOT refactor or add features.",
        f"Fix only what is listed. After each fix, verify adjacent functionality is intact.",
        "",
    ]
    for t in fixable_tasks:
        lines.append(f"[{t['severity']}] {t['task_id']} -- {t['location']}")
        lines.append(f"  Symptom:  {t['symptom']}")
        lines.append(f"  Fix:      {t['fix_instruction']}")
        if t.get("evidence"):
            lines.append(f"  Evidence: {'; '.join(str(e) for e in t['evidence'][:2])}")
        lines.append("")
    return "\n".join(lines)

def write_markdown_tasks(task_list, run_id, overall):
    lines = [
        "# QA Smoke Test — Task List",
        f"**Run:** {run_id}  **Status:** {overall}  **Threshold:** {FIX_SEVERITY}+",
        f"**Generated:** {datetime.utcnow().isoformat()}Z",
        "",
    ]
    for sev, label in [("FAIL", "🔴 FAIL"), ("WARN", "🟡 WARN"), ("INFO", "ℹ️ INFO")]:
        items = [t for t in task_list if t["severity"] == sev]
        if not items:
            continue
        lines += [f"## {label} ({len(items)})", ""]
        for t in items:
            badge = "auto-fix ✅" if t.get("auto_fix", True) else "manual 🔒"
            lines += [
                f"### {t['task_id']} `{badge}` — {t['location']}",
                f"**Symptom:** {t['symptom']}",
                f"**Cause:** {t['probable_cause']}",
                f"**Fix:** {t['fix_instruction']}",
                "",
            ]
    md_path = os.path.join(REPORT_DIR, f"{run_id}-tasks.md")
    with open(md_path, "w") as f:
        f.write("\n".join(lines))
    return md_path

# ---------------------------------------------------------------------------
# Single triage pass
# ---------------------------------------------------------------------------

def run_triage():
    try:
        with open(FINAL_REPORT) as f:
            report = json.load(f)
    except Exception as e:
        sys.exit(f"ERROR: Cannot load {FINAL_REPORT}: {e}")

    run_id  = report.get("qa_run_id", "unknown")
    overall = report.get("overall_status", "UNKNOWN")
    print(f"[triage] Run: {run_id} | Status: {overall}")

    try:
        task_list = call_triage_llm(build_report_context(report))
    except Exception as e:
        print(f"[triage] LLM failed: {e} -- using fallback")
        task_list = [
            {
                "task_id": f"T{i+1:02d}",
                "severity": "FAIL" if any(k in r for k in ["crash", "500", "TypeError"]) else "WARN",
                "location": r.split("--")[0].strip() if "--" in r else "unknown",
                "symptom": r, "probable_cause": "See report",
                "fix_instruction": r, "evidence": [], "auto_fix": True,
            }
            for i, r in enumerate(report.get("recommendations", []))
            if r != "No critical issues found."
        ]

    fixable = [t for t in task_list if t.get("auto_fix", True) and meets_fix_threshold(t["severity"])]
    spec    = format_opencode_spec(fixable, run_id)

    report["task_list"] = task_list
    report["opencode_task_spec"] = spec
    with open(FINAL_REPORT, "w") as f:
        json.dump(report, f, indent=2)

    md_path   = write_markdown_tasks(task_list, run_id, overall)
    spec_path = os.path.join(REPORT_DIR, f"{run_id}-opencode-spec.txt")
    with open(spec_path, "w") as f:
        f.write(spec)

    fail_n = sum(1 for t in task_list if t["severity"] == "FAIL")
    warn_n = sum(1 for t in task_list if t["severity"] == "WARN")
    print(f"[triage] {len(task_list)} tasks | FAIL:{fail_n} WARN:{warn_n} | Auto-fixable:{len(fixable)}")
    print(f"  Tasks (md):    {md_path}")
    print(f"  OpenCode spec: {spec_path}")
    if spec.strip():
        print(f"\n--- OpenCode Task Spec ---\n{spec}\n--------------------------\n")

    return task_list

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--loop",        action="store_true", help="Recursive fix loop: triage -> inject -> re-smoke -> repeat")
    p.add_argument("--inject-only", action="store_true", help="Triage and inject to OpenCode, skip re-smoke")
    p.add_argument("--severity",      choices=["FAIL", "WARN"], default=FIX_SEVERITY,
                   help="Minimum severity to auto-fix (default: FAIL)")
    p.add_argument("--warn-iterations", type=int, default=None, metavar="N",
                   help="After FAILs clear, automatically continue into WARN fixes for N more iterations (skips prompt)")
    args = p.parse_args()

    FIX_SEVERITY = args.severity

    if args.loop:
        run_loop(warn_iterations=args.warn_iterations)
    elif args.inject_only:
        tasks = run_triage()
        with open(FINAL_REPORT) as f:
            report = json.load(f)
        inject_to_opencode(tasks, report.get("qa_run_id", "unknown"))
    else:
        run_triage()
