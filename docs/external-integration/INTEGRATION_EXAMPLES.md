# Integration Examples

## Connecting to AgentLake from External Programs

---

## Python

### Minimal Client

```python
import httpx

class AgentLake:
    def __init__(self, url: str = "http://localhost:8000", api_key: str = ""):
        self.client = httpx.Client(base_url=url, headers={"X-API-Key": api_key})

    def search(self, query: str, **filters) -> list[dict]:
        resp = self.client.get("/api/v1/query/search", params={"q": query, **filters})
        resp.raise_for_status()
        return resp.json()["data"]

    def get_document(self, doc_id: str) -> dict:
        resp = self.client.get(f"/api/v1/query/documents/{doc_id}")
        resp.raise_for_status()
        return resp.json()["data"]

    def upload(self, filepath: str, tags: list[str] = []) -> dict:
        with open(filepath, "rb") as f:
            resp = self.client.post(
                "/api/v1/vault/upload",
                files={"file": f},
                data={"tags": ",".join(tags)},
            )
        resp.raise_for_status()
        return resp.json()

    def graph_explore(self, entity_name: str, depth: int = 2) -> dict:
        # First find the entity
        resp = self.client.get("/api/v1/graph/search", params={"q": entity_name})
        resp.raise_for_status()
        entities = resp.json()["data"]
        if not entities:
            return {"error": f"Entity '{entity_name}' not found"}
        entity_id = entities[0]["id"]
        resp = self.client.get(f"/api/v1/graph/entity/{entity_id}/neighbors", params={"depth": depth})
        resp.raise_for_status()
        return resp.json()

# Usage
lake = AgentLake(api_key="al-your-key")
results = lake.search("robot arm precision", category="technical")
for r in results:
    print(f"[{r['relevance_score']:.2f}] {r['title']}")
```

### Async Client

```python
import httpx

async def search_agentlake(query: str) -> list[dict]:
    async with httpx.AsyncClient(
        base_url="http://localhost:8000",
        headers={"X-API-Key": "al-your-key"},
    ) as client:
        resp = await client.get("/api/v1/query/search", params={"q": query})
        resp.raise_for_status()
        return resp.json()["data"]
```

### SSE Streaming (Processing Status)

```python
import httpx

async def watch_processing(file_id: str):
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "GET",
            f"http://localhost:8000/api/v1/stream/processing/{file_id}",
            headers={"X-API-Key": "al-your-key", "Accept": "text/event-stream"},
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    print(line[6:])
```

---

## TypeScript / Node.js

```typescript
const API_URL = "http://localhost:8000";
const API_KEY = "al-your-key";

async function search(query: string): Promise<any[]> {
  const params = new URLSearchParams({ q: query, limit: "10" });
  const resp = await fetch(`${API_URL}/api/v1/query/search?${params}`, {
    headers: { "X-API-Key": API_KEY },
  });
  const data = await resp.json();
  return data.data;
}

async function upload(file: File, tags: string[]): Promise<any> {
  const form = new FormData();
  form.append("file", file);
  form.append("tags", tags.join(","));
  const resp = await fetch(`${API_URL}/api/v1/vault/upload`, {
    method: "POST",
    headers: { "X-API-Key": API_KEY },
    body: form,
  });
  return resp.json();
}
```

---

## Shell / cURL

```bash
export AL_URL="http://localhost:8000"
export AL_KEY="al-your-key"

# Discover
curl -s -H "X-API-Key: $AL_KEY" "$AL_URL/api/v1/discover" | jq .

# Search
curl -s -H "X-API-Key: $AL_KEY" \
  "$AL_URL/api/v1/query/search?q=robot+arm&category=technical&limit=5" | jq '.data[].title'

# Get document
curl -s -H "X-API-Key: $AL_KEY" \
  "$AL_URL/api/v1/query/documents/DOCUMENT_ID" | jq '.data.body_markdown'

# Upload
curl -X POST -H "X-API-Key: $AL_KEY" \
  -F "file=@./report.pdf" -F "tags=research,robotics" \
  "$AL_URL/api/v1/vault/upload" | jq .

# Graph explore
curl -s -H "X-API-Key: $AL_KEY" \
  "$AL_URL/api/v1/graph/search?q=NVIDIA" | jq '.data[0].id' | \
  xargs -I{} curl -s -H "X-API-Key: $AL_KEY" \
  "$AL_URL/api/v1/graph/entity/{}/neighbors?depth=2" | jq .

# Watch processing (SSE)
curl -N -H "X-API-Key: $AL_KEY" -H "Accept: text/event-stream" \
  "$AL_URL/api/v1/stream/processing/FILE_ID"
```

---

## LangChain Integration

```python
from langchain_core.tools import tool

@tool
def search_agentlake(query: str, category: str = None) -> str:
    """Search the AgentLake data lake for relevant documents."""
    import httpx
    params = {"q": query, "limit": 5}
    if category:
        params["category"] = category
    resp = httpx.get(
        "http://localhost:8000/api/v1/query/search",
        params=params,
        headers={"X-API-Key": "al-your-key"},
    )
    results = resp.json()["data"]
    return "\n\n".join(
        f"**{r['title']}** (score: {r['relevance_score']:.2f})\n{r['summary']}"
        for r in results
    )
```

---

## n8n Integration

AgentLake's REST API works directly with n8n's HTTP Request node:

1. Add an **HTTP Request** node
2. Set URL: `http://agentlake-api:8000/api/v1/query/search`
3. Add header: `X-API-Key: your-key`
4. Add query parameter: `q: {{$json.search_query}}`
5. Connect to downstream processing nodes

For file uploads, use the HTTP Request node with `multipart/form-data` body type.
