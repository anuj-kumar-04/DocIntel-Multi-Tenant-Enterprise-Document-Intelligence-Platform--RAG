from collections.abc import AsyncGenerator
import json
import os
import re
import time
from typing import Any
try:
    import litellm
except ImportError:
    litellm = None

from app.config import settings
from app.core.logging import logger

REFUSAL_MESSAGE = "I could not find this in the provided documents."

SYSTEM_PROMPT = """You are DocIntel, an enterprise document intelligence assistant.
Your goal is to provide comprehensive, detailed, well-structured, and authoritative answers grounded strictly in the provided context.

STRICT RULES:
1. Answer using ONLY the numbered context below.
2. Provide thorough, complete, and exhaustive explanations. Do not provide overly brief or one-line answers when rich context is available in the documents. Break down key concepts, definitions, components, comparisons, advantages, and mechanisms into clear paragraphs, structured bullet points, or tables.
3. Cite every factual statement, explanation, and bullet point with its corresponding bracketed source number, e.g. [1] or [2].
4. If the context does not contain the answer at all, reply exactly:
"I could not find this in the provided documents."
5. Never use outside knowledge. Never invent numbers. Never hallucinate facts or citations.
"""


def build_context_block(chunks: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Assemble context chunks with 1-based indexing for inline citations."""
    context_lines = []
    indexed_sources = []

    for i, chunk in enumerate(chunks, start=1):
        filename = chunk.get("filename", "document")
        page = chunk.get("page_number", 1)
        raw_content = chunk.get("content", "").strip()
        section_title = chunk.get("section_title")

        # Clean invisible directional/formatting characters (e.g. \u202d, \u202c, \ufeff)
        clean_content = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", raw_content).strip()
        clean_section = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", section_title).strip() if section_title else None

        header = f"[{i}] ({filename}, p.{page})"
        if clean_section:
            header += f" - Section: {clean_section}"

        context_lines.append(f"{header}\n{clean_content}")
        indexed_sources.append(
            {
                "index": i,
                "chunk_id": str(chunk.get("id")),
                "document_id": str(chunk.get("document_id")),
                "filename": filename,
                "page": page,
                "section_title": clean_section,
                "snippet": clean_content[:250] + ("..." if len(clean_content) > 250 else ""),
            }
        )

    context_str = "\n\n".join(context_lines)
    return context_str, indexed_sources


def verify_and_clean_citations(
    raw_answer: str, indexed_sources: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    """Post-check: verify cited indices exist in context, purge hallucinated numbers."""
    if not indexed_sources or REFUSAL_MESSAGE.lower() in raw_answer.lower():
        # Remove any stray citations from refusal message
        cleaned = re.sub(r"\[\d+\]", "", raw_answer).strip()
        return cleaned, []

    valid_indices = {src["index"]: src for src in indexed_sources}
    cited_indices = set(map(int, re.findall(r"\[(\d+)\]", raw_answer)))

    surviving_citations: list[dict[str, Any]] = []
    cleaned_answer = raw_answer

    # Replace invalid citation indices
    for idx in cited_indices:
        if idx in valid_indices:
            surviving_citations.append(valid_indices[idx])
        else:
            # Strip invalid citation from text
            cleaned_answer = re.sub(rf"\[{idx}\]", "", cleaned_answer)

    # Sort surviving citations by index
    surviving_citations.sort(key=lambda x: x["index"])
    # Clean redundant whitespaces
    cleaned_answer = re.sub(r"\s{2,}", " ", cleaned_answer).strip()

    return cleaned_answer, surviving_citations


def synthesize_smart_grounded_answer(
    question: str,
    chunks: list[dict[str, Any]],
    indexed_sources: list[dict[str, Any]],
) -> str:
    """Smart grounded extractive synthesis when no cloud LLM API key is provided."""
    q_clean = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", question).strip()
    q_lower = q_clean.lower()

    stop_words = {
        "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
        "the", "and", "for", "with", "this", "that", "from", "are", "is", "was",
        "were", "tell", "explain", "about", "give", "show", "does", "did", "can",
        "could", "would", "should", "between", "difference", "differences"
    }
    q_words = [w for w in re.findall(r"\w+", q_lower) if len(w) > 2 and w not in stop_words]

    # Clean and score all chunks
    cleaned_chunks = []
    has_any_match = False

    for i, chunk in enumerate(chunks, start=1):
        raw_content = chunk.get("content", "")
        clean_c = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", raw_content).strip()
        c_lower = clean_c.lower()

        overlap = sum(1 for w in q_words if w in c_lower)
        if overlap > 0:
            has_any_match = True

        cleaned_chunks.append({
            "index": i,
            "filename": chunk.get("filename", "document"),
            "page": chunk.get("page_number", 1),
            "content": clean_c,
            "overlap": overlap,
            "raw": chunk,
        })

    # Strict Refusal Gate: If question keywords have NO match in retrieved context
    if q_words and not has_any_match:
        return REFUSAL_MESSAGE

    # Sort chunks by keyword overlap
    cleaned_chunks.sort(key=lambda x: x["overlap"], reverse=True)

    # 1. Check for "Difference" or comparison intent
    is_diff = any(w in q_lower for w in ["difference", "differences", "vs", "versus", "compare", "comparison"])
    if is_diff:
        for c in cleaned_chunks:
            idx = c["index"]
            lines = [l.strip() for l in c["content"].split("\n") if l.strip()]
            table_lines = [l for l in lines if l.startswith("|")]
            if len(table_lines) >= 3:
                clean_table = [re.sub(r"\s{2,}", " ", r).strip() for r in table_lines]
                return f"Based on the documents, here is the comparison:\n\n" + "\n".join(clean_table) + f"\n\n[{idx}]"

        diff_points = []
        for c in cleaned_chunks:
            idx = c["index"]
            lines = [l.strip() for l in c["content"].split("\n") if l.strip()]
            current_topic = None
            current_details = []
            for line in lines:
                if line.startswith("##") or (len(line) < 30 and not line.endswith(".")):
                    if current_topic and current_details:
                        detail_text = " ".join(current_details)
                        diff_points.append(f"• **{current_topic}**: {detail_text} [{idx}]")
                        current_details = []
                    current_topic = re.sub(r"^#+\s*", "", line)
                else:
                    if current_topic:
                        current_details.append(line)
            if current_topic and current_details:
                detail_text = " ".join(current_details)
                diff_points.append(f"• **{current_topic}**: {detail_text} [{idx}]")

        if diff_points:
            return "Based on the documents, here is the comparison:\n\n" + "\n\n".join(diff_points[:6])

    # 2. Check for definition / "what is" intent
    is_def = any(w in q_lower for w in ["what is", "define", "meaning of", "definition of", "what are", "overview", "explain"]) or len(q_words) <= 2
    if is_def:
        def_sections = []
        for c in cleaned_chunks:
            idx = c["index"]
            content = c["content"]
            prose_paragraphs = [
                re.sub(r"^[#●•\s\-*]+", "", p).strip()
                for p in content.split("\n\n")
                if len(p.strip()) > 25 and not p.strip().startswith("|")
            ]
            for p in prose_paragraphs:
                p_lower = p.lower()
                if any(qw in p_lower for qw in q_words):
                    clean_p = " ".join(p.split())
                    def_sections.append(f"{clean_p} [{idx}]")
                    if len(def_sections) >= 4:
                        break
            if len(def_sections) >= 4:
                break

        if def_sections:
            return "Based on the documents:\n\n" + "\n\n".join(def_sections)

    # 3. Financial / Metric intent (e.g. profit, revenue, numbers)
    has_metrics = any(w in q_lower for w in ["profit", "revenue", "income", "currency", "sales", "ebit", "loss", "cost", "margin", "2024", "2023", "2022", "balance", "total", "cash"])
    if has_metrics:
        metric_results = []
        for c in cleaned_chunks:
            idx = c["index"]
            raw_lines = [l.strip() for l in c["content"].split("\n") if l.strip()]

            # Determine unit of measurement if present (e.g. In millions of CHF)
            unit_str = ""
            for l in raw_lines:
                if any(k in l.lower() for k in ["millions of", "thousands of", "billions of", "in chf", "in usd", "in eur"]):
                    unit_str = re.sub(r"^[#\s\-*]+", "", l).strip()
                    break

            # Find year column headers if present
            years = []
            for i_l in range(len(raw_lines) - 1):
                if re.match(r"^(202[0-9])$", raw_lines[i_l]) and re.match(r"^(202[0-9])$", raw_lines[i_l + 1]):
                    years = [raw_lines[i_l], raw_lines[i_l + 1]]
                    break
            if not years:
                for l in raw_lines:
                    found_years = re.findall(r"\b(202[0-9])\b", l)
                    if len(found_years) >= 2:
                        years = found_years[:2]
                        break

            # Look for lines matching target metric keywords
            scored_metrics = []
            for i, line in enumerate(raw_lines):
                l_lower = line.lower()
                clean_label = re.sub(r"^[#●•\s\-*]+", "", line).strip()
                clean_lower = clean_label.lower()
                if (
                    clean_label.startswith("Consolidated Financial")
                    or clean_label.startswith("Notes")
                    or clean_label.startswith("##")
                    or clean_lower.startswith("for the year")
                    or clean_lower.startswith("as at december")
                    or clean_lower.startswith("consolidated statement")
                    or clean_lower.startswith("income statement")
                    or clean_lower == "2024"
                    or clean_lower == "2023"
                ):
                    continue

                # Match if query terms appear in line
                overlap = sum(1 for qw in q_words if qw in l_lower)
                if overlap > 0:
                    inline_nums = re.findall(r"[\d\(\)]+(?:\s+\d+)*", clean_label)
                    inline_val = [n for n in inline_nums if len(n) >= 2 and not re.match(r"^(202[0-9])$", n)]

                    # Collect numbers on subsequent lines
                    subsequent_vals = []
                    for next_line in raw_lines[i + 1 : i + 6]:
                        clean_next = next_line.strip()
                        if re.search(r"[\d\(\)]+", clean_next) and len(clean_next) < 25 and not re.match(r"^(202[0-9])$", clean_next):
                            subsequent_vals.append(clean_next)
                        else:
                            break

                    if subsequent_vals:
                        if years and len(subsequent_vals) == len(years) + 1:
                            note_ref = subsequent_vals[0]
                            num_vals = subsequent_vals[1:]
                            val_str = " | ".join(f"{y}: {v}" for y, v in zip(years, num_vals)) + f" (Note {note_ref})"
                        elif years and len(subsequent_vals) == len(years):
                            val_str = " | ".join(f"{y}: {v}" for y, v in zip(years, subsequent_vals))
                        else:
                            val_str = " | ".join(subsequent_vals)
                        scored_metrics.append((overlap, f"• **{clean_label}**: {val_str}" + (f" ({unit_str})" if unit_str else "") + f" [{idx}]"))
                    elif inline_val:
                        scored_metrics.append((overlap, f"• **{clean_label}**" + (f" ({unit_str})" if unit_str else "") + f" [{idx}]"))

            if scored_metrics:
                scored_metrics.sort(key=lambda x: x[0], reverse=True)
                metric_results.extend([item[1] for item in scored_metrics[:4]])
                break

        if metric_results:
            return "Based on the documents:\n\n" + "\n".join(metric_results[:4])

    # 4. General extractive synthesis from top matching chunks
    extracted_paragraphs = []
    total_len = 0
    for c in cleaned_chunks:
        if c["overlap"] == 0:
            continue
        idx = c["index"]
        raw_paras = [p.strip() for p in c["content"].split("\n\n") if len(p.strip()) > 25 and not p.strip().startswith("|")]
        for p in raw_paras:
            clean_p = re.sub(r"^[#●•\s\-*]+", "", p).strip()
            clean_p = " ".join(clean_p.split())
            if any(qw in clean_p.lower() for qw in q_words):
                extracted_paragraphs.append(f"{clean_p} [{idx}]")
                total_len += len(clean_p)
                if total_len > 1500 or len(extracted_paragraphs) >= 5:
                    break
        if total_len > 1500 or len(extracted_paragraphs) >= 5:
            break

    if extracted_paragraphs:
        return "Based on the documents:\n\n" + "\n\n".join(extracted_paragraphs)

    top = cleaned_chunks[0]
    first_p = re.sub(r"^[#●•\s\-*]+", "", top["content"][:800]).strip()
    return f"Based on the documents:\n\n{first_p} [{top['index']}]"



class GenerationService:
    """Orchestrates LiteLLM multi-provider routing and token streaming."""

    def __init__(self):
        if litellm:
            litellm.drop_params = True
            litellm.telemetry = False
            if settings.GROQ_API_KEY and not settings.GROQ_API_KEY.startswith("mock-"):
                os.environ["GROQ_API_KEY"] = settings.GROQ_API_KEY
            if settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("mock-"):
                os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
            if settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith("mock-"):
                os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    async def generate_stream(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        history: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream answer tokens, verify citations, and emit usage metrics."""
        # 1. Check if chunks are empty
        if not chunks:
            yield {"type": "token", "token": REFUSAL_MESSAGE}
            yield {"type": "citations", "citations": []}
            yield {
                "type": "usage",
                "prompt_tokens": 0,
                "completion_tokens": len(REFUSAL_MESSAGE.split()),
                "cost_usd": 0.0,
                "model": "refusal_gate",
            }
            yield {"type": "done", "status": "completed"}
            return

        # 2. Build context
        context_str, indexed_sources = build_context_block(chunks)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            for h in history[-6:]:
                messages.append({"role": h["role"], "content": h["content"]})

        user_content = f"Question: {question}\n\nContext:\n{context_str}"
        messages.append({"role": "user", "content": user_content})

        # 3. Model cascade: Groq -> Gemini -> OpenAI -> Smart Grounded Fallback
        # Only attempt cloud providers if a real API key (not placeholder) is configured
        models_to_try = []
        if settings.GROQ_API_KEY and not settings.GROQ_API_KEY.startswith("mock-"):
            if settings.DEFAULT_LLM_MODEL:
                models_to_try.append(settings.DEFAULT_LLM_MODEL)
            if "groq/qwen/qwen3.8-27b" not in models_to_try:
                models_to_try.append("groq/qwen/qwen3.8-27b")
        if settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("mock-"):
            if settings.FALLBACK_LLM_MODEL and settings.FALLBACK_LLM_MODEL not in models_to_try:
                models_to_try.append(settings.FALLBACK_LLM_MODEL)
            if "gemini/gemini-3.5-flash-lite" not in models_to_try:
                models_to_try.append("gemini/gemini-3.5-flash-lite")
        if settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith("mock-"):
            models_to_try.append("openai/gpt-4o-mini")

        full_answer = []
        model_used = "docintel_grounded_engine"
        success = False

        if litellm and models_to_try:
            for model_name in models_to_try:
                try:
                    api_key = None
                    if "groq" in model_name:
                        api_key = settings.GROQ_API_KEY
                    elif "gemini" in model_name:
                        api_key = settings.GEMINI_API_KEY
                    elif "openai" in model_name or "gpt" in model_name:
                        api_key = settings.OPENAI_API_KEY

                    response = await litellm.acompletion(
                        model=model_name,
                        messages=messages,
                        stream=True,
                        temperature=0.2,
                        max_tokens=2048,
                        api_key=api_key,
                    )
                    chunks_count = 0
                    async for chunk in response:
                        delta = chunk.choices[0].delta.content or ""
                        if delta:
                            full_answer.append(delta)
                            yield {"type": "token", "token": delta}
                            chunks_count += 1

                    if "".join(full_answer).strip():
                        model_used = model_name
                        success = True
                        break
                    else:
                        full_answer.clear()
                        logger.warning(f"Model {model_name} generated empty response. Trying next...")
                except Exception as e:
                    logger.warning(f"Model {model_name} failed: {e}. Attempting fallback...")
                    full_answer.clear()

        # 4. If no cloud provider succeeded, provide smart grounded extractive synthesis
        if not success:
            model_used = "docintel_grounded_engine"
            smart_text = synthesize_smart_grounded_answer(question, chunks, indexed_sources)
            for char in smart_text:
                full_answer.append(char)
                yield {"type": "token", "token": char}

        raw_complete_text = "".join(full_answer)

        # 5. Citation verification
        cleaned_text, verified_citations = verify_and_clean_citations(
            raw_complete_text, indexed_sources
        )

        prompt_tokens = len(context_str.split()) * 4 // 3
        completion_tokens = len(raw_complete_text.split()) * 4 // 3
        cost_usd = round(
            (prompt_tokens * 0.0000005) + (completion_tokens * 0.0000015), 6
        )

        yield {"type": "citations", "citations": verified_citations}
        yield {
            "type": "usage",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "model": model_used,
            "full_answer": cleaned_text,
        }
        yield {"type": "done", "status": "completed"}


generation_service = GenerationService()
