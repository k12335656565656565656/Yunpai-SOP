from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


OUTPUT = Path(__file__).parent / "screenshots" / "new-project-restoration"
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b49444154789c6364f80f0001050101a5b18d0000000049454e44ae426082"
)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto("http://127.0.0.1:8788/", wait_until="domcontentloaded")
        page.locator("#newProject").wait_for(state="visible", timeout=15_000)
        page.screenshot(path=str(OUTPUT / "01-entry.png"), full_page=True)

        page.locator("#newProject").click()
        page.locator("#projectBackdrop").wait_for(state="visible")
        page.locator("#projectDescription").fill("Product DEMO-01. Steps: cut wire, crimp terminal, electrical test.")
        page.locator("#projectImages").set_input_files(
            {"name": "work-step.png", "mimeType": "image/png", "buffer": PNG_1X1}
        )
        assert page.locator(".project-file").count() == 1
        page.screenshot(path=str(OUTPUT / "02-intake.png"), full_page=True)

        def preview(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"draft_id":"demo-draft","can_create":true,"product_code":"DEMO-01",'
                    '"product_name":"Demo cable","steps":[{"title":"Cut wire"},'
                    '{"title":"Crimp terminal"},{"title":"Electrical test"}],'
                    '"ie_timing":[{"step_title":"Cut wire"}],"unknowns":[],"warnings":[]}'
                ),
            )

        page.route("**/api/projects/preview", preview)
        page.locator("#projectSubmit").click()
        page.locator("text=AI 已整理，等待人工确认").wait_for(timeout=10_000)
        assert page.locator("#projectSubmit").inner_text() == "确认创建草稿路线"
        page.screenshot(path=str(OUTPUT / "03-human-confirmation.png"), full_page=True)
        browser.close()

    if console_errors or page_errors:
        raise RuntimeError(f"console_errors={console_errors}; page_errors={page_errors}")
    print(f"PASS: screenshots saved to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
