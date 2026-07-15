"""
search.py — BM25 search over the SQLite library index.

Why BM25 instead of vector embeddings?
  • Zero external API calls — no 503s, no DNS blocks, no rate limits.
  • ~5 MB RAM for a typical Islamic library (vs 450 MB for local models).
  • Works perfectly for Islamic content: terminology is consistent and specific
    (aqeedah, tawheed, arsh, salah, etc.), so keyword matching retrieves the
    right threads reliably.
  • BM25 is what search engines like Elasticsearch use at their core.

The BM25 index is built in memory from SQLite at startup and after reindex.
Queries are instant — no network, no latency.
"""

import re
from rank_bm25 import BM25Okapi
from database import init_db, load_all_chunks, count_chunks
from config import TOP_K

# Arabic diacritics (tashkeel) — remove for better matching
_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670]")

# In-memory BM25 index — rebuilt from SQLite on startup and after /reindex
_bm25:   BM25Okapi | None = None
_chunks: list[dict]       = []


def _tokenize(text: str) -> list[str]:
    """
    Tokenizer for mixed Arabic/English content.
    - Strips Arabic diacritics so ُعلى and على both match على
    - Lowercases English
    - Keeps Arabic letters (U+0600–U+06FF) and Latin alphanumerics
    - Drops tokens shorter than 2 chars
    """
    text = _DIACRITICS.sub("", text)
    text = text.lower()
    text = re.sub(r"[^\w\u0600-\u06FF\s]", " ", text)
    return [t for t in text.split() if len(t) > 1]


def build_index() -> None:
    global _bm25, _chunks

    init_db()
    _chunks = load_all_chunks()

    if not _chunks:
        _bm25 = None
        print("[Search] Index is empty — run /reindex first.")
        return

    # Include thread_name so queries matching the title find its chunks
    # even when the body is in a different script (e.g. Devanagari vs Latin)
    tokenized = [_tokenize(c["thread_name"] + " " + c["text"]) for c in _chunks]
    _bm25 = BM25Okapi(tokenized)
    print(f"[Search] ✅ BM25 index ready — {len(_chunks)} chunks loaded.")


def invalidate_index() -> None:
    """Clear the in-memory index. Called before reindex so stale data isn't used."""
    global _bm25, _chunks
    _bm25   = None
    _chunks = []


def search(query: str, top_k: int = TOP_K) -> list[dict]:
    """
    Search the library and return the top-K most relevant chunks.
    Builds the index on first call if not already built.

    Each result: { text, thread_name, thread_url, category, channel, score }
    """
    global _bm25, _chunks

    if _bm25 is None:
        build_index()

    if _bm25 is None or not _chunks:
        return []

    scores     = _bm25.get_scores(_tokenize(query))
    top_idxs   = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

    return [
        {**_chunks[i], "score": round(float(scores[i]), 3)}
        for i in top_idxs
        if scores[i] > 0
    ]


def search_prioritized(query: str, top_k: int = TOP_K) -> tuple[list[dict], bool]:
    """
    Same as search(), but boosts chunks whose thread title shares words with
    the query — people often phrase a question close to the exact title of
    the thread that answers it, and plain BM25 alone doesn't weight that.

    Returns (hits, name_match):
      hits       — top-K chunks, same shape as search()
      name_match — True if at least one result's title overlapped the query

    Reuses the existing in-memory BM25 index — does NOT rebuild it per call.
    Only adds a single O(chunks) pass over the already-computed score array,
    so this stays cheap even with thousands of chunks; no extra memory beyond
    a small list of floats.
    """
    global _bm25, _chunks

    if _bm25 is None:
        build_index()

    if _bm25 is None or not _chunks:
        return [], False

    query_tokens    = _tokenize(query)
    query_token_set = set(query_tokens)

    scores = _bm25.get_scores(query_tokens)

    boosted_scores = list(scores)
    name_match     = False

    for i, chunk in enumerate(_chunks):
        if scores[i] <= 0:
            continue   # don't bother boosting chunks BM25 already scored as irrelevant

        title_tokens = set(_tokenize(chunk["thread_name"]))
        overlap = query_token_set & title_tokens

        if overlap:
            # Boost proportional to how much of the query matched the title.
            # A chunk whose thread title contains every query word gets up to
            # a 2x boost; partial overlaps get a smaller bump.
            boost = 1.0 + (len(overlap) / max(len(query_token_set), 1))
            boosted_scores[i] = scores[i] * boost
            name_match = True

    top_idxs = sorted(
        range(len(boosted_scores)),
        key=lambda i: boosted_scores[i],
        reverse=True,
    )[:top_k]

    hits = [
        {**_chunks[i], "score": round(float(boosted_scores[i]), 3)}
        for i in top_idxs
        if scores[i] > 0   # still gate on the original BM25 relevance, not just the boost
    ]

    return hits, name_match


def is_index_empty() -> bool:
    return count_chunks() == 0