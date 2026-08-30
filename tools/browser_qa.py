from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright


def forward_api(route, base_url: str):
    request = route.request
    path = request.url.split("voodoo.invalid", 1)[-1]
    target = base_url.rstrip("/") + path
    data = request.post_data.encode("utf-8") if request.post_data else None
    req = urllib.request.Request(target, data=data, method=request.method)
    for key, value in request.headers.items():
        if key.lower() in {"content-type", "accept"}:
            req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            route.fulfill(status=resp.status, content_type=resp.headers.get_content_type(), body=resp.read())
    except urllib.error.HTTPError as exc:
        route.fulfill(status=exc.code, content_type="application/json", body=exc.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8787")
    ap.add_argument("--screenshot", default="evidence/control-room.png")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    html = (root / "web/index.html").read_text(encoding="utf-8")
    css = (root / "web/styles.css").read_text(encoding="utf-8")
    js = (root / "web/app.js").read_text(encoding="utf-8")
    html = re.sub(r'<link[^>]+href="/styles.css"[^>]*>', "", html)
    html = re.sub(r'<script[^>]+src="/app.js"[^>]*></script>', "", html)
    html = html.replace("<head>", '<head><base href="https://voodoo.invalid/">', 1)

    console_errors = []
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path="/usr/bin/chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-features=UseDBus"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.route("https://voodoo.invalid/api/**", lambda route: forward_api(route, args.url))
        page.set_content(html, wait_until="domcontentloaded")
        page.add_style_tag(content=css)
        page.add_script_tag(content=js)
        page.wait_for_function("document.querySelector('#health').textContent !== 'RUNTIME CHECKING'")
        results["title"] = page.title()
        results["health"] = page.locator("#health").inner_text()
        page.locator("#planBtn").click()
        page.wait_for_function("document.querySelector('#planStatus').textContent !== 'UNKNOWN'")
        results["plan_status"] = page.locator("#planStatus").inner_text()
        results["stages"] = page.locator(".stage").count()
        views = ["runs", "plans", "capabilities", "learning", "evidence", "verifier", "policies", "runtime", "settings", "command"]
        for view in views:
            page.locator(f'button[data-view="{view}"]').click()
            page.wait_for_timeout(150)
            results[f"view_{view}"] = page.locator(f"#view-{view}").is_visible()
        results["capability_cards"] = page.locator("#capabilitiesContent .cap-card").count()
        results["evidence_events"] = page.locator("#evidenceContent .timeline-row").count()
        results["dag_nodes_contained"] = page.evaluate("""() => {
          const host = document.querySelector('.dag-card').getBoundingClientRect();
          return [...document.querySelectorAll('.dag .node-card')].every(n => {
            const r = n.getBoundingClientRect();
            return r.left >= host.left && r.right <= host.right;
          });
        }""")
        results["desktop_overflow"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(120)
        results["mobile_overflow"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        page.set_viewport_size({"width": 1440, "height": 1000})
        Path(args.screenshot).parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=args.screenshot, full_page=True)
        browser.close()
    results["console_errors"] = console_errors
    passed = (
        results["title"] == "VOODOO / SKILLSET"
        and results["health"] == "RUNTIME HEALTHY"
        and results["plan_status"] == "VERIFIED_PLAN"
        and results["stages"] > 0
        and all(results[f"view_{v}"] for v in views)
        and results["capability_cards"] >= 10
        and results["evidence_events"] >= 4
        and results["dag_nodes_contained"]
        and not results["desktop_overflow"]
        and not results["mobile_overflow"]
        and not console_errors
    )
    print(json.dumps({"status": "PASS" if passed else "FAIL", "transport": "PLAYWRIGHT_RENDER_WITH_LOCAL_API_BRIDGE", **results}, indent=2))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
