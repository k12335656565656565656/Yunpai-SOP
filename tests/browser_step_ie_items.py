from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8787/"
OUTPUT_DIR = Path(__file__).resolve().parent / "screenshots" / "step-ie-items-20260821"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    console_issues: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[str] = []

    failure = ""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on(
            "console",
            lambda message: console_issues.append(f"{message.type}: {message.text}")
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "response",
            lambda response: failed_responses.append(f"{response.status} {response.url}")
            if response.status >= 400
            else None,
        )
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => typeof routePayload !== 'undefined' && routePayload !== null && routePayload.steps.length > 0",
                timeout=45_000,
            )
            page.locator("#routeMode").click()
            page.locator(".route-row .route-more").first.wait_for(state="visible")
            page.screenshot(path=OUTPUT_DIR / "01-route-editor.png", full_page=True)

            page.locator(".route-row .route-more").first.click()
            page.get_by_role("button", name="IE 项目", exact=True).click()
            page.get_by_role("heading", name="编辑 IE 项目").wait_for(state="visible")
            page.screenshot(path=OUTPUT_DIR / "02-ie-items-empty-or-existing.png", full_page=True)

            dialog = page.locator(".route-dialog")
            assert dialog.get_by_role("button", name="＋ 新增 IE 项目").is_visible()
            assert "动作名称必须填写" in dialog.inner_text()
            assert not page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
        except Exception as exc:
            failure = str(exc)
            page.screenshot(path=OUTPUT_DIR / "failure.png", full_page=True)
        finally:
            browser.close()

    report = {
        "screenshots": str(OUTPUT_DIR),
        "console_issues": console_issues,
        "page_errors": page_errors,
        "failed_responses": failed_responses,
        "failure": failure,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failure or console_issues or page_errors or failed_responses:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
