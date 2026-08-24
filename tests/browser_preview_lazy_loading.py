from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_HTML = PROJECT_ROOT / "cad_ai" / "sop_knowledge" / "simple_workbench.html"
ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def route_payload() -> dict[str, object]:
    steps = [
        {
            "id": index,
            "step_code": f"S{index:02d}",
            "sequence_no": index,
            "title": f"工序 {index}",
            "review_state": "needs_revision",
            "parent_step_id": None,
            "work_image_slots": 3,
        }
        for index in range(1, 13)
    ]
    return {
        "route": {
            "id": 1,
            "product_code": "LAZY-13",
            "status": "draft",
            "version": 1,
            "font_profile": "standard",
        },
        "steps": steps,
        "sections": [],
        "media": [],
    }


def document_payload() -> dict[str, object]:
    token = "lazy-loading-test"
    return {
        "route_id": 1,
        "route_version": 1,
        "product_code": "LAZY-13",
        "generated_at": "2026-08-22T00:00:00+00:00",
        "version_token": token,
        "page_count": 13,
        "media_count": 0,
        "status": "draft_document_generated",
        "preview_source": "generated_docx",
        "template_id": "yunpai.sop.hdmi-cable.multi-page.v5",
        "layout_mode": "portrait_flow_then_excel_reference_operation_sheet_v5",
        "docx_url": f"/api/routes/1/documents/latest.docx?v={token}",
        "preview_url": f"/api/routes/1/documents/preview.pdf?v={token}",
        "page_urls": [
            f"/api/routes/1/documents/pages/{page}.png?v={token}"
            for page in range(1, 14)
        ],
    }


def main() -> None:
    requested_pages: list[int] = []
    html = WORKBENCH_HTML.read_text(encoding="utf-8")

    def handle(route: Route) -> None:
        path = urlparse(route.request.url).path
        if path == "/":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif path == "/api/products":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    [{"product_code": "LAZY-13", "product_name": "懒加载测试", "latest_route_id": 1}],
                    ensure_ascii=False,
                ),
            )
        elif path == "/api/routes/1":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(route_payload(), ensure_ascii=False))
        elif path == "/api/routes/1/chat/history" or path == "/api/routes/1/step-deletions/recent":
            route.fulfill(status=200, content_type="application/json", body="[]")
        elif path == "/api/routes/1/documents/latest":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(document_payload()))
        elif "/documents/pages/" in path:
            requested_pages.append(int(Path(path).stem))
            route.fulfill(status=200, content_type="image/png", body=ONE_PIXEL_PNG)
        else:
            route.fulfill(status=404, content_type="application/json", body='{"detail":"not found"}')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("http://sop.test/**", handle)
        page.goto("http://sop.test/", wait_until="domcontentloaded")
        page.wait_for_function(
            "() => documentInfo?.page_count === 13 && previewImageLoadsActive === 0 && previewImageQueue.length === 0",
            timeout=10_000,
        )

        initial_requests = list(requested_pages)
        assert initial_requests, "首屏没有请求任何预览页"
        assert set(initial_requests).issubset({1, 2}), initial_requests
        initial_sources = page.locator("#docPages img[src]").evaluate_all(
            "images => images.map(image => image.getAttribute('src'))"
        )
        assert len(initial_sources) <= 2, (initial_requests, initial_sources)

        requested_pages.clear()
        page.evaluate(
            "() => locateChange({page_number:13,field_key:'method',field:'作业指导步骤'})"
        )
        page.wait_for_function(
            "() => document.querySelector('.doc-page[data-page-number=\"13\"] img')?.dataset.loadState === 'loaded'",
            timeout=10_000,
        )
        assert requested_pages[0] == 13, requested_pages
        assert set(requested_pages).issubset({12, 13}), requested_pages
        assert page.locator("#docPages img[src]").count() <= 4
        assert not page.locator('.doc-page[data-page-number="13"] .page-image-error').is_visible()
        browser.close()

    print(json.dumps({"initial_requests": initial_requests, "located_requests": requested_pages}, ensure_ascii=False))


if __name__ == "__main__":
    main()
