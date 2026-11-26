import io
import re
from typing import Any

import docx
import fitz  # PyMuPDF
import openpyxl
from app.core.logging import logger
from app.services.ocr import ocr_service

_INVISIBLE_CHARS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_MIN_NATIVE_TEXT_CHARS = 50
_MIN_HYBRID_IMAGE_PX = 80
_MIN_HYBRID_RECT_PT = 36.0
_OCR_RENDER_DPI = 250


def _normalize_for_dedup(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _clean_text(raw: str | None) -> str:
    """Strip invisible bidi/control markers that degrade full-text indexing."""
    if not raw:
        return ""
    return _INVISIBLE_CHARS_RE.sub("", raw).strip()


class ParsedBlock:
    def __init__(
        self,
        content: str,
        page_number: int,
        element_type: str = "paragraph",
        section_title: str | None = None,
    ):
        self.content = _clean_text(content)
        self.page_number = page_number
        self.element_type = element_type
        self.section_title = _clean_text(section_title) or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "page_number": self.page_number,
            "element_type": self.element_type,
            "section_title": self.section_title,
        }


class DocumentParser:
    """Multi-format layout-aware document parser."""

    @staticmethod
    def _ocr_page_or_images(
        doc: Any,
        page: Any,
        page_number: int,
        native_char_count: int,
        native_text_joined: str,
    ) -> list[str]:
        """Run high-DPI OCR on low-text scanned pages or significant embedded raster images."""
        images = page.get_images(full=True)
        needs_full_page_ocr = native_char_count < _MIN_NATIVE_TEXT_CHARS
        if not needs_full_page_ocr and not images:
            return []

        ocr_segments: list[str] = []

        if needs_full_page_ocr:
            try:
                pix = page.get_pixmap(dpi=_OCR_RENDER_DPI, alpha=False)
                extracted = ocr_service.extract_text_from_image(pix.tobytes("png"))
                if extracted:
                    ocr_segments.append(extracted)
            except Exception as e:
                logger.warning(f"Full-page OCR failed on page {page_number}: {e}")
        else:
            # Hybrid page: native text exists alongside embedded raster images (scans/receipts/figures)
            seen_xrefs: set[int] = set()
            fallback_full_page = False

            for img_info in images:
                xref = int(img_info[0])
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                width = int(img_info[2] or 0)
                height = int(img_info[3] or 0)
                rects = page.get_image_rects(xref)

                if rects:
                    for rect in rects:
                        if (
                            rect.width < _MIN_HYBRID_RECT_PT
                            and rect.height < _MIN_HYBRID_RECT_PT
                            and width < _MIN_HYBRID_IMAGE_PX
                            and height < _MIN_HYBRID_IMAGE_PX
                        ):
                            continue
                        try:
                            pix = page.get_pixmap(clip=rect, dpi=_OCR_RENDER_DPI, alpha=False)
                            extracted = ocr_service.extract_text_from_image(pix.tobytes("png"))
                            if extracted:
                                ocr_segments.append(extracted)
                        except Exception as e:
                            logger.debug(
                                f"Clip OCR failed for image xref={xref} on page {page_number}: {e}"
                            )
                elif width >= _MIN_HYBRID_IMAGE_PX or height >= _MIN_HYBRID_IMAGE_PX:
                    try:
                        raw_img = doc.extract_image(xref)
                        img_bytes = raw_img.get("image") if raw_img else None
                        if img_bytes:
                            extracted = ocr_service.extract_text_from_image(img_bytes)
                            if extracted:
                                ocr_segments.append(extracted)
                    except Exception:
                        fallback_full_page = True

            if fallback_full_page and not ocr_segments:
                try:
                    pix = page.get_pixmap(dpi=_OCR_RENDER_DPI, alpha=False)
                    extracted = ocr_service.extract_text_from_image(pix.tobytes("png"))
                    if extracted:
                        ocr_segments.append(extracted)
                except Exception as e:
                    logger.debug(f"Fallback full-page OCR failed on page {page_number}: {e}")

        if not ocr_segments:
            return []

        # Deduplicate lines already captured cleanly by native PDF text extraction
        native_norm = _normalize_for_dedup(native_text_joined)
        unique_segments: list[str] = []
        seen_lines: set[str] = set()

        for seg in ocr_segments:
            kept_lines: list[str] = []
            for raw_line in seg.splitlines():
                clean_line = _clean_text(raw_line)
                if not clean_line:
                    continue
                norm_line = _normalize_for_dedup(clean_line)
                if not norm_line:
                    continue
                if len(norm_line) >= 6 and norm_line in native_norm:
                    continue
                if norm_line in seen_lines:
                    continue
                seen_lines.add(norm_line)
                kept_lines.append(clean_line)
            if kept_lines:
                unique_segments.append("\n".join(kept_lines))

        return unique_segments

    @staticmethod
    def parse_pdf(file_bytes: bytes) -> tuple[list[ParsedBlock], int]:
        """Extract native text, tables, and high-DPI OCR from scanned/image PDF pages."""
        blocks: list[ParsedBlock] = []
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = len(doc)
        current_section = None

        for page_idx in range(page_count):
            page_number = page_idx + 1
            page = doc[page_idx]
            page_blocks: list[ParsedBlock] = []

            # 1. Try PyMuPDF native table extraction if available
            try:
                tabs = page.find_tables()
                if tabs.tables:
                    for table in tabs.tables:
                        df_rows = table.extract()
                        if df_rows and len(df_rows) > 1:
                            header = [str(c or "").strip() for c in df_rows[0]]
                            md_lines = ["| " + " | ".join(header) + " |"]
                            md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                            for row in df_rows[1:]:
                                md_lines.append(
                                    "| " + " | ".join([str(c or "").strip() for c in row]) + " |"
                                )
                            table_md = "\n".join(md_lines)
                            page_blocks.append(
                                ParsedBlock(
                                    content=table_md,
                                    page_number=page_number,
                                    element_type="table",
                                    section_title=current_section,
                                )
                            )
            except Exception as e:
                logger.debug(f"Table finder skipped on page {page_number}: {e}")

            # 2. Extract native text blocks in visual reading order (ignore raw image placeholders)
            text_blocks = page.get_text("blocks", sort=True)
            for b in text_blocks:
                if len(b) > 6 and b[6] != 0:
                    continue
                text = _clean_text(b[4])
                if not text:
                    continue
                # Heuristic heading detection: short line, capitalized, ends without period
                if len(text) < 100 and "\n" not in text and not text.endswith("."):
                    current_section = text
                    page_blocks.append(
                        ParsedBlock(
                            content=text,
                            page_number=page_number,
                            element_type="heading",
                            section_title=current_section,
                        )
                    )
                else:
                    page_blocks.append(
                        ParsedBlock(
                            content=text,
                            page_number=page_number,
                            element_type="paragraph",
                            section_title=current_section,
                        )
                    )

            # 3. Scanned page / embedded raster image detection + high-DPI OCR fallback
            native_text_joined = "\n".join(blk.content for blk in page_blocks)
            native_char_count = len(native_text_joined.strip())
            ocr_texts = DocumentParser._ocr_page_or_images(
                doc=doc,
                page=page,
                page_number=page_number,
                native_char_count=native_char_count,
                native_text_joined=native_text_joined,
            )
            for ocr_block_text in ocr_texts:
                logger.info(
                    f"Extracted {len(ocr_block_text)} OCR chars on PDF page {page_number} "
                    f"(native_chars={native_char_count})"
                )
                page_blocks.append(
                    ParsedBlock(
                        content=ocr_block_text,
                        page_number=page_number,
                        element_type="paragraph",
                        section_title=current_section or f"Scanned Content (Page {page_number})",
                    )
                )

            blocks.extend(page_blocks)

        doc.close()
        return blocks, page_count

    @staticmethod
    def parse_docx(file_bytes: bytes) -> tuple[list[ParsedBlock], int]:
        """Extract paragraphs and tables from DOCX files."""
        blocks: list[ParsedBlock] = []
        doc = docx.Document(io.BytesIO(file_bytes))
        current_section = None
        current_page = 1  # DOCX does not have fixed pagination; simulated page grouping

        token_estimate = 0
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            if para.style and "Heading" in para.style.name:
                current_section = text
                element_type = "heading"
            else:
                element_type = "paragraph"

            token_estimate += len(text.split())
            if token_estimate > 450:
                current_page += 1
                token_estimate = 0

            blocks.append(
                ParsedBlock(
                    content=text,
                    page_number=current_page,
                    element_type=element_type,
                    section_title=current_section,
                )
            )

        # Extract docx tables
        for table in doc.tables:
            rows_data = []
            for row in table.rows:
                rows_data.append([c.text.strip() for c in row.cells])
            if rows_data and len(rows_data) > 1:
                header = rows_data[0]
                md_lines = ["| " + " | ".join(header) + " |"]
                md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                for r in rows_data[1:]:
                    md_lines.append("| " + " | ".join(r) + " |")
                blocks.append(
                    ParsedBlock(
                        content="\n".join(md_lines),
                        page_number=current_page,
                        element_type="table",
                        section_title=current_section,
                    )
                )

        return blocks, max(1, current_page)

    @staticmethod
    def parse_xlsx(file_bytes: bytes) -> tuple[list[ParsedBlock], int]:
        """Extract sheets and tabular data from Excel spreadsheets."""
        blocks: list[ParsedBlock] = []
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        page_number = 1

        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue

            # Convert non-empty rows to markdown table
            filtered_rows = [r for r in rows if any(cell is not None for cell in r)]
            if not filtered_rows:
                continue

            header = [str(c or "").strip() for c in filtered_rows[0]]
            md_lines = [f"### Sheet: {sheet_name}", "| " + " | ".join(header) + " |"]
            md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")

            for r in filtered_rows[1:]:
                md_lines.append("| " + " | ".join([str(c or "").strip() for c in r]) + " |")

            blocks.append(
                ParsedBlock(
                    content="\n".join(md_lines),
                    page_number=page_number,
                    element_type="table",
                    section_title=sheet_name,
                )
            )
            page_number += 1

        return blocks, max(1, page_number - 1)

    @classmethod
    def parse(
        cls, file_bytes: bytes, filename: str, mime_type: str
    ) -> tuple[list[ParsedBlock], int]:
        """Auto-detect format and parse document contents."""
        lower_name = filename.lower()
        if mime_type == "application/pdf" or lower_name.endswith(".pdf"):
            return cls.parse_pdf(file_bytes)
        elif mime_type in [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ] or lower_name.endswith(".docx"):
            return cls.parse_docx(file_bytes)
        elif mime_type in [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        ] or lower_name.endswith(".xlsx"):
            return cls.parse_xlsx(file_bytes)
        else:
            # Fallback for plain text, markdown, csv
            text = file_bytes.decode("utf-8", errors="replace")
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            blocks = [
                ParsedBlock(
                    content=line,
                    page_number=1,
                    element_type="paragraph",
                    section_title=None,
                )
                for line in lines
            ]
            return blocks, 1
