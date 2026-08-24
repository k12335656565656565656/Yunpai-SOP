from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8787/?route=1"
TOLERANCE = 0.35


def assert_region(actual: dict[str, float], expected: dict[str, float], label: str) -> None:
    errors = {
        key: {"actual": round(float(actual[key]), 2), "expected": value}
        for key, value in expected.items()
        if abs(float(actual[key]) - value) > TOLERANCE
    }
    assert not errors, f"{label} is not aligned to the v5 table: {json.dumps(errors)}"


def regions_for_slot_count(page, slot_count: int) -> dict[str, dict[str, float]]:
    return page.evaluate(
        """slotCount => {
            const step = {...pageEditStep(2), work_image_slots: slotCount};
            const fields = pageEditFieldsForStep(step);
            return pageEditRegionsForPageV5(step, fields);
        }""",
        slot_count,
    )


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => documentInfo?.template_id === 'yunpai.sop.hdmi-cable.multi-page.v5'",
            timeout=120_000,
        )

        two_slots = regions_for_slot_count(page, 2)
        six_slots = regions_for_slot_count(page, 6)
        browser.close()

    expected_common = {
        "action": {"x": 2.68, "y": 15.2, "w": 65.36, "h": 3.8},
        "why": {"x": 2.68, "y": 19.0, "w": 65.36, "h": 3.8},
        "materials": {"x": 68.04, "y": 27.2, "w": 29.58, "h": 4.4},
        "inputs": {"x": 68.04, "y": 31.6, "w": 29.58, "h": 4.4},
        "tool_equipment": {"x": 68.04, "y": 40.0, "w": 29.58, "h": 4.1},
        "fixtures": {"x": 68.04, "y": 44.1, "w": 29.58, "h": 4.1},
        "parameters": {"x": 68.04, "y": 52.0, "w": 29.58, "h": 3.6},
        "ie_items": {"x": 68.04, "y": 59.3, "w": 29.58, "h": 9.9},
        "quality_check": {"x": 6.43, "y": 75.7, "w": 9.46, "h": 14.6},
        "acceptance_criteria": {"x": 15.89, "y": 75.7, "w": 37.98, "h": 14.6},
    }
    for key, expected in expected_common.items():
        assert_region(two_slots[key], expected, key)

    assert_region(
        two_slots["image_slot_1"],
        {"x": 2.68, "y": 31.0, "w": 32.68, "h": 32.0},
        "two-slot image 1",
    )
    assert_region(
        two_slots["method_slot_1"],
        {"x": 2.68, "y": 63.0, "w": 32.68, "h": 6.2},
        "two-slot caption 1",
    )
    assert_region(
        six_slots["image_slot_1"],
        {"x": 2.68, "y": 31.0, "w": 21.79, "h": 15.1},
        "six-slot top image",
    )
    assert_region(
        six_slots["method_slot_1"],
        {"x": 2.68, "y": 46.1, "w": 21.79, "h": 3.6},
        "six-slot top caption",
    )
    assert_region(
        six_slots["image_slot_4"],
        {"x": 2.68, "y": 49.7, "w": 21.79, "h": 17.2},
        "six-slot bottom image",
    )
    assert_region(
        six_slots["method_slot_4"],
        {"x": 2.68, "y": 66.9, "w": 21.79, "h": 3.7},
        "six-slot bottom caption",
    )
    print(json.dumps({"two_slots": two_slots, "six_slots": six_slots}, ensure_ascii=False))


if __name__ == "__main__":
    main()
