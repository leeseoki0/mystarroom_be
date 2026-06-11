# mystarroom_be

FastAPI + SQLite backend for the Mystarroom / Luminote AI fan service MVP.

## Features

- Official MVP plot card API
- Chat turn API for plot start, guided choices, and free input
- SQLite-backed session and logbook persistence
- Safety checks for real IP references, external contact/private info, and overdependence patterns
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
