from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8787/?route=1"


def main() -> None:
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
        page.fill("#worker", "scroll-edit-review")
        page.click("#pageEditToggle")
        page.wait_for_selector('.doc-page[data-page-number="2"].editing-page')

        page.locator('.doc-page[data-page-number="3"]').scroll_into_view_if_needed()
        page.wait_for_function("() => currentPreviewPage === 3", timeout=10_000)
        switched = page.evaluate(
            """() => ({
                currentPage: currentPreviewPage,
                editStatePage: pageEditState?.page || null,
                editingPages: [...document.querySelectorAll('.doc-page.editing-page')]
                    .map(node => Number(node.dataset.pageNumber)),
                page3Zones: document.querySelectorAll(
                    '.doc-page[data-page-number="3"] .page-edit-zone'
                ).length,
            })"""
        )

        page.locator('.doc-page[data-page-number="3"] textarea').first.evaluate(
            """input => {
                input.value += ' 临时修改';
                input.dispatchEvent(new Event('input', {bubbles: true}));
            }"""
        )
        page.locator('.doc-page[data-page-number="4"]').scroll_into_view_if_needed()
        page.wait_for_function("() => currentPreviewPage === 4", timeout=10_000)
        protected = page.evaluate(
            """() => ({
                currentPage: currentPreviewPage,
                editStatePage: pageEditState?.page || null,
                dirty: Boolean(pageEditState?.dirty),
                editingPages: [...document.querySelectorAll('.doc-page.editing-page')]
                    .map(node => Number(node.dataset.pageNumber)),
                page4Zones: document.querySelectorAll(
                    '.doc-page[data-page-number="4"] .page-edit-zone'
                ).length,
            })"""
        )
        page.click("#pageEditUndo")
        page.wait_for_function("() => pageEditState?.page === 4", timeout=10_000)
        resumed = page.evaluate(
            """() => ({
                currentPage: currentPreviewPage,
                editStatePage: pageEditState?.page || null,
                dirty: Boolean(pageEditState?.dirty),
                editingPages: [...document.querySelectorAll('.doc-page.editing-page')]
                    .map(node => Number(node.dataset.pageNumber)),
                page4Zones: document.querySelectorAll(
                    '.doc-page[data-page-number="4"] .page-edit-zone'
                ).length,
            })"""
        )
        browser.close()

    expected_switched = {
        "currentPage": 3,
        "editStatePage": 3,
        "editingPages": [3],
    }
    errors = {
        f"switched.{key}": {"actual": switched[key], "expected": value}
        for key, value in expected_switched.items()
        if switched[key] != value
    }
    if switched["page3Zones"] < 10:
        errors["switched.page3Zones"] = {"actual": switched["page3Zones"], "expected": ">= 10"}
    expected_protected = {
        "currentPage": 4,
        "editStatePage": 3,
        "dirty": True,
        "editingPages": [3],
        "page4Zones": 0,
    }
    expected_resumed = {
        "currentPage": 4,
        "editStatePage": 4,
        "dirty": False,
        "editingPages": [4],
    }
    for stage, actual, expected in (
        ("protected", protected, expected_protected),
        ("resumed", resumed, expected_resumed),
    ):
        for key, value in expected.items():
            if actual[key] != value:
                errors[f"{stage}.{key}"] = {"actual": actual[key], "expected": value}
    if resumed["page4Zones"] < 10:
        errors["resumed.page4Zones"] = {"actual": resumed["page4Zones"], "expected": ">= 10"}
    result = {"switched": switched, "protected": protected, "resumed": resumed}
    if console_errors:
        errors["console_errors"] = console_errors
    if page_errors:
        errors["page_errors"] = page_errors
    if failed_responses:
        errors["failed_responses"] = failed_responses
    assert not errors, json.dumps({"errors": errors, "result": result}, ensure_ascii=False)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
