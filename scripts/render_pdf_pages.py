from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a PDF into numbered PNG preview pages.")
    parser.add_argument("--input", required=True, type=Path, help="Source PDF path")
    parser.add_argument(
        "--output-directory",
        required=True,
        type=Path,
        help="Directory for page-001.png, page-002.png, and later pages",
    )
    parser.add_argument("--dpi", type=int, default=180, help="PNG rendering resolution")
    return parser


def render_pdf_pages(pdf_path: Path, output_directory: Path, dpi: int) -> list[Path]:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    if dpi < 36 or dpi > 600:
        raise ValueError("DPI must be between 36 and 600")

    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to render PDF preview pages") from exc

    output_directory.mkdir(parents=True, exist_ok=True)
    for existing_page in output_directory.glob("page-*.png"):
        existing_page.unlink()

    rendered_pages: list[Path] = []
    document = pymupdf.open(pdf_path)
    try:
        if document.page_count < 1:
            raise ValueError(f"PDF contains no pages: {pdf_path}")
        for page_number, page in enumerate(document, start=1):
            output_path = output_directory / f"page-{page_number:03d}.png"
            page.get_pixmap(dpi=dpi, alpha=False).save(output_path)
            rendered_pages.append(output_path.resolve())
    finally:
        document.close()

    return rendered_pages


def main() -> int:
    args = build_parser().parse_args()
    try:
        pdf_path = args.input.resolve()
        page_paths = render_pdf_pages(pdf_path, args.output_directory.resolve(), args.dpi)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "pdf_path": str(pdf_path),
                "page_count": len(page_paths),
                "page_paths": [str(path) for path in page_paths],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
