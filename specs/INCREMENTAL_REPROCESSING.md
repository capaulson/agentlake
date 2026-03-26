# Feature Spec: Incremental Reprocessing

## Overview

When a raw file is re-uploaded or manually triggered for reprocessing, the system must NOT reprocess the entire file from scratch. Instead, it compares the new extraction against the existing chunks and only re-summarizes, re-cites, and re-embeds the chunks that actually changed.

This is critical because:
- LLM calls are the most expensive operation (both latency and cost)
- A one-word edit in a 100-page PDF should not trigger 100 LLM summarization calls
- Embeddings are expensive to regenerate
- The diff log must accurately reflect what changed and why

---

## Architecture

```
Re-upload / Reprocess trigger
    │
    ▼
[Extract] ─── full re-extraction (always, this is cheap)
    │
    ▼
[Chunk] ─── full re-chunking (always, this is cheap)
    │
    ▼
[Diff Chunks] ─── compare new chunks against existing chunks
    │
    ├── Unchanged chunks → skip summarization, reuse existing summaries + embeddings
    ├── Modified chunks  → re-summarize + re-embed (via Layer 4B)
    ├── New chunks       → summarize + embed (via Layer 4B)
    └── Deleted chunks   → mark as removed, remove from search index
    │
    ▼
[Re-cite] ─── regenerate citations for modified/new chunks only
    │
    ▼
[Re-classify] ─── re-run ontology classification only if significant content changed
    │                (threshold: >20% of chunks modified)
    ▼
[Assemble] ─── rebuild document markdown from mix of old + new summaries
    │
    ▼
[Store] ─── new version with accurate diff log
```

---

## Chunk Comparison Algorithm

Each chunk is identified by a content hash (SHA-256 of its text content). Comparison is done at the chunk level:

```python
@dataclass
class ChunkDelta:
    unchanged: list[tuple[int, str]]   # (old_index, chunk_hash) — reuse existing
    modified: list[tuple[int, int]]     # (old_index, new_index) — content changed
    added: list[int]                    # new_index — brand new content
    removed: list[int]                  # old_index — no longer present

def compute_chunk_delta(
    old_chunks: list[DocumentChunk],
    new_chunks: list[TextBlock],
) -> ChunkDelta:
    """Compare old processed chunks against newly extracted text blocks.

    Strategy:
    1. Hash each old chunk and new chunk
    2. Exact hash matches → unchanged (even if position shifted)
    3. Unmatched old chunks: check fuzzy similarity against unmatched new chunks
       - >85% similarity → modified (re-summarize)
       - <85% similarity → old is "removed", new is "added"
    4. Remaining unmatched new chunks → added
    5. Remaining unmatched old chunks → removed
    """
```

### Similarity Metric

For fuzzy matching modified chunks, use token-level Jaccard similarity:

```python
def chunk_similarity(old_text: str, new_text: str) -> float:
    old_tokens = set(old_text.lower().split())
    new_tokens = set(new_text.lower().split())
    if not old_tokens or not new_tokens:
        return 0.0
    intersection = old_tokens & new_tokens
    union = old_tokens | new_tokens
    return len(intersection) / len(union)
```

Threshold: `INCREMENTAL_SIMILARITY_THRESHOLD = 0.85` (configurable via env)

---

## Data Model Changes

### DocumentChunk — Add content hash

```sql
ALTER TABLE document_chunks ADD COLUMN content_hash VARCHAR(64) NOT NULL DEFAULT '';
CREATE INDEX idx_chunks_hash ON document_chunks(content_hash);
```

The content hash is computed at chunk creation time: `sha256(content.encode()).hexdigest()`

### ProcessedDocument — Track reprocessing metadata

Add to frontmatter JSONB:

```yaml
reprocessing:
  last_reprocessed_at: "2026-03-24T14:00:00Z"
  reprocessing_type: "incremental"  # or "full"
  chunks_reused: 18
  chunks_modified: 3
  chunks_added: 1
  chunks_removed: 0
  llm_calls_saved: 18  # calls that would have been made in full reprocessing
  estimated_cost_saved_usd: 0.54
```

### DiffLog — Enhanced for incremental reprocessing

The diff log entry for an incremental reprocess includes:

```
diff_type: "reprocessing"
justification: "Incremental reprocessing: 3 chunks modified, 1 added, 0 removed (18 reused)"
before_text: <previous document body>
after_text: <new document body>
```

Plus a JSONB `metadata` field on DiffLog:

```json
{
  "reprocessing_type": "incremental",
  "chunk_delta": {
    "unchanged": 18,
    "modified": 3,
    "added": 1,
    "removed": 0
  },
  "modified_chunks": [4, 11, 15],
  "added_chunks": [22],
  "trigger": "file_reupload"
}
```

---

## Trigger Conditions

Incremental reprocessing is triggered when:

1. **File re-upload:** Same `sha256_hash` NOT found (content changed). If hash matches, no reprocessing needed.
2. **Manual reprocess:** `POST /api/v1/vault/reprocess/{file_id}?mode=incremental` (default) or `?mode=full`
3. **Processing version bump:** When `PROCESSING_VERSION` env var changes (new prompts, new ontology), all documents are queued for incremental reprocessing.

### Force Full Reprocessing

Sometimes a full reprocess is needed (e.g., LLM model upgrade, prompt changes). This is triggered by:

- `POST /api/v1/vault/reprocess/{file_id}?mode=full`
- Setting `FORCE_FULL_REPROCESS=true` on the distiller container (processes everything in queue as full)

---

## Configuration

```bash
# Incremental reprocessing
INCREMENTAL_SIMILARITY_THRESHOLD=0.85    # Jaccard threshold for "modified" vs "new"
INCREMENTAL_RECLASSIFY_THRESHOLD=0.20    # Re-run ontology if >20% chunks changed
PROCESSING_VERSION=1.0.0                  # Bump to trigger mass reprocessing
FORCE_FULL_REPROCESS=false                # Override to disable incremental
```

---

## Performance Impact

| Scenario | Full Reprocess | Incremental | Savings |
|----------|---------------|-------------|---------|
| 1-word edit in 100-page PDF | 100 LLM calls | 1 LLM call | 99% |
| New section added to report | 50 LLM calls | 5 LLM calls | 90% |
| Complete document rewrite | 50 LLM calls | 50 LLM calls | 0% (correct) |
| Processing version bump | N × full | N × incremental | ~70-90% |

---

## Testing Requirements

- **Unit:** Test `compute_chunk_delta` with known inputs (unchanged, modified, added, removed)
- **Unit:** Test Jaccard similarity at boundary (0.84 → added, 0.86 → modified)
- **Integration:** Upload file → process → re-upload with small edit → verify only changed chunks re-summarized
- **Integration:** Verify LLM call count matches expected (mock gateway, count calls)
- **Integration:** Verify diff log accurately records chunk delta metadata
- **Integration:** Full reprocess mode ignores chunk comparison and re-summarizes everything
