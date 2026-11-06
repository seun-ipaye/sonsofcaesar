import pytest
from sqlalchemy import select

from app import knowledge
from app.models import EMBEDDING_DIMENSIONS, KnowledgeChunk


def unit_vector(position: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[position] = 1.0
    return vector


@pytest.fixture
def fake_embed(monkeypatch):
    """Texts mentioning "refund" and texts mentioning "door" point different ways."""
    calls = []

    def embed(texts, input_type):
        calls.append(texts)
        return [unit_vector(0 if 'refund' in text.lower() else 1) for text in texts]

    monkeypatch.setattr(knowledge, 'embed', embed)
    return calls


@pytest.fixture
def docs(tmp_path):
    (tmp_path / 'README.md').write_text('# Rules\n\n## Not an answer\nSkip me.\n')
    (tmp_path / 'policy.md').write_text('# Policy\n\n## Refunds\nAll sales are final.\n\n## Door\nShow your QR.\n')
    return tmp_path


def test_each_section_becomes_a_chunk_and_readme_is_skipped(docs):
    chunks = knowledge.load_chunks(docs)
    assert [(c.source, c.heading, c.content) for c in chunks] == [
        ('policy.md', 'Refunds', 'All sales are final.'),
        ('policy.md', 'Door', 'Show your QR.'),
    ]


def test_an_empty_section_is_an_error(tmp_path):
    (tmp_path / 'bad.md').write_text('# Bad\n\n## Nothing here\n')
    with pytest.raises(ValueError, match='Nothing here'):
        knowledge.load_chunks(tmp_path)


def test_real_docs_all_load():
    chunks = knowledge.load_chunks()
    assert len(chunks) > 20
    assert len({c.hash for c in chunks}) == len(chunks)


def test_reindexing_only_embeds_what_changed(db, docs, fake_embed):
    assert knowledge.index_knowledge(db, docs) == {'embedded': 2, 'unchanged': 0, 'removed': 0}
    assert knowledge.index_knowledge(db, docs) == {'embedded': 0, 'unchanged': 2, 'removed': 0}
    assert len(fake_embed) == 1

    (docs / 'policy.md').write_text('# Policy\n\n## Refunds\nAll sales are final.\n\n## Door\nBring ID.\n')
    assert knowledge.index_knowledge(db, docs) == {'embedded': 1, 'unchanged': 1, 'removed': 1}
    assert {c.content for c in db.scalars(select(KnowledgeChunk))} == {'All sales are final.', 'Bring ID.'}


def test_failed_embedding_leaves_the_index_alone(db, docs, fake_embed, monkeypatch):
    knowledge.index_knowledge(db, docs)
    (docs / 'policy.md').write_text('# Policy\n\n## Door\nBring ID.\n')

    def down(texts, input_type):
        raise RuntimeError('Voyage is down')

    monkeypatch.setattr(knowledge, 'embed', down)
    with pytest.raises(RuntimeError):
        knowledge.index_knowledge(db, docs)
    db.rollback()
    assert {c.heading for c in db.scalars(select(KnowledgeChunk))} == {'Refunds', 'Door'}
    assert 'Show your QR.' in {c.content for c in db.scalars(select(KnowledgeChunk))}


def test_search_returns_closest_section_first(db, docs, fake_embed):
    knowledge.index_knowledge(db, docs)
    assert knowledge.search_knowledge(db, 'can I get a refund?')[0].heading == 'Refunds'
    assert knowledge.search_knowledge(db, 'what happens at the door?')[0].heading == 'Door'
    assert len(knowledge.search_knowledge(db, 'refund', limit=1)) == 1


def test_embed_without_a_key_fails_clearly(monkeypatch):
    monkeypatch.setattr(knowledge.settings, 'voyage_api_key', '')
    with pytest.raises(RuntimeError, match='VOYAGE_API_KEY'):
        knowledge.embed(['hi'], 'query')
