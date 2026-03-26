# Connecting to AgentLake via MCP

## Model Context Protocol Integration Guide

AgentLake exposes an MCP server that allows any MCP-compatible client (Claude Desktop, Claude Code, custom agents) to interact with the data lake directly.

---

## 1. Claude Desktop

### Configuration

Add AgentLake to your Claude Desktop MCP configuration:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

#### SSE Transport (Remote / Always-Running Server)

```json
{
  "mcpServers": {
    "agentlake": {
      "type": "sse",
      "url": "http://localhost:8002/mcp/sse",
      "headers": {
        "X-API-Key": "your-api-key-here"
      }
    }
  }
}
```

#### stdio Transport (Local / Spawned Process)

```json
{
  "mcpServers": {
    "agentlake": {
      "command": "python",
      "args": ["-m", "agentlake.mcp.server", "--transport", "stdio"],
      "env": {
        "AGENTLAKE_API_URL": "http://localhost:8000",
        "AGENTLAKE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### Usage in Claude Desktop

Once connected, you can ask Claude:

- "Search AgentLake for everything about the Siemens partnership"
- "What documents do we have about robot arm precision testing?"
- "Show me the entity graph around NVIDIA"
- "Upload this meeting notes file to AgentLake with tags partner:gm, meeting-notes"
- "Get the full document for [document ID] and verify citation #3"

Claude will automatically use the AgentLake MCP tools.

---

## 2. Claude Code

### Configuration

Add to `.claude/settings.json` in your project:

```json
{
  "mcpServers": {
    "agentlake": {
      "type": "sse",
      "url": "http://localhost:8002/mcp/sse"
    }
  }
}
```

Or use the skill-based approach — copy `specs/CLAUDE_SKILL.md` to your project's `/mnt/skills/user/agentlake/SKILL.md` and Claude Code will use the REST API directly via curl.

### Example Prompts for Claude Code

```
"Search AgentLake for technical specs related to the GR00T training pipeline 
and summarize the key findings in a markdown file."

"Upload all the PDF files in ./meeting-notes/ to AgentLake with tag meeting-notes."

"Use AgentLake to find everything connected to Physical Intelligence in the 
entity graph, then write a competitive analysis."
```

---

## 3. Custom MCP Clients (Python)

### Using the MCP Python SDK

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client("http://localhost:8002/mcp/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")

            # Search the data lake
            result = await session.call_tool(
                "agentlake_search",
                arguments={"query": "robot arm precision", "limit": 5}
            )
            print(result.content)

            # Explore entity graph
            result = await session.call_tool(
                "agentlake_graph_explore",
                arguments={"entity_name": "NVIDIA", "depth": 2}
            )
            print(result.content)

            # Upload a file
            result = await session.call_tool(
                "agentlake_upload",
                arguments={
                    "file_path": "/path/to/document.pdf",
                    "tags": "research,robotics"
                }
            )
            print(result.content)

asyncio.run(main())
```

### Using the REST API Directly (Non-MCP)

For clients that don't support MCP, use the REST API. See `API_REFERENCE.md` for the full endpoint documentation.

```python
import httpx

client = httpx.Client(
    base_url="http://localhost:8000",
    headers={"X-API-Key": "your-key"}
)

# Search
results = client.get("/api/v1/query/search", params={"q": "robot arm"}).json()

# Get document
doc = client.get(f"/api/v1/query/documents/{results['data'][0]['id']}").json()

# Explore graph
graph = client.get("/api/v1/graph/search", params={"q": "NVIDIA"}).json()
```

---

## 4. Available MCP Tools

| Tool | Description |
|------|------------|
| `agentlake_discover` | Get data lake overview (call first) |
| `agentlake_search` | Search with keyword/semantic/hybrid |
| `agentlake_get_document` | Retrieve full processed document |
| `agentlake_get_citations` | Get citation provenance for a document |
| `agentlake_upload` | Upload a file for processing |
| `agentlake_list_tags` | List all tags with counts |
| `agentlake_graph_explore` | Traverse entity relationship graph |
| `agentlake_edit_document` | Edit a processed document |

---

## 5. Available MCP Prompts

| Prompt | Description |
|--------|------------|
| `research_topic` | Research a topic across all documents with citations |
| `entity_briefing` | Generate a briefing about a person, company, or product |

---

## 6. Troubleshooting

**"Connection refused" to MCP server:**
- Ensure the MCP server container is running: `docker compose ps mcp-server`
- Check the port: `curl http://localhost:8002/mcp/sse`

**"Unauthorized" errors:**
- Verify your API key is valid and has the `agent` role
- For SSE transport, check the `X-API-Key` header in your MCP config

**Tools not appearing in Claude:**
- Restart Claude Desktop after changing `claude_desktop_config.json`
- For Claude Code, restart the session after changing `.claude/settings.json`

**Slow responses:**
- The first search may be slow if the database hasn't been warmed up
- Large result sets stream incrementally — watch for partial results
