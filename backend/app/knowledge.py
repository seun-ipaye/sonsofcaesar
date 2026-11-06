"""Search over the support docs in backend/knowledge.

Each "##" section becomes one chunk. Only public support docs belong here: never
event data, secret addresses or anything about a customer.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import KnowledgeChunk

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / 'knowledge'
VOYAGE_URL = 'https://api.voyageai.com/v1/embeddings'
EMBEDDING_MODEL = 'voyage-3.5'


@dataclass(frozen=True)
class Chunk:
    source: str
    heading: str
    content: str

    @property
    def text(self) -> str:
        """What gets embedded: the heading carries most of the meaning in short sections."""
        return f'{self.heading}\n{self.content}'

    @property
    def hash(self) -> str:
        return hashlib.sha256(f'{EMBEDDING_MODEL}\n{self.source}\n{self.text}'.encode()).hexdigest()


def load_chunks(directory: Path = KNOWLEDGE_DIR) -> list[Chunk]:
    chunks = []
    for path in sorted(directory.glob('*.md')):
        if path.name == 'README.md':
            continue
        for section in path.read_text().split('\n## ')[1:]:
            heading, _, content = section.partition('\n')
            content = content.strip()
            if not content:
                raise ValueError(f'{path.name}: section "{heading}" is empty')
            chunks.append(Chunk(path.name, heading.strip(), content))
    return chunks


def embed(texts: list[str], input_type: str) -> list[list[float]]:
    """input_type is 'document' when indexing and 'query' when searching."""
    if not settings.voyage_api_key:
        raise RuntimeError('VOYAGE_API_KEY is not set')
    response = httpx.post(
        VOYAGE_URL,
        headers={'Authorization': f'Bearer {settings.voyage_api_key}'},
        json={'input': texts, 'model': EMBEDDING_MODEL, 'input_type': input_type},
        timeout=30,
    )
    response.raise_for_status()
    rows = sorted(response.json()['data'], key=lambda row: row['index'])
    return [row['embedding'] for row in rows]


def index_knowledge(db: Session, directory: Path = KNOWLEDGE_DIR) -> dict[str, int]:
    """Make the table match the docs, embedding only new or changed sections."""
    chunks = load_chunks(directory)
    wanted = {chunk.hash for chunk in chunks}
    existing = {row.content_hash: row for row in db.scalars(select(KnowledgeChunk))}
    new = [chunk for chunk in chunks if chunk.hash not in existing]

    # Embed first: if Voyage fails, the current index stays as it was
    vectors = embed([chunk.text for chunk in new], 'document') if new else []
    for chunk, vector in zip(new, vectors, strict=True):
        db.add(
            KnowledgeChunk(
                source=chunk.source,
                heading=chunk.heading,
                content=chunk.content,
                content_hash=chunk.hash,
                embedding=vector,
            )
        )
    stale = [row for content_hash, row in existing.items() if content_hash not in wanted]
    for row in stale:
        db.delete(row)
    db.commit()
    return {'embedded': len(new), 'unchanged': len(chunks) - len(new), 'removed': len(stale)}


def search_knowledge(db: Session, query: str, limit: int = 4) -> list[KnowledgeChunk]:
    """The sections closest in meaning to the question, best first.

    An exact scan: there are few enough sections that an index wouldn't help.
    """
    vector = embed([query], 'query')[0]
    return list(db.scalars(select(KnowledgeChunk).order_by(KnowledgeChunk.embedding.cosine_distance(vector)).limit(limit)))
