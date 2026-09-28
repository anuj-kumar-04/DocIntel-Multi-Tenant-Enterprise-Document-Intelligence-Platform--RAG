import io
from typing import Any

import docx
import fitz  # PyMuPDF
import openpyxl

from app.core.logging import logger


class ParsedBlock:
    def __init__(
        self,
        content: str,
        page_number: int,
        element_type: str = "paragraph",
        section_title: str | None = None,
    ):
        self.content = content.strip()
        self.page_number = page_number
        self.element_type = element_type
        self.section_title = section_title

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
    def parse_pdf(file_bytes: bytes) -> tuple[list[ParsedBlock], int]:
        """Extract text, headings, and tables from PDF carrying page numbers."""
        blocks: list[ParsedBlock] = []
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = len(doc)
        current_section = None

        for page_idx in range(page_count):
            page_number = page_idx + 1
            page = doc[page_idx]

            # 1. Try PyMuPDF native table extraction if available
            try:
                tabs = page.find_tables()
                if tabs.tables:
                    for table in tabs.tables:
                        df_rows = table.extract()
                        if df_rows and len(df_rows) > 1:
                            # Render markdown table
                            header = [str(c or "").strip() for c in df_rows[0]]
                            md_lines = ["| " + " | ".join(header) + " |"]
                            md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                            for row in df_rows[1:]:
                                md_lines.append(
                                    "| " + " | ".join([str(c or "").strip() for c in row]) + " |"
                                )
                            table_md = "\n".join(md_lines)
                            blocks.append(
                                ParsedBlock(
                                    content=table_md,
                                    page_number=page_number,
                                    element_type="table",
                                    section_title=current_section,
                                )
                            )
            except Exception as e:
                logger.debug(f"Table finder skipped on page {page_number}: {e}")

            # 2. Extract text blocks
            text_blocks = page.get_text("blocks")
            for b in text_blocks:
                text = b[4].strip()
                if not text:
                    continue
                # Heuristic heading detection: short line, capitalized, ends without period
                if len(text) < 100 and "\n" not in text and not text.endswith("."):
                    current_section = text
                    blocks.append(
                        ParsedBlock(
                            content=text,
                            page_number=page_number,
                            element_type="heading",
                            section_title=current_section,
                        )
                    )
                else:
                    blocks.append(
                        ParsedBlock(
                            content=text,
                            page_number=page_number,
                            element_type="paragraph",
                            section_title=current_section,
                        )
                    )

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
