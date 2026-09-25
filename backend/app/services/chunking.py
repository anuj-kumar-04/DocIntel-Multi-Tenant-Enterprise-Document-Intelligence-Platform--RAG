import re
from typing import Any
import tiktoken

from app.services.parsing import ParsedBlock


class ChunkData:
    def __init__(
        self,
        content: str,
        page_number: int,
        chunk_index: int,
        section_title: str | None,
        element_type: str,
        token_count: int,
    ):
        self.content = content
        self.page_number = page_number
        self.chunk_index = chunk_index
        self.section_title = section_title
        self.element_type = element_type
        self.token_count = token_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "section_title": self.section_title,
            "element_type": self.element_type,
            "token_count": self.token_count,
        }


class LayoutChunker:
    """Layout-aware chunker preserving table boundaries and heading hierarchy."""

    def __init__(self, target_chunk_size: int = 700, chunk_overlap: int = 100):
        self.target_chunk_size = target_chunk_size
        self.chunk_overlap = chunk_overlap
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.tokenizer = None

    def count_tokens(self, text: str) -> int:
        """Count tokens using cl100k_base or word approximation fallback."""
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except Exception:
                pass
        return max(1, len(text.split()) * 4 // 3)

    def _split_text_recursively(self, text: str, max_tokens: int) -> list[str]:
        """Split text by paragraphs, then sentences, then tokens if too large."""
        if self.count_tokens(text) <= max_tokens:
            return [text]

        # Try paragraph split
        paragraphs = text.split("\n\n")
        if len(paragraphs) > 1:
            chunks = []
            current = []
            current_tokens = 0
            for p in paragraphs:
                p_tokens = self.count_tokens(p)
                if current_tokens + p_tokens > max_tokens and current:
                    chunks.append("\n\n".join(current))
                    current = [p]
                    current_tokens = p_tokens
                else:
                    current.append(p)
                    current_tokens += p_tokens
            if current:
                chunks.append("\n\n".join(current))
            return chunks

        # Try sentence split
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) > 1:
            chunks = []
            current = []
            current_tokens = 0
            for s in sentences:
                s_tokens = self.count_tokens(s)
                if current_tokens + s_tokens > max_tokens and current:
                    chunks.append(" ".join(current))
                    current = [s]
                    current_tokens = s_tokens
                else:
                    current.append(s)
                    current_tokens += s_tokens
            if current:
                chunks.append(" ".join(current))
            return chunks

        # Fallback slice by words
        words = text.split()
        word_chunk_size = max(10, max_tokens * 3 // 4)
        return [" ".join(words[i : i + word_chunk_size]) for i in range(0, len(words), word_chunk_size)]

    def chunk_blocks(self, blocks: list[ParsedBlock]) -> list[ChunkData]:
        """Convert parsed blocks into structured, page-tagged chunks."""
        chunks: list[ChunkData] = []
        chunk_idx = 0

        buffer_text: list[str] = []
        buffer_tokens = 0
        current_page = blocks[0].page_number if blocks else 1
        current_section = blocks[0].section_title if blocks else None

        def flush_buffer():
            nonlocal buffer_text, buffer_tokens, chunk_idx
            if not buffer_text:
                return
            combined_text = "\n\n".join(buffer_text).strip()
            if combined_text:
                chunks.append(
                    ChunkData(
                        content=combined_text,
                        page_number=current_page,
                        chunk_index=chunk_idx,
                        section_title=current_section,
                        element_type="paragraph",
                        token_count=buffer_tokens,
                    )
                )
                chunk_idx += 1
            buffer_text = []
            buffer_tokens = 0

        for block in blocks:
            # 1. Tables are preserved whole as distinct chunks to prevent splitting tabular data
            if block.element_type == "table":
                flush_buffer()
                tokens = self.count_tokens(block.content)
                chunks.append(
                    ChunkData(
                        content=block.content,
                        page_number=block.page_number,
                        chunk_index=chunk_idx,
                        section_title=block.section_title or current_section,
                        element_type="table",
                        token_count=tokens,
                    )
                )
                chunk_idx += 1
                current_page = block.page_number
                continue

            # 2. Heading boundaries trigger a new context window if buffer has content
            if block.element_type == "heading":
                if buffer_tokens > 200:
                    flush_buffer()
                current_section = block.content
                current_page = block.page_number
                buffer_text.append(f"## {block.content}")
                buffer_tokens += self.count_tokens(block.content)
                continue

            # 3. Paragraph text
            block_tokens = self.count_tokens(block.content)
            current_page = block.page_number
            if block.section_title:
                current_section = block.section_title

            if buffer_tokens + block_tokens <= self.target_chunk_size:
                buffer_text.append(block.content)
                buffer_tokens += block_tokens
            else:
                # If block itself is huge, split it
                if block_tokens > self.target_chunk_size:
                    flush_buffer()
                    sub_pieces = self._split_text_recursively(block.content, self.target_chunk_size)
                    for piece in sub_pieces:
                        p_tokens = self.count_tokens(piece)
                        chunks.append(
                            ChunkData(
                                content=piece,
                                page_number=current_page,
                                chunk_index=chunk_idx,
                                section_title=current_section,
                                element_type="paragraph",
                                token_count=p_tokens,
                            )
                        )
                        chunk_idx += 1
                else:
                    flush_buffer()
                    buffer_text.append(block.content)
                    buffer_tokens = block_tokens

        flush_buffer()
        return chunks
