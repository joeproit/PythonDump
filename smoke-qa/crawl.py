#!/usr/bin/env python3
"""
opencode-smoke-qa: Crawl Phase
Standalone script. Set PORT and BASE_URL before running.

Recovered 2026-11-21 from the March 2026 build chat (retyped from the recorded file, then run end to end).
"""

import json, os, uuid, sys
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- CONFIG ---
PORT = int(os.environ.get("QA_PORT", 3000))
BASE_URL = os.environ.get("QA_BASE_URL", f"http://localhost:{PORT}")
MAX_PAGES = int(os.environ.get("QA_MAX_PAGES", 50))
MAX_DEPTH = int(os.environ.get("QA_MAX_DEPTH", 3))
SCREENSHOT_DIR = os.environ.get("QA_SCREENSHOT_DIR", "/tmp/qa-screenshots")
REPORT_OUT = os.environ.get("QA_REPORT_OUT", "/tmp/qa-crawl-report.json")

BENIGN_PATTERNS = [
    "Download the React DevTools", "[HMR]", "webpack",
    "Fast Refresh", "vite", "[vue/", "ReactDOM.render",
]

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def is_benign(text):
    return any(p.lower() in text.lower() for p in BENIGN_PATTERNS)

def run_crawl():
    report = {
        "qa_run_id": str(uuid.uuid4())[:8],
        "timestamp": datetime.utcnow().isoformat(),
        "base_url": BASE_URL,
        "crawl_results": [],
        "summary": {}
    }

    console_errors = []
    network_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )
        page = context.new_page()

        page.on("console", lambda msg: console_errors.append({
            "type": msg.type, "text": msg.text, "page_url": page.url
        }) if msg.type in ("error", "warning") and not is_benign(msg.text) else None)

        page.on("requestfailed", lambda req: network_errors.append({
            "url": req.url, "failure": req.failure, "page_url": page.url
        }))

        visited = set()
        queue = [(BASE_URL, 0)]

        while queue and len(visited) < MAX_PAGES:
            url, depth = queue.pop(0)
            norm_url = url.rstrip("/")
            if norm_url in visited or depth > MAX_DEPTH:
                continue
            visited.add(norm_url)

            result = {"url": url, "depth": depth, "result": "PASS"}

            try:
                errors_before = len(console_errors)
                response = page.goto(url, wait_until="networkidle", timeout=12000)
                status = response.status if response else 0

                title = page.title()
                body_text = page.inner_text("body").strip()
                is_blank = len(body_text) < 20

                slug = url.replace(BASE_URL, "").replace("/", "_").strip("_") or "root"
                shot_path = f"{SCREENSHOT_DIR}/{slug[:60]}.png"
                page.screenshot(path=shot_path, full_page=True)

                page_errors = [e for e in console_errors[errors_before:] if e.get("page_url") == url]

                result.update({
                    "status": status,
                    "title": title,
                    "blank_page": is_blank,
                    "console_errors": page_errors,
                    "screenshot": shot_path,
                })

                if status >= 400 or is_blank:
                    result["result"] = "FAIL"
                    result["failure_reason"] = f"HTTP {status}" if status >= 400 else "Blank page"

                # Enqueue links
                if depth < MAX_DEPTH:
                    try:
                        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                        for link in links:
                            if link.startswith(BASE_URL) and link.rstrip("/") not in visited:
                                if "logout" not in link and "signout" not in link:
                                    queue.append((link, depth + 1))
                    except Exception:
                        pass

            except Exception as e:
                result.update({
                    "status": 0,
                    "error": str(e),
                    "result": "FAIL",
                    "failure_reason": f"Exception: {str(e)[:100]}"
                })

            report["crawl_results"].append(result)
            print(f"[{'OK' if result['result'] == 'PASS' else 'FAIL'}] {url} ({result.get('status', '?')})")

        browser.close()

    # Summary
    total = len(report["crawl_results"])
    failed = sum(1 for r in report["crawl_results"] if r["result"] == "FAIL")
    report["summary"] = {
        "total_routes": total,
        "passed": total - failed,
        "failed": failed,
        "network_errors": len(network_errors),
        "overall": "PASS" if failed == 0 else "FAIL"
    }
    report["network_errors"] = network_errors

    with open(REPORT_OUT, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n--- Crawl Complete ---")
    print(f"Routes: {total} | Pass: {total - failed} | Fail: {failed}")
    print(f"Report: {REPORT_OUT}")
    print(f"Screenshots: {SCREENSHOT_DIR}")

    return report

if __name__ == "__main__":
    run_crawl()
