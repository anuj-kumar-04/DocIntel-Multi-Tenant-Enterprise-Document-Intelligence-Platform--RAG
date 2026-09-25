import asyncio
import os
import uuid
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.config import settings
from app.core.security import create_access_token, get_password_hash
from app.deps import get_db
from app.main import app
from app.models.base import Base
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.org import Organization
from app.models.user import User, UserRole
from app.services.embeddings import embedding_service

# In-memory SQLite async engine for lightning-fast self-contained unit and isolation tests
test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a pristine database session with schema for each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create an AsyncClient with database dependency overridden."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


class SeededTenant:
    def __init__(self, org: Organization, owner: User, member: User, token_owner: str, token_member: str):
        self.org = org
        self.owner = owner
        self.member = member
        self.owner_token = token_owner
        self.member_token = token_member
        self.owner_headers = {"Authorization": f"Bearer {token_owner}"}
        self.member_headers = {"Authorization": f"Bearer {token_member}"}


@pytest_asyncio.fixture(scope="function")
async def seed_two_tenants(db_session: AsyncSession) -> tuple[SeededTenant, SeededTenant]:
    """Seed two completely distinct tenant organizations for strict isolation testing."""
    # Org A: Acme Corp
    org_a = Organization(
        id=uuid.uuid4(),
        name="Acme Corp",
        slug="acme-corp",
        monthly_token_budget=1_000_000,
        tokens_used_this_month=0,
    )
    db_session.add(org_a)
    await db_session.flush()

    user_a_owner = User(
        id=uuid.uuid4(),
        org_id=org_a.id,
        email="owner@acme.com",
        full_name="Acme Owner",
        hashed_password=get_password_hash("SecretPass123!"),
        role=UserRole.OWNER,
        is_active=True,
    )
    user_a_member = User(
        id=uuid.uuid4(),
        org_id=org_a.id,
        email="member@acme.com",
        full_name="Acme Member",
        hashed_password=get_password_hash("SecretPass123!"),
        role=UserRole.MEMBER,
        is_active=True,
    )
    db_session.add_all([user_a_owner, user_a_member])

    # Org B: Zephyr Industries
    org_b = Organization(
        id=uuid.uuid4(),
        name="Zephyr Industries",
        slug="zephyr-corp",
        monthly_token_budget=500_000,
        tokens_used_this_month=0,
    )
    db_session.add(org_b)
    await db_session.flush()

    user_b_owner = User(
        id=uuid.uuid4(),
        org_id=org_b.id,
        email="owner@zephyr.com",
        full_name="Zephyr Owner",
        hashed_password=get_password_hash("SecretPass123!"),
        role=UserRole.OWNER,
        is_active=True,
    )
    user_b_member = User(
        id=uuid.uuid4(),
        org_id=org_b.id,
        email="member@zephyr.com",
        full_name="Zephyr Member",
        hashed_password=get_password_hash("SecretPass123!"),
        role=UserRole.MEMBER,
        is_active=True,
    )
    db_session.add_all([user_b_owner, user_b_member])
    await db_session.commit()

    token_a_owner = create_access_token(user_a_owner.id, org_a.id, UserRole.OWNER.value)
    token_a_member = create_access_token(user_a_member.id, org_a.id, UserRole.MEMBER.value)

    token_b_owner = create_access_token(user_b_owner.id, org_b.id, UserRole.OWNER.value)
    token_b_member = create_access_token(user_b_member.id, org_b.id, UserRole.MEMBER.value)

    tenant_a = SeededTenant(org_a, user_a_owner, user_a_member, token_a_owner, token_a_member)
    tenant_b = SeededTenant(org_b, user_b_owner, user_b_member, token_b_owner, token_b_member)

    return tenant_a, tenant_b
