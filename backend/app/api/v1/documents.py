import hashlib
import io
import uuid
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.errors import ResourceNotFoundError
from app.core.logging import logger
from app.deps import get_current_user, get_db
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentListItemResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.services.storage import storage_service
from app.workers.tasks import ingest_document, process_document_pipeline

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document, stream to object storage, and enqueue background ingestion."""
    # 1. Read file bytes and validate size
    content = await file.read()
    file_size = len(content)

    if file_size > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_BYTES // (1024*1024)} MB",
        )
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # 2. Compute SHA-256 hash for idempotency checking
    content_hash = hashlib.sha256(content).hexdigest()

    # Check for existing document in the same tenant organization
    existing_stmt = select(Document).where(
        Document.org_id == current_user.org_id,
        Document.content_hash == content_hash,
    )
    existing_result = await db.execute(existing_stmt)
    existing_doc = existing_result.scalars().first()

    if existing_doc and existing_doc.status == DocumentStatus.READY:
        return DocumentUploadResponse(
            document_id=existing_doc.id,
            filename=existing_doc.filename,
            status=existing_doc.status,
            message="Document already uploaded and processed for this organization.",
            is_duplicate=True,
        )

    # 3. Stream to S3 / MinIO
    doc_id = uuid.uuid4()
    s3_key = f"org_{current_user.org_id}/{doc_id}_{file.filename}"
    storage_service.upload_file(
        io.BytesIO(content),
        s3_key=s3_key,
        content_type=file.content_type or "application/octet-stream",
    )

    # 4. Insert row in database
    document = Document(
        id=doc_id,
        org_id=current_user.org_id,
        uploaded_by=current_user.id,
        filename=file.filename or "uploaded_file",
        s3_key=s3_key,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=file_size,
        status=DocumentStatus.QUEUED,
        content_hash=content_hash,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # 5. Dispatch background task: Celery primary, FastAPI background task fallback
    enqueued_celery = False
    try:
        ingest_document.delay(str(document.id))
        enqueued_celery = True
    except Exception as e:
        logger.warning(f"Celery enqueue skipped or unavailable ({e}); running via FastAPI background task.")

    if not enqueued_celery:
        background_tasks.add_task(process_document_pipeline, str(document.id))

    return DocumentUploadResponse(
        document_id=document.id,
        filename=document.filename,
        status=document.status,
        message="Document uploaded successfully. Ingestion in progress.",
        is_duplicate=False,
    )


@router.get("", response_model=list[DocumentListItemResponse])
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all documents belonging strictly to the user's organization."""
    stmt = (
        select(Document)
        .where(Document.org_id == current_user.org_id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve live processing status of a document for polling."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.org_id == current_user.org_id,  # Strict tenant isolation
    )
    result = await db.execute(stmt)
    doc = result.scalars().first()
    if not doc:
        raise ResourceNotFoundError("Document", str(document_id))

    return DocumentStatusResponse(
        document_id=doc.id,
        filename=doc.filename,
        status=doc.status,
        chunk_count=doc.chunk_count,
        page_count=doc.page_count,
        error_message=doc.error_message,
        processed_at=doc.processed_at,
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_detail(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve full document details and generated chunks."""
    stmt = (
        select(Document)
        .where(
            Document.id == document_id,
            Document.org_id == current_user.org_id,  # Strict tenant isolation
        )
        .options(selectinload(Document.chunks))
    )
    result = await db.execute(stmt)
    doc = result.scalars().first()
    if not doc:
        raise ResourceNotFoundError("Document", str(document_id))

    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document, its S3 blob, and all child chunks in single transaction."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.org_id == current_user.org_id,  # Strict tenant isolation
    )
    result = await db.execute(stmt)
    doc = result.scalars().first()
    if not doc:
        raise ResourceNotFoundError("Document", str(document_id))

    # Delete from S3 storage
    storage_service.delete_file(doc.s3_key)

    # Delete from database (cascades to chunks)
    await db.delete(doc)
    await db.commit()
    return None
