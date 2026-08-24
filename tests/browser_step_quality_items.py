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
            if message.type in {"error", "warning"}
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
        target = page.evaluate(
            """() => {
                const columns = [
                    'quality_check_json',
                    'acceptance_criteria_json',
                    'tool_equipment_json',
                    'fixture_json',
                ];
                const index = routePayload.steps.findIndex(step =>
                    Math.max(...columns.map(key => Array.isArray(step[key]) ? step[key].length : 0)) < 6
                );
                const safeIndex = index >= 0 ? index : 0;
                return {id: routePayload.steps[safeIndex].id, page: safeIndex + 2};
            }"""
        )

        page.locator("#routeMode").click()
        row = page.locator(f'.route-row[data-step-id="{target["id"]}"]')
        row.locator(".route-more").click()
        page.get_by_role("button", name="品质项目", exact=True).click()
        page.get_by_role("heading", name="编辑品质项目").wait_for(state="visible")
        dialog = page.locator(".route-dialog")
        add = dialog.get_by_role("button", name="＋ 新增品质项目")
        assert add.is_visible() and add.is_enabled()

        add.click()
        dialog.locator('[data-quality-field="control_point"]').fill("检查标签内容")
        dialog.locator('[data-quality-field="acceptance"]').fill("型号和工单一致")
        dialog.locator('[data-quality-field="tool"]').fill("扫码枪")
        dialog.locator('[data-quality-field="fixture"]').fill("定位治具")
        dialog.get_by_role("button", name="删除此项").click()
        restore = dialog.get_by_role("button", name="恢复")
        assert restore.is_visible()
        restore.click()
        assert dialog.locator('[data-quality-field="control_point"]').input_value() == "检查标签内容"
        assert dialog.locator('[data-quality-field="acceptance"]').input_value() == "型号和工单一致"
        assert dialog.locator('[data-quality-field="tool"]').input_value() == "扫码枪"
        assert dialog.locator('[data-quality-field="fixture"]').input_value() == "定位治具"
        dialog.get_by_role("button", name="取消").click()

        page.evaluate(f"() => navigatePreviewPage({target['page']})")
        page.wait_for_function(
            f"() => document.querySelector('.doc-page[data-page-number=\"{target['page']}\"] img')?.dataset.loadState === 'loaded'",
            timeout=60_000,
        )
        page.locator("#pageEditToggle").click()
        page.wait_for_function(
            f"() => pageEditState?.page === {target['page']} && document.querySelector('.doc-page[data-page-number=\"{target['page']}\"]')?.classList.contains('editing-page')"
        )
        quality_zone = page.locator(
            f'.doc-page[data-page-number="{target["page"]}"] .page-edit-zone[data-label="品质项目"]'
        )
        quality_zone.get_by_role("button", name="编辑品质项目").click()
        page.get_by_role("heading", name="编辑品质项目").wait_for(state="visible")
        assert dialog.get_by_role("button", name="＋ 新增品质项目").is_visible()
        assert not page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
        browser.close()

    errors = {
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_responses": failed_responses,
    }
    errors = {key: value for key, value in errors.items() if value}
    assert not errors, json.dumps(errors, ensure_ascii=False)
    print(json.dumps({"quality_editor": "ok", "target": target}, ensure_ascii=False))


if __name__ == "__main__":
    main()
