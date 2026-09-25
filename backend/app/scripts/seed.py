import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from sqlalchemy import select
from app.core.security import get_password_hash
from app.deps import AsyncSessionLocal
from app.models.chat import Conversation, Message, MessageRole
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.org import Organization
from app.models.user import User, UserRole
from app.services.embeddings import embedding_service


async def seed_database():
    """Populate database with multi-tenant realistic organizations, documents, and chunks."""
    print("[SEED] Starting DocIntel database seeding...")

    async with AsyncSessionLocal() as session:
        # 1. Organization A: Acme Corporation
        org_a_stmt = select(Organization).where(Organization.slug == "acme-corp")
        res_a = await session.execute(org_a_stmt)
        org_a = res_a.scalars().first()

        if not org_a:
            org_a = Organization(
                id=uuid.uuid4(),
                name="Acme Corporation",
                slug="acme-corp",
                plan="enterprise",
                monthly_token_budget=2_500_000,
                tokens_used_this_month=142_300,
            )
            session.add(org_a)
            await session.flush()
            print(f"[OK] Created Org A: {org_a.name} ({org_a.id})")
        else:
            print(f"[INFO] Org A already exists: {org_a.name}")

        # 2. Organization B: Zephyr Industries (for isolation testing)
        org_b_stmt = select(Organization).where(Organization.slug == "zephyr-industries")
        res_b = await session.execute(org_b_stmt)
        org_b = res_b.scalars().first()

        if not org_b:
            org_b = Organization(
                id=uuid.uuid4(),
                name="Zephyr Industries",
                slug="zephyr-industries",
                plan="growth",
                monthly_token_budget=750_000,
                tokens_used_this_month=68_900,
            )
            session.add(org_b)
            await session.flush()
            print(f"[OK] Created Org B: {org_b.name} ({org_b.id})")
        else:
            print(f"[INFO] Org B already exists: {org_b.name}")

        # 3. Create Users
        # Org A Owner
        user_a1_stmt = select(User).where(User.email == "admin@acme.com")
        if not (await session.execute(user_a1_stmt)).scalars().first():
            user_a1 = User(
                id=uuid.uuid4(),
                org_id=org_a.id,
                email="admin@acme.com",
                full_name="Sarah Connor (VP of Tech)",
                hashed_password=get_password_hash("Password123!"),
                role=UserRole.OWNER,
                is_active=True,
            )
            session.add(user_a1)

        # Org A Member
        user_a2_stmt = select(User).where(User.email == "analyst@acme.com")
        if not (await session.execute(user_a2_stmt)).scalars().first():
            user_a2 = User(
                id=uuid.uuid4(),
                org_id=org_a.id,
                email="analyst@acme.com",
                full_name="James Miller (Research Lead)",
                hashed_password=get_password_hash("Password123!"),
                role=UserRole.MEMBER,
                is_active=True,
            )
            session.add(user_a2)

        # Org B Owner
        user_b1_stmt = select(User).where(User.email == "admin@zephyr.com")
        if not (await session.execute(user_b1_stmt)).scalars().first():
            user_b1 = User(
                id=uuid.uuid4(),
                org_id=org_b.id,
                email="admin@zephyr.com",
                full_name="Dr. Elena Rostova (Chief Scientist)",
                hashed_password=get_password_hash("Password123!"),
                role=UserRole.OWNER,
                is_active=True,
            )
            session.add(user_b1)

        await session.flush()
        print("[OK] Seeded user accounts")

        # 4. Seed Documents & Chunks for Org A (Acme)
        doc_a1_stmt = select(Document).where(Document.filename == "Acme_Q4_Financial_Report.pdf")
        if not (await session.execute(doc_a1_stmt)).scalars().first():
            doc_a1 = Document(
                id=uuid.uuid4(),
                org_id=org_a.id,
                filename="Acme_Q4_Financial_Report.pdf",
                s3_key=f"org_{org_a.id}/Acme_Q4_Financial_Report.pdf",
                mime_type="application/pdf",
                size_bytes=1_248_500,
                page_count=3,
                chunk_count=3,
                status=DocumentStatus.READY,
                processed_at=datetime.now(timezone.utc),
            )
            session.add(doc_a1)
            await session.flush()

            # Chunks for Doc A1
            c1_text = (
                "In Q4 fiscal year 2024, Acme Corporation posted record consolidated revenue of $14.8 billion, "
                "representing a 16.4% year-over-year increase. Cloud Infrastructure and AI enterprise services "
                "surpassed expectations, contributing $6.2 billion in quarterly revenue, up 31% from the prior year. "
                "Operating cash flow reached $4.1 billion, maintaining strong capital reserves for strategic R&D initiatives."
            )
            c2_text = (
                "### Segment Financial Breakdown\n"
                "| Segment | Q4 FY24 Revenue | Operating Margin | YoY Growth |\n"
                "| --- | --- | --- | --- |\n"
                "| Cloud & AI Platform | $6,200M | 34.2% | +31.0% |\n"
                "| Enterprise Software | $4,500M | 28.5% | +11.2% |\n"
                "| Hardware Solutions | $2,700M | 18.1% | +4.3% |\n"
                "| Professional Services | $1,400M | 14.8% | +2.1% |\n"
                "Operating margin expansion was driven by automation and procurement efficiencies."
            )
            c3_text = (
                "Forward Guidance and FY2025 Outlook:\n"
                "Management projects full-year FY2025 revenue between $61.0 billion and $63.5 billion, with "
                "Cloud Solutions driving over 45% of total bookings. Projected operating margin target remains at 29.5%. "
                "Free cash flow conversion is anticipated to exceed 85% of net income."
            )

            chunks_data = [
                (c1_text, 1, 0, "Financial Overview", "paragraph"),
                (c2_text, 2, 1, "Segment Financial Breakdown", "table"),
                (c3_text, 3, 2, "Guidance & Outlook", "paragraph"),
            ]

            for content, page, idx, sec, el_type in chunks_data:
                vec = embedding_service.embed_query(content)
                ch = Chunk(
                    document_id=doc_a1.id,
                    org_id=org_a.id,
                    content=content,
                    embedding=vec,
                    page_number=page,
                    chunk_index=idx,
                    section_title=sec,
                    element_type=el_type,
                    token_count=len(content.split()) * 4 // 3,
                )
                session.add(ch)

            print("[OK] Seeded Acme Q4 Financial Report with table chunks")

        # 5. Seed Documents & Chunks for Org B (Zephyr Industries) - CONFIDENTIAL MARGIN
        doc_b1_stmt = select(Document).where(Document.filename == "Zephyr_Proprietary_Margin_Analysis.pdf")
        if not (await session.execute(doc_b1_stmt)).scalars().first():
            doc_b1 = Document(
                id=uuid.uuid4(),
                org_id=org_b.id,
                filename="Zephyr_Proprietary_Margin_Analysis.pdf",
                s3_key=f"org_{org_b.id}/Zephyr_Proprietary_Margin_Analysis.pdf",
                mime_type="application/pdf",
                size_bytes=840_000,
                page_count=2,
                chunk_count=2,
                status=DocumentStatus.READY,
                processed_at=datetime.now(timezone.utc),
            )
            session.add(doc_b1)
            await session.flush()

            zb_text1 = (
                "CONFIDENTIAL — ZEPHYR INDUSTRIES INTERNAL USE ONLY\n"
                "The Zephyrite quarterly margin for Q3 achieved an unprecedented 47.8%, driven by proprietary "
                "quantum turbine manufacturing contracts with aerospace primes. The patent-pending Zephyrite alloy "
                "reduced thermal loss by 22% compared to standard titanium composites."
            )
            zb_text2 = (
                "Quarterly turbine shipments totaled 142 units in EMEA, with gross profit per unit exceeding $180,000. "
                "Zephyrite quarterly margin targets for the next fiscal year remain pegged at 49.0% minimum."
            )

            for content, page, idx in [(zb_text1, 1, 0), (zb_text2, 2, 1)]:
                vec = embedding_service.embed_query(content)
                ch = Chunk(
                    document_id=doc_b1.id,
                    org_id=org_b.id,
                    content=content,
                    embedding=vec,
                    page_number=page,
                    chunk_index=idx,
                    section_title="Confidential Margin Data",
                    element_type="paragraph",
                    token_count=len(content.split()) * 4 // 3,
                )
                session.add(ch)

            print("[OK] Seeded Zephyr confidential documents for tenant isolation testing")

        await session.commit()
        print("[SUCCESS] Database seeding completed successfully!")


if __name__ == "__main__":
    asyncio.run(seed_database())
