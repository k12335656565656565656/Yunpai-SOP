from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8787/?route=1"
SCREENSHOT = Path(".tmp/local-runtime/v5-operating-method-editor.png")


def main() -> None:
    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
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

        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => documentInfo?.template_id === 'yunpai.sop.hdmi-cable.multi-page.v5'",
            timeout=120_000,
        )
        page.evaluate("() => navigatePreviewPage(2)")
        page.wait_for_function(
            "() => document.querySelector('.doc-page[data-page-number=\"2\"] img')?.dataset.loadState === 'loaded'",
            timeout=60_000,
        )
        page.locator("#pageEditToggle").click()
        page.wait_for_selector('.doc-page[data-page-number="2"].editing-page')

        operating_zone = page.locator(
            '.doc-page[data-page-number="2"] .page-edit-zone[data-label="作业方法"]'
        )
        assert operating_zone.count() == 1
        assert page.locator(
            '.doc-page[data-page-number="2"] .page-edit-zone[data-label="工序动作"]'
        ).count() == 0
        assert page.locator(
            '.doc-page[data-page-number="2"] .page-edit-zone[data-label="作业目的"]'
        ).count() == 0

        textarea = operating_zone.locator("textarea")
        original = textarea.input_value()
        assert "工序动作：" in original
        assert "作业目的：" in original
        assert "1. " in original
        operating_zone.click()
        textarea.wait_for(state="visible")
        textarea.fill(original + "\n6. 临时浏览器验证")
        assert page.locator("#pageEditDirty").is_visible()

        page.locator('.doc-page[data-page-number="2"]').screenshot(path=str(SCREENSHOT))
        page.locator("#pageEditUndo").click()
        assert textarea.input_value() == original
        page.locator("#pageEditCancel").click()
        browser.close()

    errors = {
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_responses": failed_responses,
    }
    errors = {key: value for key, value in errors.items() if value}
    assert not errors, json.dumps(errors, ensure_ascii=False)
    print(
        json.dumps(
            {"operating_method_editor": "ok", "screenshot": str(SCREENSHOT.resolve())},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
