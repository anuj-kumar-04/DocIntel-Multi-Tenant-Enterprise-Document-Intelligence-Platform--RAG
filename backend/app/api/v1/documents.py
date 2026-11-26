import hashlib
import io
import os
import re
import uuid
import zipfile

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
from app.services.audit import AuditService
from app.services.cache import semantic_cache
from app.services.storage import storage_service
from app.workers.tasks import ingest_document, process_document_pipeline
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

ALLOWED_EXTENSIONS = set(ALLOWED_MIME_TYPES.values())
_MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # 100 MB decompression bomb guard


def sanitize_filename(raw_name: str | None) -> str:
    """Strip path segments and unsafe characters from uploaded filenames."""
    base = os.path.basename((raw_name or "uploaded_file").replace("\\", "/"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    return cleaned[:200] or "uploaded_file"


def validate_uploaded_file(filename: str, content_type: str | None, content: bytes) -> str:
    """Validate extension, MIME type, binary magic bytes, and zip-bomb thresholds."""
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file extension '{ext or 'none'}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    mime = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if mime != "application/octet-stream" and mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported media type '{mime}'.",
        )

    if ext == ".pdf":
        if not content.lstrip().startswith(b"%PDF-"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content does not match PDF signature.",
            )
    elif ext in {".docx", ".xlsx"}:
        if not content.startswith(b"PK\x03\x04"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File content does not match valid {ext.upper()} archive signature.",
            )
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                total_uncompressed = sum(info.file_size for info in zf.infolist())
                if total_uncompressed > _MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Decompressed document archive exceeds safety limit.",
                    )
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Corrupted or malformed {ext.upper()} archive.",
            ) from None
    elif ext in {".doc", ".xls"}:
        if not content.startswith(b"\xd0\xcf\x11\xe0"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File content does not match legacy {ext.upper()} signature.",
            )
    elif ext in {".txt", ".md"}:
        if b"\x00" in content[:4096]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Binary payload rejected for plain-text document.",
            )

    return mime if mime in ALLOWED_MIME_TYPES else "application/octet-stream"


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document, validate signature, stream to S3, and enqueue ingestion."""
    # 1. Read file bytes and validate size
    content = await file.read()
    file_size = len(content)

    if file_size > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB",
        )
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    safe_filename = sanitize_filename(file.filename)
    validated_mime = validate_uploaded_file(safe_filename, file.content_type, content)

    # 2. Compute SHA-256 hash for idempotency checking
    content_hash = hashlib.sha256(content).hexdigest()

    # Check for existing document in the same tenant organization
    existing_stmt = select(Document).where(
        Document.org_id == current_user.org_id,
        Document.content_hash == content_hash,
    )
    existing_result = await db.execute(existing_stmt)
    existing_doc = existing_result.scalars().first()

    if existing_doc and existing_doc.status != DocumentStatus.FAILED:
        return DocumentUploadResponse(
            document_id=existing_doc.id,
            filename=existing_doc.filename,
            status=existing_doc.status,
            message="Document already uploaded and processed for this organization."
            if existing_doc.status == DocumentStatus.READY
            else "Document already uploaded and queued for processing.",
            is_duplicate=True,
        )

    # 3. Stream to S3 / MinIO with sanitized key
    doc_id = uuid.uuid4()
    s3_key = f"org_{current_user.org_id}/{doc_id}_{safe_filename}"
    storage_service.upload_file(
        io.BytesIO(content),
        s3_key=s3_key,
        content_type=validated_mime,
    )

    # 4. Insert row in database
    document = Document(
        id=doc_id,
        org_id=current_user.org_id,
        uploaded_by=current_user.id,
        filename=safe_filename,
        s3_key=s3_key,
        mime_type=validated_mime,
        size_bytes=file_size,
        status=DocumentStatus.QUEUED,
        content_hash=content_hash,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    await AuditService(db).log_event(
        action="DOCUMENT_UPLOADED",
        resource_type="document",
        org_id=current_user.org_id,
        user_id=current_user.id,
        resource_id=str(document.id),
        details={"filename": safe_filename, "size_bytes": file_size},
        request=request,
    )

    # 5. Dispatch background task: Celery primary, FastAPI background task fallback
    enqueued_celery = False
    try:
        ingest_document.delay(str(document.id))
        enqueued_celery = True
    except Exception as e:
        logger.warning(
            f"Celery enqueue skipped or unavailable ({e}); running via FastAPI background task."
        )

    if not enqueued_celery:

        async def _safe_background_ingest(doc_id_str: str) -> None:
            try:
                await process_document_pipeline(doc_id_str)
            except Exception as bg_exc:
                logger.warning(
                    f"Background ingestion ended with handled error for {doc_id_str}: {bg_exc}"
                )

        background_tasks.add_task(_safe_background_ingest, str(document.id))

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
    request: Request,
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

    filename = doc.filename
    # Delete from S3 storage
    storage_service.delete_file(doc.s3_key)

    # Delete from database (cascades to chunks)
    await db.delete(doc)
    await db.commit()
    await semantic_cache.invalidate_org(str(current_user.org_id))

    await AuditService(db).log_event(
        action="DOCUMENT_DELETED",
        resource_type="document",
        org_id=current_user.org_id,
        user_id=current_user.id,
        resource_id=str(document_id),
        details={"filename": filename},
        request=request,
    )
    return None
