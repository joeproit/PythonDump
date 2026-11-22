#!/usr/bin/env python3
"""
opencode-smoke-qa: Form Interaction Phase
Run after crawl.py. Reads crawl report to get URLs, tests all forms found.

Recovered 2026-11-21 from the March 2026 build chat (retyped from the recorded file, then run end to end).
"""

import json, os, uuid
from datetime import datetime
from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("QA_PORT", 3000))
BASE_URL = os.environ.get("QA_BASE_URL", f"http://localhost:{PORT}")
CRAWL_REPORT = os.environ.get("QA_CRAWL_REPORT", "/tmp/qa-crawl-report.json")
REPORT_OUT = os.environ.get("QA_FORM_REPORT", "/tmp/qa-form-report.json")

FIXTURES = {
    "email":    "qa-test@example.com",
    "password": "TestPass123!",
    "text":     "QA Smoke Test",
    "search":   "test query",
    "url":      "https://example.com",
    "number":   "42",
    "textarea": "QA smoke test submission. Ignore this.",
    "tel":      "555-867-5309",
    "date":     "2024-01-15",
    "time":     "10:00",
    "range":    "50",
}

ADVERSARIAL_CASES = [
    ("empty_submit", {}),
    ("oversized_text", {"text": "A" * 5000, "email": "a" * 200 + "@x.com"}),
    ("xss_string", {"text": "<script>alert(1)</script>", "email": "t@t.com"}),
    ("invalid_email", {"email": "notanemail", "text": "test"}),
]

def get_urls_from_crawl():
    try:
        with open(CRAWL_REPORT) as f:
            data = json.load(f)
        return [r["url"] for r in data["crawl_results"] if r.get("status", 0) < 400]
    except Exception:
        return [BASE_URL]

def test_url_forms(page, url, console_errors):
    results = []
    try:
        page.goto(url, wait_until="networkidle", timeout=10000)
    except Exception as e:
        return [{"url": url, "error": str(e), "result": "SKIP"}]

    forms = page.query_selector_all("form")
    if not forms:
        return []

    for i, _ in enumerate(forms):
        # Normal fill + submit
        page.goto(url, wait_until="networkidle", timeout=8000)
        forms = page.query_selector_all("form")
        if i >= len(forms):
            continue
        form = forms[i]

        form_result = {
            "url": url, "form_index": i,
            "fields_filled": [], "result": "PASS"
        }

        inputs = form.query_selector_all("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset])")
        for inp in inputs:
            itype = inp.get_attribute("type") or "text"
            val = FIXTURES.get(itype, FIXTURES["text"])
            try:
                inp.fill(val)
                form_result["fields_filled"].append({"type": itype})
            except Exception:
                pass

        for ta in form.query_selector_all("textarea"):
            try:
                ta.fill(FIXTURES["textarea"])
            except Exception:
                pass

        for sel in form.query_selector_all("select"):
            try:
                opts = sel.query_selector_all("option:not([disabled]):not([value=''])")
                if opts:
                    sel.select_option(index=0)
            except Exception:
                pass

        errors_before = len(console_errors)
        try:
            submit = form.query_selector("[type=submit]") or form.query_selector("button:not([type=button])")
            if submit:
                submit.click()
                page.wait_for_load_state("networkidle", timeout=5000)

            new_errs = [e for e in console_errors[errors_before:] if e["type"] == "error"]
            form_result["post_url"] = page.url
            form_result["js_errors"] = new_errs
            if new_errs:
                form_result["result"] = "FAIL"
                form_result["failure_reason"] = f"{len(new_errs)} JS errors on submit"
        except Exception as e:
            form_result["result"] = "FAIL"
            form_result["failure_reason"] = str(e)

        results.append(form_result)

        # Adversarial cases
        for case_name, overrides in ADVERSARIAL_CASES:
            try:
                page.goto(url, wait_until="networkidle", timeout=6000)
                forms = page.query_selector_all("form")
                if i >= len(forms):
                    continue
                form = forms[i]

                inputs = form.query_selector_all("input:not([type=hidden]):not([type=submit])")
                for inp in inputs:
                    itype = inp.get_attribute("type") or "text"
                    val = overrides.get(itype, overrides.get("text", ""))
                    try:
                        inp.fill(val)
                    except Exception:
                        pass

                errors_before = len(console_errors)
                submit = form.query_selector("[type=submit]") or form.query_selector("button")
                if submit:
                    submit.click()
                    page.wait_for_load_state("networkidle", timeout=3000)

                new_errs = [e for e in console_errors[errors_before:] if e["type"] == "error"]
                adv_result = "FAIL" if new_errs else "PASS"

                results.append({
                    "url": url, "form_index": i,
                    "adversarial_case": case_name,
                    "result": adv_result,
                    "js_errors": new_errs,
                })
            except Exception as e:
                results.append({
                    "url": url, "form_index": i,
                    "adversarial_case": case_name,
                    "result": "FAIL",
                    "error": str(e)[:100],
                })

    return results

def run_form_tests():
    urls = get_urls_from_crawl()
    all_results = []
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
        page = context.new_page()
        page.on("console", lambda msg: console_errors.append({
            "type": msg.type, "text": msg.text
        }) if msg.type in ("error", "warning") else None)

        for url in urls:
            url_results = test_url_forms(page, url, console_errors)
            if url_results:
                print(f"[FORMS] {url}: {len(url_results)} interactions")
            all_results.extend(url_results)

        browser.close()

    total = len([r for r in all_results if "adversarial_case" not in r])
    failed = sum(1 for r in all_results if r["result"] == "FAIL" and "adversarial_case" not in r)

    report = {
        "qa_run_id": str(uuid.uuid4())[:8],
        "timestamp": datetime.utcnow().isoformat(),
        "form_results": all_results,
        "summary": {
            "total_form_interactions": total,
            "failed": failed,
            "adversarial_cases_run": len([r for r in all_results if "adversarial_case" in r]),
            "overall": "PASS" if failed == 0 else "FAIL"
        }
    }

    with open(REPORT_OUT, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n--- Form Tests Complete ---")
    print(f"Interactions: {total} | Failed: {failed}")
    print(f"Report: {REPORT_OUT}")
    return report

if __name__ == "__main__":
    run_form_tests()
