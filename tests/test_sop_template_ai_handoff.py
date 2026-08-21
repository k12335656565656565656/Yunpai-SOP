from __future__ import annotations

import json
import base64
import tempfile
import unittest
import zipfile
from pathlib import Path

import pymupdf
from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE

from scripts.generate_sop_template_ai_handoff import (
    CENTER_FLOWCHART_NAME,
    CONTENT_PROFILE_HDMI,
    FINAL_DOCX_NAME,
    FORMAT_CHECK_NAME,
    HDMI_FINAL_DOCX_NAME,
    HDMI_TEMPLATE_ID,
    MANIFEST_NAME,
    TEMPLATE_ID,
    VALIDATION_NAME,
    generate_package,
    generate_route_package,
    validate_document,
)
from cad_ai.sop_knowledge.store import SopKnowledgeStore
from cad_ai.sop_knowledge.models import RouteSectionDraft
from cad_ai.sop_knowledge.documents import SopDocumentService
from cad_ai.sop_visual_template import _work_image_font_sizes
from tests.test_sop_knowledge_workflow import make_identity, make_route


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class SopTemplateAiHandoffTests(unittest.TestCase):
    def test_frozen_handoff_entrypoint_generates_exact_two_section_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = generate_package(directory, document_date="2026-08-11")
            root = Path(directory)

            expected_files = {
                FINAL_DOCX_NAME,
                CENTER_FLOWCHART_NAME,
                MANIFEST_NAME,
                FORMAT_CHECK_NAME,
                VALIDATION_NAME,
            }
            self.assertEqual({path.name for path in root.iterdir()}, expected_files)
            self.assertEqual(result["template_id"], TEMPLATE_ID)
            self.assertTrue(result["structural_pass"])
            self.assertTrue(result["visual_qa_required"])

            document = Document(root / FINAL_DOCX_NAME)
            self.assertEqual(len(document.sections), 2)
            self.assertEqual(len(document.tables), 8)
            self.assertEqual(document.tables[0].cell(2, 3).text.strip(), "DRAFT")
            self.assertEqual(document.tables[4].cell(2, 3).text.strip(), "DRAFT")
            self.assertEqual(document.tables[0].cell(2, 5).text.strip(), "2026/8/11")
            self.assertEqual(document.tables[4].cell(1, 7).text.strip(), "2026/8/11")
            self.assertEqual(
                [document.tables[7].cell(1, index).text.strip() for index in range(3)],
                ["", "", ""],
            )

            validation = json.loads((root / VALIDATION_NAME).read_text(encoding="utf-8"))
            self.assertTrue(validation["structural_pass"])
            self.assertEqual(validation["visual_qa"]["expected_page_count"], 2)

            manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["template_id"], TEMPLATE_ID)
            self.assertTrue(manifest["tables_filled_before_flowchart"])
            self.assertEqual(manifest["fixed_template_profile"]["step_order"], "1,2,3 / 6,5,4")
            self.assertTrue(manifest["guardrails"]["no_auto_release"])

    def test_hdmi_profile_rejects_the_obsolete_two_page_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "route-backed multi-page"):
                generate_package(
                    directory,
                    document_date="2026-08-11",
                    content_profile=CONTENT_PROFILE_HDMI,
                )

    def test_route_backed_hdmi_generates_one_flow_page_and_repeated_instruction_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SopKnowledgeStore(root / "knowledge.sqlite3")
            store.initialize()
            store.ensure_process_family("test_family", "测试工艺族")
            identity = make_identity("HDMI-ROUTE-TEST")
            store.upsert_product(identity, {"class": "cable"})
            route_id = store.create_route(make_route(identity, 3))
            store.create_route_section(
                route_id,
                RouteSectionDraft(
                    section_type="ie_timing",
                    content={"单价": "15.50", "人数": "2", "source": "人工填写"},
                ),
            )
            step = store.get_route(route_id)["steps"][1]
            store.update_step_field(
                step["id"],
                "record_output",
                ["首件记录", "巡检记录", "登记工单号和异常现象"],
                reviewer="worker-01",
                decision="needs_revision",
            )
            result = generate_route_package(
                root / "package",
                document_date="2026-08-12",
                db_path=store.path,
                route_id=route_id,
            )

            self.assertEqual(result["template_id"], HDMI_TEMPLATE_ID)
            self.assertEqual(result["instruction_page_count"], 3)
            self.assertEqual(result["expected_page_count"], 4)
            document = Document(result["document_docx"])
            self.assertEqual(len(document.sections), 2)
            self.assertEqual(len(document.tables), 16)
            first_instruction_body = document.tables[5]
            first_instruction_ie = document.tables[6]
            first_instruction_footer = document.tables[7]
            self.assertTrue(
                all(row.height_rule == WD_ROW_HEIGHT_RULE.AT_LEAST for row in first_instruction_body.rows)
            )
            self.assertTrue(
                all(row.height_rule == WD_ROW_HEIGHT_RULE.AT_LEAST for row in first_instruction_ie.rows)
            )
            self.assertTrue(
                all(row.height_rule == WD_ROW_HEIGHT_RULE.AT_LEAST for row in first_instruction_footer.rows)
            )
            side_font_sizes = [
                run.font.size.pt
                for row_index in range(6)
                for paragraph in first_instruction_body.cell(row_index, 7).paragraphs
                for run in paragraph.runs
                if run.font.size is not None
            ]
            ie_font_sizes = [
                run.font.size.pt
                for row in first_instruction_ie.rows
                for cell in row.cells
                for paragraph in cell.paragraphs
                for run in paragraph.runs
                if run.font.size is not None
            ]
            self.assertGreaterEqual(min(side_font_sizes), 7.5)
            self.assertGreaterEqual(min(ie_font_sizes), 7.5)
            self.assertEqual([step["work_image_slots"] for step in store.get_route(route_id)["steps"]], [3, 3, 3])
            self.assertEqual(len(first_instruction_ie.rows), 5)
            self.assertIn("技术参数", first_instruction_body.cell(6, 0).text)
            self.assertIn("生产参数", first_instruction_body.cell(7, 0).text)
            flow_ie_time = document.tables[2]
            self.assertIn("单价", flow_ie_time.cell(1, 3).text)
            self.assertIn("人数", flow_ie_time.cell(1, 4).text)
            self.assertIn("15.50", flow_ie_time.cell(2, 3).text)
            self.assertIn("2", flow_ie_time.cell(2, 4).text)
            for page_index in range(3):
                base = 4 + page_index * 4
                self.assertEqual(document.tables[base].cell(2, 3).text.strip(), "DRAFT")
                work_ie_time = document.tables[base + 2]
                self.assertIn("单价", work_ie_time.cell(1, 3).text)
                self.assertIn("人数", work_ie_time.cell(1, 4).text)
                self.assertIn("15.50", work_ie_time.cell(2, 3).text)
                self.assertIn("2", work_ie_time.cell(2, 4).text)
                self.assertEqual(
                    [document.tables[base + 3].cell(1, index).text.strip() for index in range(3)],
                    ["", "", ""],
                )
            second_instruction_body = document.tables[9]
            self.assertIn("记录要求（最新）", second_instruction_body.cell(4, 7).text)
            self.assertIn("登记工单号和异常现象", second_instruction_body.cell(4, 7).text)

    def test_route_backed_hdmi_supports_every_work_image_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SopKnowledgeStore(root / "knowledge.sqlite3")
            store.initialize()
            store.ensure_process_family("test_family", "测试工艺族")
            identity = make_identity("HDMI-LAYOUT-TEST")
            store.upsert_product(identity, {"class": "cable"})
            route_id = store.create_route(make_route(identity, 6))
            steps = store.get_route(route_id)["steps"]
            store.update_step_field(
                steps[0]["id"],
                "method",
                ["准备物料", "核对方向", "执行作业", "记录结果"],
                reviewer="layout-tester",
            )
            for field_name, value in {
                "quality_check": ["本工序检查方法尚未由人工提供。"],
                "acceptance_criteria": ["本工序合格判据尚未由责任人依据受控规范提供。"],
                "tool_equipment": ["设备、工具及治具型号待工程确认。"],
                "safety": ["信息不完整或结果异常时停止流转并提交人工判定。"],
                "record_output": ["本工序记录要求尚未由人工提供。"],
                "inputs": ["本工序输入资料待责任人确认。"],
            }.items():
                store.update_step_field(
                    steps[-1]["id"], field_name, value, reviewer="layout-tester"
                )
            for slot_count, step in enumerate(steps, start=1):
                store.set_step_work_image_slots(step["id"], slot_count, reviewer="layout-tester")
            store.set_route_font_profile(route_id, "large", reviewer="layout-tester")

            result = generate_route_package(
                root / "package",
                document_date="2026-08-18",
                db_path=store.path,
                route_id=route_id,
            )

            document = Document(result["document_docx"])
            expected_positions = {
                1: [(0, 1, "1")],
                2: [(0, 1, "1"), (0, 4, "2")],
                3: [(0, 1, "1"), (0, 3, "2"), (0, 5, "3")],
                4: [(0, 1, "1"), (0, 4, "2"), (3, 4, "3"), (3, 1, "4")],
                5: [(0, 1, "1"), (0, 3, "2"), (0, 5, "3"), (3, 4, "4"), (3, 1, "5")],
                6: [(0, 1, "1"), (0, 3, "2"), (0, 5, "3"), (3, 5, "4"), (3, 3, "5"), (3, 1, "6")],
            }
            for page_index, slot_count in enumerate(range(1, 7)):
                body = document.tables[5 + page_index * 4]
                ie_table = document.tables[6 + page_index * 4]
                for row, column, prefix in expected_positions[slot_count]:
                    self.assertTrue(body.cell(row, column).text.strip().startswith(prefix))
                self.assertEqual(len(ie_table.rows), 2 + slot_count)
                self.assertIn("技术参数", body.cell(6, 0).text)
                self.assertIn("生产参数", body.cell(7, 0).text)
                font_sizes = _work_image_font_sizes(slot_count, "large")
                side_sizes = [
                    run.font.size.pt
                    for row_index in range(6)
                    for paragraph in body.cell(row_index, 7).paragraphs
                    for run in paragraph.runs
                    if run.font.size is not None
                ]
                parameter_sizes = [
                    run.font.size.pt
                    for row_index in (6, 7)
                    for paragraph in body.cell(row_index, 1).paragraphs
                    for run in paragraph.runs
                    if run.font.size is not None
                ]
                ie_sizes = [
                    run.font.size.pt
                    for row in ie_table.rows[2:]
                    for cell in row.cells
                    for paragraph in cell.paragraphs
                    for run in paragraph.runs
                    if run.font.size is not None
                ]
                self.assertGreaterEqual(min(side_sizes), font_sizes["side"])
                self.assertGreaterEqual(min(parameter_sizes), font_sizes["parameter"])
                self.assertGreaterEqual(min(ie_sizes), font_sizes["ie"])

            first_body_text = "\n".join(
                cell.text for row in document.tables[5].rows for cell in row.cells
            )
            for method in ("准备物料", "核对方向", "执行作业", "记录结果"):
                self.assertIn(method, first_body_text)

            manifest = json.loads((root / "package" / MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(
                [item["work_image_slots"] for item in manifest["layout"]["instruction_layouts"]],
                [1, 2, 3, 4, 5, 6],
            )
            validation = json.loads((root / "package" / VALIDATION_NAME).read_text(encoding="utf-8"))
            self.assertTrue(validation["checks"]["ie_action_rows_match_work_image_slots"])
            self.assertTrue(validation["checks"]["visual_step_order_every_page"])

            documents = SopDocumentService(store)
            if documents._find_libreoffice_executable() is not None:
                preview_dir = root / "libreoffice-preview"
                pdf_path = documents._convert_docx_with_libreoffice(
                    Path(result["document_docx"]), preview_dir
                )
                page_paths = documents._render_pdf_pages(pdf_path, preview_dir)
                with pymupdf.open(pdf_path) as pdf:
                    page_summaries = [
                        " | ".join(page.get_text().splitlines()[:8])
                        for page in pdf
                    ]
                self.assertEqual(
                    len(page_paths),
                    result["expected_page_count"],
                    page_summaries,
                )

    def test_route_backed_hdmi_writes_manual_step_ie_items_without_inventing_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SopKnowledgeStore(root / "knowledge.sqlite3")
            store.initialize()
            store.ensure_process_family("test_family", "测试工艺族")
            identity = make_identity("HDMI-IE-ITEM-TEST")
            store.upsert_product(identity, {"class": "cable"})
            route_id = store.create_route(make_route(identity, 2))
            step = store.get_route(route_id)["steps"][0]
            store.replace_step_ie_items(
                step["id"],
                [
                    {
                        "action": "剥皮",
                        "machine_type": "人工填写的剥皮机",
                        "equipment_speed": "每分钟 12 米",
                        "headcount": "1",
                        "standard_time": "30 秒",
                        "allowance_rate": "8%",
                        "standard_capacity": "100 条/小时",
                        "time_source": "现场实测记录 IE-2026-08",
                        "note": "单价尚未提供",
                    },
                    {"action": "检查"},
                ],
                reviewer="ie-reviewer",
            )

            result = generate_route_package(
                root / "package",
                document_date="2026-08-21",
                db_path=store.path,
                route_id=route_id,
            )
            document = Document(result["document_docx"])
            ie_table = document.tables[6]
            headers = [ie_table.cell(1, index).text.strip() for index in range(10)]
            first_row = [ie_table.cell(2, index).text.strip() for index in range(10)]
            second_row = [ie_table.cell(3, index).text.strip() for index in range(10)]

            self.assertEqual(
                headers,
                ["动作", "机器类型", "设备速度", "单价", "人数", "标准工时", "宽放率", "标准产能", "工时来源", "备注"],
            )
            self.assertEqual(first_row[0], "剥皮")
            self.assertEqual(first_row[1], "人工填写的剥皮机")
            self.assertEqual(first_row[2], "每分钟 12 米")
            self.assertEqual(first_row[3], "")
            self.assertEqual(first_row[7], "100 条/小时")
            self.assertEqual(second_row, ["检查", "", "", "", "", "", "", "", "", ""])

    def test_route_backed_hdmi_embeds_only_confirmed_step_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SopKnowledgeStore(root / "knowledge.sqlite3")
            store.initialize()
            store.ensure_process_family("test_family", "测试工艺族")
            identity = make_identity("HDMI-MEDIA-TEST")
            store.upsert_product(identity, {"class": "cable"})
            route_id = store.create_route(make_route(identity, 2))
            steps = store.get_route(route_id)["steps"]
            confirmed = store.upload_media_asset(
                route_id, original_name="confirmed.png", mime_type="image/png",
                data=PNG_1X1, uploaded_by="worker-01",
            )
            draft = store.upload_media_asset(
                route_id, original_name="draft.png", mime_type="image/png",
                data=PNG_1X1 + b"draft", uploaded_by="worker-01",
            )
            store.link_media_asset(steps[0]["id"], confirmed["id"], caption="确认图片")
            store.confirm_step(steps[0]["id"], reviewer="worker-01")
            store.link_media_asset(steps[1]["id"], draft["id"], caption="草稿图片")

            result = generate_route_package(
                root / "package", document_date="2026-08-12", db_path=store.path, route_id=route_id,
            )

            with zipfile.ZipFile(result["document_docx"]) as archive:
                embedded = [name for name in archive.namelist() if name.startswith("word/media/")]
            self.assertEqual(len(embedded), 2)  # 流程图 + 1 张已确认工序图片
            document = Document(result["document_docx"])
            first_page_body = document.tables[5]
            second_page_body = document.tables[9]
            self.assertNotIn("待人工上传确认", first_page_body.cell(0, 1).text)
            self.assertIn("待人工上传确认", second_page_body.cell(0, 1).text)

    def test_check_only_validation_rejects_missing_document(self) -> None:
        result = validate_document(Path("does-not-exist.docx"))
        self.assertFalse(result["structural_pass"])
        self.assertEqual(result["errors"], ["document_not_found"])


if __name__ == "__main__":
    unittest.main()
