# mystarroom_be

FastAPI + SQLite backend for the Mystarroom / Luminote AI fan service MVP.

## Features

- Official MVP plot card API
- Chat turn API for plot start, guided choices, and free input
- SQLite-backed session and logbook persistence
- Safety checks for real IP references, external contact/private info, and overdependence patterns
- Optional OpenAI-compatible LLM provider for LM Studio or similar servers, with scripted fallback
- Operator plot-card validation endpoint

## Setup

```bash
python3 -m pip install -r requirements.txt
```

## Run

```bash
PYTHONPATH=. python3 -m uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/health
```

## LLM provider

By default the API uses deterministic scripted responses, so the app runs without an external model:

```env
LLM_PROVIDER=scripted
```

For LM Studio or another OpenAI-compatible server, copy `.env.example` to `.env` and set:

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://your-llm-server:1234/v1
LLM_API_KEY=your-api-key
LLM_MODEL=your-loaded-model-id
```

The frontend still calls only this FastAPI backend; never expose the LLM server key in the browser.

## Test

```bash
PYTHONPATH=. python3 -m pytest tests -q
```

## API

- `GET /api/health`
- `GET /api/plot-cards`
- `POST /api/chat/turn`
- `GET /api/sessions/{session_id}/logbook`
- `POST /api/admin/plot-cards/validate`

SQLite data is stored under `data/luminote.sqlite3` by default and is ignored by git.
