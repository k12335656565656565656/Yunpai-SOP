from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .store import SopKnowledgeStore

CURRENT_PREVIEW_DIR_NAME = "preview-current"
VERSIONED_PREVIEW_DIR_PREFIX = "preview-version-"
PREVIEW_PAGE_DPI = 180

MULTI_PAGE_TEMPLATE_ID = "yunpai.sop.hdmi-cable.multi-page.v3"
MULTI_PAGE_LAYOUT_MODE = "portrait_flow_then_repeated_landscape_work_instructions"
MULTI_PAGE_DOCX_NAME = "SOP完整模板_HDMI线制作_草案.docx"


class SopDocumentService:
    """Generate the final DOCX and a browser preview from the same artifact."""

    _locks: dict[int, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, store: SopKnowledgeStore) -> None:
        self.store = store
        self.root = store.path.parent / "generated_documents"
        self.root.mkdir(parents=True, exist_ok=True)
        self.project_root = Path(__file__).resolve().parents[2]
        self.preview_script = self.project_root / "scripts" / "render_docx_preview.ps1"
        self.template_script = self.project_root / "scripts" / "generate_sop_template_ai_handoff.py"

    def generate(self, route_id: int) -> dict[str, Any]:
        lock = self._lock_for(route_id)
        with lock:
            output_dir = self.root / f"route_{route_id}"
            # Keep live artifacts separate from stale legacy preview folders.
            preview_dir = output_dir / CURRENT_PREVIEW_DIR_NAME
            template_dir = output_dir / "template_package"
            output_dir.mkdir(parents=True, exist_ok=True)
            preview_dir.mkdir(parents=True, exist_ok=True)
            template_dir.mkdir(parents=True, exist_ok=True)
            rendered = self._generate_template_package(route_id, template_dir)
            docx_path = Path(rendered["document_docx"])
            version_token = hashlib.sha256(docx_path.read_bytes()).hexdigest()[:16]
            route_fingerprint = self._route_fingerprint(route_id)
            route_payload = self.store.get_route(route_id)
            route = route_payload["route"]
            generated_at = datetime.now(timezone.utc).isoformat()
            try:
                preview = self._render_preview(
                    docx_path,
                    preview_dir,
                    expected_page_count=int(rendered["expected_page_count"]),
                )
            except Exception as exc:
                failure = {
                    "route_id": route_id,
                    "route_version": route["version"],
                    "product_code": route["product_code"],
                    "generated_at": generated_at,
                    "version_token": version_token,
                    "route_fingerprint": route_fingerprint,
                    "template_id": rendered["template_id"],
                    "layout_mode": MULTI_PAGE_LAYOUT_MODE,
                    "docx_path": str(docx_path.resolve()),
                    "page_count": 0,
                    "expected_page_count": rendered["expected_page_count"],
                    "validation_path": rendered["validation_json"],
                    "media_count": len(route_payload.get("media") or []),
                    "status": "preview_failed",
                    "preview_source": "generated_docx",
                    "preview_status": "failed",
                    "preview_error": self._friendly_preview_error(exc),
                    "preview_error_detail": str(exc),
                }
                self._write_json(self._preview_failure_path(route_id), failure)
                return self.public_failure(failure)
            manifest = {
                "route_id": route_id,
                "route_version": route["version"],
                "product_code": route["product_code"],
                "generated_at": generated_at,
                "version_token": version_token,
                "route_fingerprint": route_fingerprint,
                "template_id": rendered["template_id"],
                "layout_mode": MULTI_PAGE_LAYOUT_MODE,
                "docx_path": str(docx_path.resolve()),
                "pdf_path": preview["pdf_path"],
                "page_paths": preview["page_paths"],
                "page_count": preview["page_count"],
                "expected_page_count": rendered["expected_page_count"],
                "validation_path": rendered["validation_json"],
                "media_count": len(route_payload.get("media") or []),
                "status": "draft_document_generated",
                "preview_source": "generated_docx",
            }
            if preview["page_count"] != rendered["expected_page_count"]:
                raise RuntimeError(
                    f"SOP 页数不符合模板：应为 {rendered['expected_page_count']} 页，实际为 {preview['page_count']} 页"
                )
            self._write_json(output_dir / "document_manifest.json", manifest)
            self._preview_failure_path(route_id).unlink(missing_ok=True)
            return self.public_manifest(manifest)

    def latest(self, route_id: int, *, generate_if_missing: bool = True) -> dict[str, Any]:
        failure = self._current_preview_failure(route_id)
        if failure:
            return self.public_failure(failure)
        manifest_path = self.root / f"route_{route_id}" / "document_manifest.json"
        if not manifest_path.exists():
            if not generate_if_missing:
                raise FileNotFoundError("该路线尚未生成 DOCX")
            return self.generate(route_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("template_id") != MULTI_PAGE_TEMPLATE_ID or manifest.get("layout_mode") != MULTI_PAGE_LAYOUT_MODE:
            return self.generate(route_id)
        preview_path = Path(manifest["pdf_path"])
        if not self._is_published_preview_directory(preview_path.parent):
            return self.generate(route_id)
        if not self._is_readable_file(Path(manifest["docx_path"])):
            return self.generate(route_id)
        if manifest.get("route_fingerprint") != self._route_fingerprint(route_id):
            return self.generate(route_id)
        page_count = int(manifest.get("page_count") or 0)
        page_paths = [Path(item) for item in manifest.get("page_paths") or []]
        if page_count < 1 or len(page_paths) != page_count:
            # A published manifest is only written after its PDF and page PNGs
            # are complete. Do not repair a partial manifest by reopening its
            # old PDF: Edge can hold that PDF on Windows. A new complete render
            # is safer than turning a recoverable lock into a workbench outage.
            return self.generate(route_id)
        # Windows browsers can retain an exclusive read lock on an existing
        # PDF or individual preview images. The manifest is atomically
        # published with complete page paths, so normal page loading must not
        # probe or re-render those live browser assets.
        return self.public_manifest(manifest)

    def resolve_file(self, route_id: int, kind: str, *, page_no: int | None = None) -> tuple[Path, str, str]:
        # Resolve from the published manifest first. A browser may lock a PDF
        # or PNG after the manifest was written, so repair the artifact once
        # instead of letting the file endpoint fail the whole preview.
        self.latest(route_id, generate_if_missing=True)
        failure = self._current_preview_failure(route_id)
        if failure:
            if kind == "docx":
                return Path(failure["docx_path"]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"SOP_{failure['product_code']}.docx"
            raise RuntimeError(failure["preview_error"])
        manifest_path = self.root / f"route_{route_id}" / "document_manifest.json"
        if not manifest_path.exists():
            self.generate(route_id)
            failure = self._current_preview_failure(route_id)
            if failure:
                if kind == "docx":
                    return Path(failure["docx_path"]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"SOP_{failure['product_code']}.docx"
                raise RuntimeError(failure["preview_error"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        file_path, mime_type, filename = self._manifest_file(manifest, kind, page_no=page_no)
        if self._is_readable_file(file_path):
            return file_path, mime_type, filename

        self.generate(route_id)
        failure = self._current_preview_failure(route_id)
        if failure:
            if kind == "docx":
                return Path(failure["docx_path"]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"SOP_{failure['product_code']}.docx"
            raise RuntimeError(failure["preview_error"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        file_path, mime_type, filename = self._manifest_file(manifest, kind, page_no=page_no)
        if not self._is_readable_file(file_path):
            raise RuntimeError("DOCX 预览文件暂时无法读取，已尝试生成新副本，请稍后重试。")
        return file_path, mime_type, filename

    @staticmethod
    def _manifest_file(
        manifest: dict[str, Any],
        kind: str,
        *,
        page_no: int | None = None,
    ) -> tuple[Path, str, str]:
        if kind == "docx":
            return Path(manifest["docx_path"]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"SOP_{manifest['product_code']}.docx"
        if kind == "pdf":
            return Path(manifest["pdf_path"]), "application/pdf", f"SOP_{manifest['product_code']}_preview.pdf"
        if kind == "page" and page_no is not None:
            paths = manifest["page_paths"]
            if page_no < 1 or page_no > len(paths):
                raise KeyError(page_no)
            return Path(paths[page_no - 1]), "image/png", f"page-{page_no}.png"
        raise ValueError("unsupported document asset")

    def runtime_status(self) -> dict[str, Any]:
        try:
            import pymupdf  # noqa: F401
        except ImportError:
            pdf_renderer = {"available": False, "backend": "PyMuPDF"}
        else:
            pdf_renderer = {"available": True, "backend": "PyMuPDF"}

        if sys.platform.startswith("win"):
            powershell = self._windows_powershell_executable()
            office_backend = self._find_windows_office_backend()
            converter = {
                "available": bool(powershell and self.preview_script.is_file() and office_backend),
                "backend": office_backend or "Microsoft Word/LibreOffice",
            }
        else:
            libreoffice = self._find_libreoffice_executable()
            converter = {
                "available": libreoffice is not None,
                "backend": "LibreOffice",
            }

        try:
            with self.store.connect() as connection:
                connection.execute("SELECT 1").fetchone()
        except Exception as exc:
            database = {"available": False, "detail": str(exc)}
        else:
            database = {"available": True}

        try:
            with tempfile.NamedTemporaryFile(prefix=".health-", dir=self.root):
                pass
        except OSError as exc:
            storage = {"available": False, "detail": str(exc)}
        else:
            storage = {"available": True, "path": str(self.root.resolve())}

        template_generator = {"available": self.template_script.is_file()}
        ready = all(
            item["available"]
            for item in (converter, pdf_renderer, database, storage, template_generator)
        )
        return {
            "status": "ready" if ready else "degraded",
            "platform": sys.platform,
            "docx_converter": converter,
            "pdf_renderer": pdf_renderer,
            "database": database,
            "storage": storage,
            "template_generator": template_generator,
        }

    @staticmethod
    def _is_published_preview_directory(path: Path) -> bool:
        return path.name == CURRENT_PREVIEW_DIR_NAME or path.name.startswith(VERSIONED_PREVIEW_DIR_PREFIX)

    @staticmethod
    def _is_readable_file(path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            with path.open("rb"):
                pass
        except OSError:
            return False
        return True

    @staticmethod
    def public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
        route_id = manifest["route_id"]
        token = manifest["version_token"]
        return {
            key: manifest[key]
            for key in (
                "route_id", "route_version", "product_code", "generated_at", "version_token",
                "page_count", "media_count", "status", "preview_source", "template_id", "layout_mode",
            )
        } | {
            "docx_url": f"/api/routes/{route_id}/documents/latest.docx?v={token}",
            "preview_url": f"/api/routes/{route_id}/documents/preview.pdf?v={token}",
            "page_urls": [f"/api/routes/{route_id}/documents/pages/{index}.png?v={token}" for index in range(1, int(manifest["page_count"]) + 1)],
        }

    @staticmethod
    def public_failure(failure: dict[str, Any]) -> dict[str, Any]:
        route_id = failure["route_id"]
        token = failure["version_token"]
        return {
            key: failure[key]
            for key in (
                "route_id", "route_version", "product_code", "generated_at", "version_token",
                "page_count", "media_count", "status", "preview_source", "template_id", "layout_mode",
                "preview_status", "preview_error",
            )
        } | {
            "docx_url": f"/api/routes/{route_id}/documents/latest.docx?v={token}",
            "preview_url": "",
            "page_urls": [],
        }

    def _render_preview(
        self,
        docx_path: Path,
        output_dir: Path,
        *,
        expected_page_count: int | None = None,
    ) -> dict[str, Any]:
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".preview-stage-", dir=output_dir.parent) as staging_value:
            staging_dir = Path(staging_value)
            staging_docx = staging_dir / "source.docx"
            staging_output = staging_dir / "rendered"
            shutil.copy2(docx_path, staging_docx)
            pdf_path = self._convert_docx_to_pdf(staging_docx, staging_output)
            page_files = self._render_pdf_pages(pdf_path, staging_output)
            page_count = len(page_files)
            if page_count < 1:
                raise RuntimeError("DOCX 预览转换没有返回有效页数")
            if expected_page_count is not None and page_count != expected_page_count:
                raise RuntimeError(f"SOP 页数不符合模板：应为 {expected_page_count} 页，实际为 {page_count} 页")
            target_pdf = staging_output / f"{docx_path.stem}.pdf"
            if pdf_path != target_pdf:
                pdf_path.replace(target_pdf)
            published_dir = self._publish_preview_directory(staging_output, output_dir)
        pdf_files = sorted(published_dir.glob("*.pdf"))
        page_files = sorted(published_dir.glob("page-*.png"))
        return {
            "pdf_path": str(pdf_files[0].resolve()),
            "page_paths": [str(item.resolve()) for item in page_files],
            "page_count": len(page_files),
        }

    def _convert_docx_to_pdf(self, docx_path: Path, output_dir: Path) -> Path:
        if sys.platform.startswith("win"):
            return self._convert_docx_with_windows(docx_path, output_dir)
        return self._convert_docx_with_libreoffice(docx_path, output_dir)

    def _convert_docx_with_windows(self, docx_path: Path, output_dir: Path) -> Path:
        if not self.preview_script.is_file():
            raise FileNotFoundError(f"DOCX preview script is missing: {self.preview_script}")
        powershell_exe = self._windows_powershell_executable()
        if not powershell_exe:
            raise RuntimeError("DOCX preview is unavailable: Windows PowerShell was not found")
        output_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                str(powershell_exe), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File",
                str(self.preview_script), "-InputPath", str(docx_path),
                "-OutputDirectory", str(output_dir),
            ],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "DOCX was generated, but preview conversion failed: "
                + (result.stderr.strip() or "Word/LibreOffice conversion is unavailable")
            )
        try:
            json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("DOCX preview conversion did not return a valid result") from exc
        pdf_files = sorted(output_dir.glob("*.pdf"))
        if len(pdf_files) != 1:
            raise RuntimeError("DOCX preview conversion produced an incomplete PDF artifact")
        return pdf_files[0]

    def _convert_docx_with_libreoffice(self, docx_path: Path, output_dir: Path) -> Path:
        executable = self._find_libreoffice_executable()
        if executable is None:
            raise RuntimeError(
                "DOCX preview is unavailable: install LibreOffice or set SOP_LIBREOFFICE_PATH"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".libreoffice-profile-", dir=output_dir.parent) as profile_value:
            profile_uri = Path(profile_value).resolve().as_uri()
            result = subprocess.run(
                [
                    str(executable),
                    "--headless", "--nologo", "--nodefault", "--nolockcheck",
                    f"-env:UserInstallation={profile_uri}",
                    "--convert-to", "pdf:writer_pdf_Export",
                    "--outdir", str(output_dir), str(docx_path),
                ],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        if result.returncode != 0:
            raise RuntimeError(
                "DOCX was generated, but LibreOffice preview conversion failed: "
                + (result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}")
            )
        pdf_path = output_dir / f"{docx_path.stem}.pdf"
        if not pdf_path.is_file():
            raise RuntimeError(f"LibreOffice did not create the expected PDF: {pdf_path}")
        return pdf_path

    @staticmethod
    def _windows_powershell_executable() -> Path | None:
        candidate = (
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        return candidate if candidate.is_file() else None

    @staticmethod
    def _find_libreoffice_executable() -> Path | None:
        configured = os.environ.get("SOP_LIBREOFFICE_PATH")
        candidates = [
            Path(configured) if configured else None,
            Path(found) if (found := shutil.which("soffice")) else None,
            Path(found) if (found := shutil.which("libreoffice")) else None,
        ]
        if sys.platform.startswith("win"):
            for environment_name in ("ProgramFiles", "ProgramFiles(x86)"):
                root = os.environ.get(environment_name)
                if root:
                    candidates.append(Path(root) / "LibreOffice" / "program" / "soffice.exe")
        return next((candidate for candidate in candidates if candidate and candidate.is_file()), None)

    def _find_windows_office_backend(self) -> str | None:
        for environment_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(environment_name)
            if root and (Path(root) / "Microsoft Office" / "Root" / "Office16" / "WINWORD.EXE").is_file():
                return "Microsoft Word"
        return "LibreOffice" if self._find_libreoffice_executable() else None

    @staticmethod
    def _publish_preview_directory(candidate: Path, output_dir: Path) -> Path:
        backup = output_dir.parent / f".{output_dir.name}-backup-{uuid.uuid4().hex}"
        had_previous = output_dir.exists()
        if had_previous:
            try:
                os.replace(output_dir, backup)
            except PermissionError:
                # Browsers can hold a live preview open on Windows. Publish the
                # replacement beside it so the current preview stays readable.
                versioned_output = output_dir.parent / f"{VERSIONED_PREVIEW_DIR_PREFIX}{uuid.uuid4().hex}"
                os.replace(candidate, versioned_output)
                return versioned_output
        try:
            os.replace(candidate, output_dir)
        except Exception:
            if had_previous and backup.exists() and not output_dir.exists():
                os.replace(backup, output_dir)
            raise
        finally:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
        return output_dir

    def _preview_failure_path(self, route_id: int) -> Path:
        return self.root / f"route_{route_id}" / "preview_failure.json"

    def _current_preview_failure(self, route_id: int) -> dict[str, Any] | None:
        path = self._preview_failure_path(route_id)
        if not path.is_file():
            return None
        try:
            failure = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if failure.get("route_fingerprint") != self._route_fingerprint(route_id):
            return None
        if not Path(str(failure.get("docx_path") or "")).is_file():
            return None
        return failure

    @staticmethod
    def _friendly_preview_error(error: Exception) -> str:
        detail = str(error)
        if any(token in detail for token in ("REGDB_E_CLASSNOTREG", "NoCOMClassIdentified", "Class not registered")):
            return "DOCX 已生成并可下载，但当前电脑没有可用的 Microsoft Word 预览转换组件。请安装或修复 Word 后重试预览。"
        return "DOCX 已生成并可下载，但预览转换暂时不可用。请检查 Word/PDF 转换组件后重试。"

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _render_pdf_pages(pdf_path: Path, output_dir: Path) -> list[Path]:
        try:
            import pymupdf
        except ImportError as exc:
            raise RuntimeError("PDF 分页预览不可用：缺少 PyMuPDF 依赖") from exc
        output_dir.mkdir(parents=True, exist_ok=True)
        for artifact in output_dir.glob("page-*.png"):
            artifact.unlink()
        document = pymupdf.open(pdf_path)
        try:
            for index, page in enumerate(document, start=1):
                page.get_pixmap(dpi=PREVIEW_PAGE_DPI, alpha=False).save(output_dir / f"page-{index:03d}.png")
        finally:
            document.close()
        return sorted(output_dir.glob("page-*.png"))

    def _generate_template_package(self, route_id: int, output_dir: Path) -> dict[str, Any]:
        if not self.template_script.is_file():
            raise FileNotFoundError(f"SOP template generator is missing: {self.template_script}")
        result = subprocess.run(
            [
                sys.executable,
                str(self.template_script),
                "--out-dir", str(output_dir),
                "--document-date", date.today().isoformat(),
                "--route-db", str(self.store.path),
                "--route-id", str(route_id),
            ],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "SOP 模板生成失败：" + (result.stderr.strip() or result.stdout.strip() or "未知错误")
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("SOP 模板生成器没有返回有效结果") from exc
        if payload.get("template_id") != MULTI_PAGE_TEMPLATE_ID or not payload.get("structural_pass"):
            raise RuntimeError("SOP 模板生成结果未通过结构校验")
        # The child Python process may emit its absolute Chinese paths using the
        # active Windows code page. Resolve governed artifacts from their known
        # package names instead of trusting those serialized path bytes.
        payload["document_docx"] = str((output_dir / MULTI_PAGE_DOCX_NAME).resolve())
        payload["validation_json"] = str((output_dir / "sop_template_validation.json").resolve())
        return payload

    def _route_fingerprint(self, route_id: int) -> str:
        payload = self.store.get_route(route_id)
        source = {
            "route": payload["route"],
            "steps": payload["steps"],
            "sections": payload["sections"],
            "media": payload["media"],
        }
        encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _lock_for(cls, route_id: int) -> threading.Lock:
        with cls._locks_guard:
            return cls._locks.setdefault(route_id, threading.Lock())
