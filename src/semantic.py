"""Semantic search over the funds' documents: find funds by what their objective says, not by
the words in their name. Only available when the brochures have been processed.

A small multilingual embedding model (CPU) turns each fund's objective into a vector once; a
query in Spanish then finds objectives written in Spanish or English.
"""

import csv
import hashlib
from functools import lru_cache
from pathlib import Path

from .paths import BROCHURES, MODELS

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INDEX = BROCHURES.with_name("folletos_vectores.npz")
MIN_SIMILARITY = 0.30
TOP = 400


def installed() -> bool:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def available() -> bool:
    return installed() and INDEX.is_file()


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    return TextEmbedding(MODEL, cache_dir=str(MODELS / "embeddings"))


def _embed(texts: list[str]):
    import numpy as np

    vectors = np.array(list(_model().embed(texts, batch_size=64)), dtype="float32")
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _text(row: dict) -> str:
    return ". ".join(part for part in (row["nombre"], row["categoria"], row["objetivo"]) if part)


def build(brochures: Path = BROCHURES, index: Path = INDEX) -> dict:
    """Embed the objective of every fund that has one. Funds whose text has not changed are reused."""
    import numpy as np

    with Path(brochures).open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["objetivo"]]
    texts = [_text(row) for row in rows]
    digests = [hashlib.sha1(text.encode("utf-8")).hexdigest() for text in texts]
    known = {}
    if index.is_file():
        with np.load(index, allow_pickle=False) as saved:
            known = {digest: vector for digest, vector in zip(saved["digests"], saved["vectors"])}
    fresh = [position for position, digest in enumerate(digests) if digest not in known]
    if fresh:
        for digest, vector in zip((digests[position] for position in fresh), _embed([texts[position] for position in fresh])):
            known[digest] = vector
    vectors = np.array([known[digest] for digest in digests], dtype="float32")
    temporary = index.with_name(index.stem + "_tmp.npz")
    np.savez(temporary, isins=np.array([row["isin"] for row in rows]), digests=np.array(digests), vectors=vectors)
    temporary.replace(index)
    _index.cache_clear()
    return {"fondos con vector": len(rows), "calculados ahora": len(fresh)}


@lru_cache(maxsize=1)
def _index(modified_ns: int):
    import numpy as np

    with np.load(INDEX, allow_pickle=False) as saved:
        return saved["isins"].tolist(), saved["vectors"]


def search(query: str, top: int = TOP) -> dict[str, float]:
    """ISIN -> similarity for the funds whose objective is closest to the query."""
    if not query.strip() or not available():
        return {}
    isins, vectors = _index(INDEX.stat().st_mtime_ns)
    scores = vectors @ _embed([query])[0]
    order = scores.argsort()[::-1][:top]
    return {isins[position]: float(scores[position]) for position in order if scores[position] >= MIN_SIMILARITY}
