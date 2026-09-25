"""Initial multi-tenant schema with pgvector

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-25 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Organizations
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=255), nullable=False),
        sa.Column('plan', sa.String(length=50), server_default='enterprise', nullable=False),
        sa.Column('monthly_token_budget', sa.BigInteger(), server_default='1000000', nullable=False),
        sa.Column('tokens_used_this_month', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)

    # 3. Users
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), server_default='member', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_org_id', 'users', ['org_id'])
    op.create_index('ix_users_org_role', 'users', ['org_id', 'role'])

    # 4. Documents
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('filename', sa.String(length=512), nullable=False),
        sa.Column('s3_key', sa.String(length=1024), nullable=False),
        sa.Column('mime_type', sa.String(length=128), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('page_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='queued', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('chunk_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_documents_org_id', 'documents', ['org_id'])
    op.create_index('ix_documents_org_status', 'documents', ['org_id', 'status'])
    op.create_index('ix_documents_org_hash', 'documents', ['org_id', 'content_hash'])

    # 5. Chunks
    op.create_table(
        'chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', content)", persisted=True), nullable=True),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(384), nullable=True),
        sa.Column('page_number', sa.Integer(), server_default='1', nullable=False),
        sa.Column('chunk_index', sa.Integer(), server_default='0', nullable=False),
        sa.Column('section_title', sa.String(length=512), nullable=True),
        sa.Column('element_type', sa.String(length=64), server_default='paragraph', nullable=False),
        sa.Column('token_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_chunks_org_id', 'chunks', ['org_id'])
    op.create_index('ix_chunks_document_id', 'chunks', ['document_id'])
    op.create_index('ix_chunks_document_page', 'chunks', ['document_id', 'page_number'])
    op.create_index('ix_chunks_tsv', 'chunks', ['content_tsv'], postgresql_using='gin')
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
    )

    # 6. Conversations
    op.create_table(
        'conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=255), server_default='New Conversation', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_conversations_org_id', 'conversations', ['org_id'])
    op.create_index('ix_conversations_org_user', 'conversations', ['org_id', 'user_id'])

    # 7. Messages
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('citations', postgresql.JSONB(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('completion_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cost_usd', sa.Numeric(precision=10, scale=6), server_default='0.0', nullable=False),
        sa.Column('latency_ms', sa.Integer(), server_default='0', nullable=False),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('trace_id', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])

    # 8. Usage Events
    op.create_table(
        'usage_events',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cost_usd', sa.Numeric(precision=10, scale=6), server_default='0.0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_usage_events_org_created', 'usage_events', ['org_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('usage_events')
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('chunks')
    op.drop_table('documents')
    op.drop_table('users')
    op.drop_table('organizations')
    op.execute("DROP EXTENSION IF EXISTS vector;")
