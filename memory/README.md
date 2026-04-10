# Memory API

A vector-backed memory storage and search system for AI agents. Provides semantic search, temporal clustering, and automatic summarization of conversation context.

## Architecture

```
┌─────────────────┐      ┌─────────────────┐
│   Core Agent    │─────▶│   Memory API    │
│  (client code)  │      │   (FastAPI)     │
└─────────────────┘      └────────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │   SQLite DB    │
                         │  (memory.db)   │
                         └─────────────────┘
```

## Quick Start

```bash
# Install dependencies
cd memory
pip install -r requirements.txt

# Start the server
python api.py

# Server runs on http://localhost:8030
```

## Database Schema

### `memories` table
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| content | TEXT | Memory text content |
| embedding | BLOB | Vector embedding |
| created_at | TEXT | ISO timestamp |
| last_updated | TEXT | ISO timestamp |
| last_accessed | TEXT | ISO timestamp (optional) |
| token_count | INTEGER | Token count for the content |

### `properties` table (formerly `memory_properties`)
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| memory_id | INTEGER | Foreign key to memories |
| key | TEXT | Property name (lowercase) |
| value | TEXT | Property value |

### `keywords` table
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | TEXT | Keyword (unique, lowercase) |
| embedding | BLOB | Keyword embedding |

### `memory_keywords` junction table
Links memories to keywords for tagging.

### `memory_links` table
Stores directional relationships between memories (e.g., summary_of, related_to).

## API Endpoints

### Memory Operations

#### `POST /memories`
Add a new memory with optional keywords and properties.

```bash
curl -X POST http://localhost:8030/memories?db_name=default \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Python is awesome",
    "keywords": ["python", "coding"],
    "properties": {"role": "user"}
  }'
```

#### `POST /memories/context`
Add a context message (conversation turn). Optimized for chat messages.

```bash
curl -X POST http://localhost:8030/memories/context?db_name=default \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Hello, how are you?",
    "role": "user"
  }'
```

**Response:**
```json
{
  "id": 42,
  "content": "Hello, how are you?",
  "role": "user",
  "token_count": 12,
  "created_at": "2025-01-15T10:00:00+00:00"
}
```

Auto-adds:
- Keyword: `"context"`
- Property: `role`, `node_type="context"`, `token_count`

#### `GET /memories/{id}`
Get a memory by ID.

#### `DELETE /memories/{id}`
Delete a memory.

#### `PUT /memories/{id}`
Update a memory's properties and/or keywords.

#### `POST /memories/search`
Search memories using the query DSL.

```bash
curl -X POST http://localhost:8030/memories/search?db_name=default \
  -H "Content-Type: application/json" \
  -d '{
    "query": "k:python AND p:role=user",
    "limit": 10
  }'
```

### Link Operations

#### `POST /memories/link`
Add a link between two memories.

```bash
curl -X POST http://localhost:8030/memories/link?db_name=default \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": 1,
    "target_id": 2,
    "link_type": "related_to"
  }'
```

### Database Operations

#### `GET /db/list`
List all databases.

#### `POST /db/create`
Create a new database.

#### `GET /db/exists/{name}`
Check if a database exists.

### Stats & Info

#### `GET /stats`
Get memory count.

#### `GET /embed/model`
Get embedding model info.

#### `GET /embed/cache`
Get embedding cache stats.

#### `DELETE /embed/cache`
Clear embedding cache.

#### `GET /docs/search-syntax`
Get search query syntax documentation.

## Search Query Syntax

The search system supports a DSL with the following operators:

### Keywords
```
k:python          # memories with "python" keyword
python            # same as above
```

### Properties
```
p:role=user           # exact match
p:rating>=4          # numeric comparison
p:status!=archived   # not equal
```

### Date Filtering
```
d:last 7 days       # memories from last 7 days
d:2025-01-01        # memories from specific date
```

### Semantic Search
```
q:async programming    # semantic similarity
q:async@0.7           # with threshold
```

### Links
```
l:summary_of           # memories linked by summary_of
l:source:related_to    # memories that link TO others
l:target:related_to   # memories that ARE LINKED TO
```

### Boolean Operators
```
k:python AND k:asyncio    # both must match
k:python OR k:javascript  # either can match
NOT k:archived            # negation
```

### Grouping
```
(k:python OR k:javascript) AND d:last 7 days
```

### Conditionals
```
IF k:python THEN k:asyncio ELSE k:docker
```

## Configuration

### Config Files

The API loads configuration from YAML files (priority order):
1. `config_local.yaml` (local overrides)
2. `config.yaml` (project defaults)

### Key Config Options

```yaml
memory_api:
  url: "http://127.0.0.1:8030"
  db_name: "riven"

llm:
  url: "http://127.0.0.1:8010"
  api_key: "sk-dummy"
  model: "llama3"
  context_window: 128000

context:
  max_tokens: 32000
  max_messages: 50
  cluster_gap_minutes: 30
  cluster_exclude_minutes: 30

embedding:
  model_size: "27b"
  force_cpu: true
  cache_db: "memory/embeddings_cache.db"
```

## Summarization (In Progress)

The API is being extended to handle automatic summarization:

1. **`POST /memories/summarize`** - Trigger summarization for context memories
2. **Temporal clustering** - Group memories by time proximity
3. **Token budget** - Summarize when context exceeds threshold

See `summary.py` for the in-progress implementation.

## File Structure

```
memory/
├── api.py              # FastAPI endpoints
├── database.py         # SQLite database operations
├── search.py           # Query DSL parser and search
├── embedding.py        # Text embedding model
├── summary.py          # Summarization manager (in progress)
├── config.py           # Configuration loader
├── config.yaml         # Default configuration
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

## Client Library

The `memory_manager.py` in the project root provides a Python client:

```python
from memory_manager import MemoryManager

manager = MemoryManager(db_name="default")

# Add a memory
memory_id = manager.add("Hello world", keywords=["greeting"])

# Search
results = manager.search("k:greeting")

# Get temporal clusters
clusters = manager.get_temporal_clusters(gap_minutes=30)
```

## Token Counting

Token counting uses `tiktoken` (OpenAI's tokenizer) with a fallback to rough estimation (~4 chars per token). Token count is:
- Automatically computed when adding memories
- Stored in the `token_count` column
- Used to trigger summarization when context exceeds threshold