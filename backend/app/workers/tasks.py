import asyncio
import uuid
from datetime import UTC, datetime

from celery import shared_task
from sqlalchemy import select

from app.core.logging import logger
from app.deps import AsyncSessionLocal
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.chunking import LayoutChunker
from app.services.embeddings import embedding_service
from app.services.parsing import DocumentParser
from app.services.storage import storage_service


async def process_document_pipeline(document_id: str | uuid.UUID) -> dict:
    """Core asynchronous document ingestion pipeline."""
    doc_uuid = uuid.UUID(str(document_id))
    logger.info(f"Starting ingestion pipeline for document {doc_uuid}")

    async with AsyncSessionLocal() as session:
        # 1. Fetch document record
        stmt = select(Document).where(Document.id == doc_uuid)
        result = await session.execute(stmt)
        document = result.scalars().first()

        if not document:
            logger.error(f"Document {doc_uuid} not found")
            return {"status": "error", "message": "Document not found"}

        try:
            # 2. Update status -> PARSING
            document.status = DocumentStatus.PARSING
            await session.commit()

            # 3. Download file from S3 / MinIO
            file_bytes = storage_service.download_file(document.s3_key)

            # 4. Parse content layout-aware
            blocks, page_count = DocumentParser.parse(
                file_bytes, document.filename, document.mime_type
            )
            document.page_count = page_count

            # 5. Chunk layout-aware
            chunker = LayoutChunker(target_chunk_size=700, chunk_overlap=100)
            chunk_records = chunker.chunk_blocks(blocks)

            if not chunk_records:
                raise ValueError("Parsed document yielded zero readable text chunks")

            # 6. Update status -> EMBEDDING
            document.status = DocumentStatus.EMBEDDING
            await session.commit()

            # 7. Generate batched embeddings
            texts = [c.content for c in chunk_records]
            embeddings = embedding_service.embed_documents(texts)

            # 8. Bulk create Chunks with denormalized org_id
            db_chunks = []
            for c_data, emb in zip(chunk_records, embeddings, strict=False):
                db_chunk = Chunk(
                    document_id=document.id,
                    org_id=document.org_id,  # Critical tenant denormalization
                    content=c_data.content,
                    embedding=emb,
                    page_number=c_data.page_number,
                    chunk_index=c_data.chunk_index,
                    section_title=c_data.section_title,
                    element_type=c_data.element_type,
                    token_count=c_data.token_count,
                )
                db_chunks.append(db_chunk)

            session.add_all(db_chunks)

            # 9. Update status -> READY
            document.status = DocumentStatus.READY
            document.chunk_count = len(db_chunks)
            document.processed_at = datetime.now(UTC)
            document.error_message = None

            await session.commit()
            logger.info(
                f"Document {doc_uuid} successfully ingested: {len(db_chunks)} chunks, {page_count} pages"
            )

            return {
                "status": "ready",
                "document_id": str(document.id),
                "chunks": len(db_chunks),
                "pages": page_count,
            }

        except Exception as exc:
            logger.exception(f"Document ingestion failed for {doc_uuid}: {exc}")
            document.status = DocumentStatus.FAILED
            document.error_message = str(exc)[:1000]
            await session.commit()
            raise


@shared_task(
    bind=True,
    name="app.workers.tasks.ingest_document",
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
)
def ingest_document(self, document_id: str):
    """Celery background worker entrypoint with exponential backoff."""
    try:
        return asyncio.run(process_document_pipeline(document_id))
    except Exception as exc:
        logger.error(f"Task retry for document {document_id}: {exc}")
        raise self.retry(exc=exc) from exc
