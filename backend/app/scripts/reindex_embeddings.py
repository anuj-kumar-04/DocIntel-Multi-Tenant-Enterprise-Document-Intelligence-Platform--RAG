import asyncio
import re
from sqlalchemy import text
from app.deps import AsyncSessionLocal
from app.services.embeddings import embedding_service
from app.core.logging import logger

async def reindex_all_chunks():
    print("=== Starting Re-indexing with Fastembed (BAAI/bge-small-en-v1.5) ===")
    async with AsyncSessionLocal() as db:
        # Fetch all chunks
        result = await db.execute(text("SELECT id, content FROM chunks ORDER BY created_at ASC"))
        rows = result.fetchall()
        total = len(rows)
        print(f"Total chunks to re-index: {total}")

        batch_size = 32
        for start_idx in range(0, total, batch_size):
            batch = rows[start_idx : start_idx + batch_size]
            cleaned_texts = []
            ids = []
            for r in batch:
                c_id, content = r[0], r[1]
                # Clean invisible characters
                clean_c = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", content or "").strip()
                cleaned_texts.append(clean_c if clean_c else "empty")
                ids.append(str(c_id))

            # Generate real fastembed embeddings
            embeddings = embedding_service.embed_documents(cleaned_texts)

            # Update DB
            for chunk_id, emb in zip(ids, embeddings):
                vec_str = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
                await db.execute(
                    text("UPDATE chunks SET embedding = CAST(:vec AS vector) WHERE id = CAST(:id AS uuid)"),
                    {"vec": vec_str, "id": chunk_id}
                )

            await db.commit()
            print(f"Re-indexed {min(start_idx + batch_size, total)} / {total} chunks...")

    print("=== Re-indexing completed successfully! ===")

if __name__ == "__main__":
    asyncio.run(reindex_all_chunks())
