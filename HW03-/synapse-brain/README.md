# SynapseBrain — Personal Context Compiler & Local Memory Graph

Single-user knowledge-graph app: nodes/edges in local SQLite, offline chat via
Ollama, a compiler that turns top-weighted nodes into an external prompt
(for Gemini/Claude), and an ingestion pipeline that parses
` ```brain-update ` JSON blocks back into the graph.

## Directory structure

```text
synapse-brain/
├── main.py       # FastAPI server, endpoints, static hosting
├── database.py   # SQLite helpers (nodes/edges CRUD, graph queries)
├── compiler.py   # compile_prompt + brain-update regex ingestion engine
├── static/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── tests/
│   └── test_brain.py
├── requirements.txt
└── README.md
```

## Setup & run

```powershell
cd synapse-brain
pip install -r requirements.txt
python main.py          # serves http://127.0.0.1:8800 (see "Dynamic port" below)
```

### Dynamic port

The server picks the first free port starting at **8800** and scanning up to
**8820**, so it never fights Ollama (`11434`), Docker or WSL port relays for
`8000`/`8080`. The port it actually bound is printed on startup and written to
a `.port` file in this directory, so scripts and CI do not have to guess:

```powershell
python main.py
# [synapse] SynapseBrain 啟動於 http://127.0.0.1:8800  (port 記錄於 .port)

$port = Get-Content .port
Invoke-RestMethod "http://127.0.0.1:$port/api/graph"
```

Override the starting point with `$env:SYNAPSE_PORT` (e.g. `$env:SYNAPSE_PORT=9000`).
A non-numeric value falls back to the `8800` default. Both `.port` and
`synapse.db` are git-ignored.

Optional: local LLM via Ollama (falls back to a mock reply if unreachable):

```powershell
ollama serve
ollama pull llama3:8b
# $env:OLLAMA_MODEL="qwen2.5:7b"  # to switch models
```

DB file: `./synapse.db` (override with `$env:SYNAPSE_DB="path\to\other.db"`).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_PORT` | `8800` | First port to try; auto-increments up to `+20` if busy |
| `SYNAPSE_DB` | `./synapse.db` | SQLite file path |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `OLLAMA_MODEL` | `llama3:8b` | Model tag |
| `OLLAMA_AUTOSTART` | `1` | Start `ollama serve` on boot if unreachable |
| `OLLAMA_AUTOPULL` | `0` | Pull the model in the background if missing |
| `OLLAMA_UNLOAD_AFTER_CHAT` | `0` | Unload the model from RAM after each chat |
| `OLLAMA_TEMPERATURE` | `0.3` | Sampling temperature |
| `CHAT_MEMORY_LIMIT` | `8` | Top-weighted nodes injected into each system prompt |
| `EXTRACT_TIMEOUT` | `180` | Seconds allowed for the post-chat memory extraction pass |
| `EXTRACT_MAX_TOKENS` | `400` | Cap on tokens generated during extraction (it only needs a small JSON) |
| `EXTRACT_KEEPALIVE` | `10` | Seconds between `busy` frames while extraction runs |

## API docs

Interactive docs at `http://127.0.0.1:<port>/docs` (FastAPI auto-OpenAPI),
where `<port>` is the number in `.port`.

| Method | Endpoint | Body | Description |
|---|---|---|---|
| GET | `/api/health` | — | status + Ollama reachability / model presence |
| GET | `/api/graph` | — | `{ nodes, edges }` for Vis-Network |
| POST | `/api/nodes` | `{id, label?, category?, weight?, summary?}` | create/update node |
| POST | `/api/nodes/:id/boost` | `?amount=0.5` | increment (clamped 0.1–10), then decay others |
| DELETE | `/api/nodes/:id` | — | remove node + adjacent edges |
| POST | `/api/edges` | `{source, target, relation?, strength?}` | connect nodes |
| POST | `/api/seed-demo` | — | write the sample graph (idempotent merge) |
| POST | `/api/local-chat` | `{message, remember?}` | proxy to Ollama `/api/generate` (mock fallback) |
| POST | `/api/local-chat-stream` | `{message, remember?}` | SSE token stream; last frame carries `memory` |
| POST | `/api/compile-prompt` | `{focus_topic?, limit?}` | compiled external system prompt |
| POST | `/api/ingest` | `{text}` | parse ` ```brain-update ` blocks, apply to SQLite |

### Automatic memory write-back

Both chat endpoints take `remember` (default `true`). After the reply, a second
LLM pass extracts anything worth keeping and writes it back into the graph as
a `brain-update` payload — so chatting *is* how the brain grows. The streaming
endpoint reports the outcome in its final `done` frame under `memory`
(`blocks_found`, `new_nodes`, `boosted_nodes`, `decayed_nodes`, `errors`).
Set `remember: false` to skip extraction entirely.

### Streaming frames

| Frame | Meaning |
|---|---|
| `{"token": "..."}` | a chunk of the reply |
| `{"busy": "正在整理記憶…"}` | reply finished; extraction still running |
| `{"done": true, "memory": {...}}` | final frame; `memory` carries the write-back result |

On a local 8B model a single message typically takes 1–3 minutes, and the
extraction pass alone can run for another minute or so. That gap is why the
`busy` frames exist: without them the connection would sit completely silent
for a long stretch and get cut by anything in the middle. **Extraction is
strictly best-effort — it runs in its own task with its own timeout, and it can
never tear down the stream or discard a reply you already received.**

If extraction times out, `memory.error` says so and the reply is unaffected.
Ollama failures are classified distinctly so the advice is actionable:

| `memory.error` contains | Meaning |
|---|---|
| `（unreachable）` | Ollama isn't running or isn't reachable |
| `（timeout）` | Ollama is up but too slow for `EXTRACT_TIMEOUT` |
| `（model_missing）` | Ollama is up, but `OLLAMA_MODEL` isn't pulled |

### Ingestion block schema

Extraction is called with Ollama's `format: "json"`, which makes the model
return a single valid JSON object with no Markdown and no prose. The parser
still does not take any of that on trust — it scans every fenced block *and*
the whole response, and accepts a candidate only when its body parses into an
object carrying `new_nodes` / `boost_nodes` / `new_edges` with list values.

So all of these work, which is what an 8B model actually produces:

````text
format="json"  -> {"new_nodes": [...], "boost_nodes": [...], "new_edges": [...]}

```json
{"new_nodes": [...], "boost_nodes": [...], "new_edges": [...]}
```

Here is the brain update code block:
```
{"new_nodes": [...], "boost_nodes": [...], "new_edges": [...]}
```
````

Unrelated blocks (` ```python `, ` ```bash `, …) and same payload seen through
two of those routes are de-duplicated rather than ingested twice.

Payload shape:

```json
{
  "new_nodes": [{"id": "docker", "label": "Docker", "summary": "...", "weight": 1.0}],
  "boost_nodes": ["python"],
  "new_edges": [{"source": "docker", "target": "python", "relation": "relates_to"}]
}
```

When nothing can be parsed the server prints the model's raw output to the
terminal, so "no error, but no new nodes" is always diagnosable:

```text
[synapse] 萃取結果解析不到 brain-update，原始輸出（… 字元）：
Here is the brain update code block: …
```

## Verification

```powershell
pytest -v
```

Manual E2E: add `python` + `fastapi` nodes → connect
`fastapi —depends_on→ python` → *Generate External Prompt* → paste a
`brain-update` reply into *Ingest → Sync to Brain* → canvas updates live.

Smoke-test a running server without hardcoding the port:

```powershell
$port = Get-Content .port
curl.exe "http://127.0.0.1:$port/api/graph"        # → nodes / edges
curl.exe -X POST "http://127.0.0.1:$port/api/compile-prompt" -H "Content-Type: application/json" -d '{"limit": 3}'
```

## Notes

- Frontend uses zero-build ES modules + Vis-Network CDN — no `npm` needed.
  It talks to the API through relative `/api/...` paths, so the dynamically
  chosen port needs no frontend changes.
- Categories: `topic | skill | persona | rule` (anything else → `topic`).
- Boost clamps weights to `[0.1, 10.0]`; malformed ingest blocks are skipped
  and reported in `errors` without aborting the rest of the sync.
- **Local models are slow.** Measured on CPU with `llama3:8b`: ~160 s for one
  chat turn plus ~90–160 s for the extraction pass. Use a smaller model
  (`$env:OLLAMA_MODEL="qwen2.5:1.5b"`) if that is too slow to wait for.
- **Event-driven decay.** Whenever a node is boosted (manually or via chat
  ingestion), every *other* `topic` / `skill` node has its weight multiplied by
  `0.98`, floored at `0.1`. `persona` and `rule` nodes are excluded so core
  identity and hard constraints never fade out. One decay pass per chat turn,
  not per boost — see `compiler.apply_ingest(..., decay_fn=...)`.
