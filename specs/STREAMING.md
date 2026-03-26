# Feature Spec: SSE Streaming

## Overview

AgentLake uses Server-Sent Events (SSE) for two real-time data flows:

1. **Processing status updates** — when a file is uploaded, the UI receives live stage-by-stage progress (extracting → chunking → summarizing → citing → storing)
2. **Streaming search results** — large result sets stream incrementally so the user sees the first results immediately while the system continues scoring and ranking

WebSocket is used for a third flow:

3. **Live dashboard counters** — the dashboard page receives push updates for file counts, token usage, and queue depth without polling

---

## 1. Processing Status Stream

### Endpoint

```
GET /api/v1/stream/processing/{file_id}
Accept: text/event-stream
```

### Event Format

```
event: stage_update
data: {"file_id": "uuid", "stage": "extracting", "progress": 0.15, "message": "Extracting text from PDF (page 3 of 12)"}

event: stage_update
data: {"file_id": "uuid", "stage": "chunking", "progress": 0.35, "message": "Split into 24 chunks"}

event: stage_update
data: {"file_id": "uuid", "stage": "summarizing", "progress": 0.55, "chunk": 8, "total_chunks": 24, "message": "Summarizing chunk 8/24"}

event: stage_update
data: {"file_id": "uuid", "stage": "citing", "progress": 0.80, "message": "Generating citations"}

event: stage_update
data: {"file_id": "uuid", "stage": "storing", "progress": 0.95, "message": "Storing processed document and embeddings"}

event: complete
data: {"file_id": "uuid", "document_id": "uuid", "status": "processed", "duration_ms": 42000}

event: error
data: {"file_id": "uuid", "stage": "summarizing", "error": "LLM timeout on chunk 15", "will_retry": true, "retry_count": 1}
```

### Implementation Notes

- The API server publishes processing events to a Redis Pub/Sub channel keyed by `processing:{file_id}`
- Celery workers publish stage updates to this channel as they progress
- The SSE endpoint subscribes to the channel and forwards events to the client
- Connection timeout: 5 minutes (client should reconnect on timeout)
- `Last-Event-ID` header supported for reconnection resumption

### Stages Enum

```python
class ProcessingStage(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    SUMMARIZING = "summarizing"
    CITING = "citing"
    ONTOLOGY_MAPPING = "ontology_mapping"
    GENERATING_EMBEDDINGS = "generating_embeddings"
    STORING = "storing"
    COMPLETE = "complete"
    ERROR = "error"
```

---

## 2. Streaming Search Results

### Endpoint

```
GET /api/v1/stream/search?q=...&limit=50
Accept: text/event-stream
```

### Event Format

```
event: result
data: {"index": 0, "id": "uuid", "title": "...", "summary": "...", "relevance_score": 0.94, "snippet": "..."}

event: result
data: {"index": 1, "id": "uuid", "title": "...", "summary": "...", "relevance_score": 0.91, "snippet": "..."}

... (results stream as they are scored)

event: meta
data: {"total_results": 142, "query_time_ms": 87, "search_type": "hybrid"}

event: done
data: {}
```

### Implementation Notes

- Keyword results return first (faster), then semantic results merge in via RRF
- The UI renders results as they arrive using a streaming parser
- Non-streaming `/api/v1/query/search` endpoint still exists for agents that prefer batch responses
- The streaming endpoint returns the same data shape as the batch endpoint, just incrementally

---

## 3. WebSocket Dashboard Feed

### Endpoint

```
WS /ws/dashboard
```

### Message Format

```json
{
  "type": "stats_update",
  "data": {
    "total_files": 12455,
    "total_documents": 11894,
    "tokens_today": 1823456,
    "cost_today_usd": 12.47,
    "queue_depth": {"high": 0, "default": 3, "low": 12},
    "processing_active": 2
  }
}
```

### Implementation Notes

- Server pushes updates every 5 seconds (configurable)
- Stats are read from Redis cached counters (not direct DB queries)
- Counters are updated atomically by the API and distiller services
- WebSocket auth via token query parameter: `ws://host/ws/dashboard?token=...`

---

## 4. Frontend Integration

### React Hooks

```typescript
// useProcessingStream(fileId) — returns live processing status
// useSearchStream(query, filters) — returns incrementally-populated results array
// useDashboardFeed() — returns live dashboard statistics
```

### UI Behavior

- **Upload page:** After upload, a progress card shows real-time processing stages with a progress bar
- **Search page:** Results appear one by one with a fade-in animation as they stream in
- **Dashboard:** Stats cards update in real-time without page refresh, with subtle pulse animation on change

---

## 5. Redis Pub/Sub Channels

| Channel Pattern | Publisher | Subscriber | Purpose |
|----------------|-----------|------------|---------|
| `processing:{file_id}` | Celery workers | API SSE endpoint | Per-file processing updates |
| `stats:global` | API + Distiller | API WebSocket | Dashboard counters |
| `search:stream:{request_id}` | Search service | API SSE endpoint | Streaming search results |
