#!/usr/bin/env python3
"""
opencode-smoke-qa: Report Compiler
Merges crawl and form reports into a single QA handoff JSON.
Generates human-readable summary and OpenCode-ready recommendations.

Recovered 2026-11-21 from the March 2026 build chat (retyped from the recorded file, then run end to end).
"""

import json, os, sys
from datetime import datetime

CRAWL_REPORT = os.environ.get("QA_CRAWL_REPORT", "/tmp/qa-crawl-report.json")
FORM_REPORT = os.environ.get("QA_FORM_REPORT", "/tmp/qa-form-report.json")
FINAL_REPORT = os.environ.get("QA_FINAL_REPORT", "/tmp/qa-final-report.json")
SERVER_LOG = os.environ.get("QA_SERVER_LOG", "/tmp/qa-server.log")

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def tail(path, lines=30):
    try:
        with open(path) as f:
            return "\n".join(f.readlines()[-lines:])
    except Exception:
        return ""

def generate_recommendations(crawl, forms):
    recs = []

    # Crawl failures
    for r in crawl.get("crawl_results", []):
        if r.get("result") == "FAIL":
            reason = r.get("failure_reason", "unknown failure")
            recs.append(f"Route {r['url']} — {reason}")
        if r.get("console_errors"):
            for e in r["console_errors"][:2]:
                recs.append(f"JS error at {r['url']}: {e['text'][:120]}")

    # Form failures
    for r in forms.get("form_results", []):
        if r.get("result") == "FAIL" and "adversarial_case" not in r:
            reason = r.get("failure_reason", r.get("error", "unknown"))
            recs.append(f"Form #{r.get('form_index', '?')} at {r['url']} — {reason}")
        if r.get("adversarial_case") and r.get("result") == "FAIL":
            recs.append(f"Adversarial case '{r['adversarial_case']}' crashed form at {r['url']}")

    return recs if recs else ["No critical issues found."]

def compile():
    crawl = load_json(CRAWL_REPORT)
    forms = load_json(FORM_REPORT)

    c_summary = crawl.get("summary", {})
    f_summary = forms.get("summary", {})

    recs = generate_recommendations(crawl, forms)

    # Determine overall status
    if c_summary.get("overall") == "FAIL" or f_summary.get("overall") == "FAIL":
        overall = "FAIL"
    elif recs != ["No critical issues found."]:
        overall = "WARN"
    else:
        overall = "PASS"

    final = {
        "qa_run_id": crawl.get("qa_run_id", "unknown"),
        "timestamp": datetime.utcnow().isoformat(),
        "app_url": crawl.get("base_url", "unknown"),
        "overall_status": overall,
        "summary": {
            "routes_total": c_summary.get("total_routes", 0),
            "routes_passed": c_summary.get("passed", 0),
            "routes_failed": c_summary.get("failed", 0),
            "forms_tested": f_summary.get("total_form_interactions", 0),
            "forms_failed": f_summary.get("failed", 0),
            "adversarial_cases": f_summary.get("adversarial_cases_run", 0),
            "network_errors": c_summary.get("network_errors", 0),
        },
        "crawl_results": crawl.get("crawl_results", []),
        "form_results": forms.get("form_results", []),
        "recommendations": recs,
        "server_log_tail": tail(SERVER_LOG),
    }

    with open(FINAL_REPORT, "w") as f:
        json.dump(final, f, indent=2)

    # Terminal summary
    s = final["summary"]
    print(f"\n{'='*50}")
    print(f"QA SMOKE TEST REPORT — {final['qa_run_id']}")
    print(f"Status: {overall}")
    print(f"{'='*50}")
    print(f"Routes:  {s['routes_passed']}/{s['routes_total']} passed")
    print(f"Forms:   {s['forms_tested'] - s['forms_failed']}/{s['forms_tested']} passed")
    print(f"Network: {s['network_errors']} errors")
    print(f"\nRecommendations ({len(recs)}):")
    for i, r in enumerate(recs, 1):
        print(f"  {i}. {r}")
    print(f"\nFull report: {FINAL_REPORT}")
    print(f"{'='*50}\n")

    return final

if __name__ == "__main__":
    compile()
