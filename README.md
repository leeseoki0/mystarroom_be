# mystarroom_be

FastAPI + SQLite backend for the Mystarroom / Luminote AI fan service MVP.

## Features

- Official MVP plot card API
- Guest profile onboarding/profile API with support style, safety preferences, and memory controls
- Home/continue APIs for active quest, relationship summary, and recent logbook entries
- Chat turn API for plot start, guided choices, and free input
- Report intake/admin queue API plus profile reset for post-incident recovery
- SQLite-backed profile, session, logbook, and report persistence
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
pytest -q
```

Targeted API smoke check:

```bash
PYTHONPATH=. python3 - <<'PY'
from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app(db_path='data/smoke.sqlite3'))
profile_id = client.post('/api/profiles', json={}).json()['profile']['id']
session_id = client.post('/api/chat/turn', json={'profile_id': profile_id, 'plot_id': 'p_luminote_001_first_light'}).json()['session']['id']
report = client.post(
    '/api/reports',
    json={
        'profile_id': profile_id,
        'session_id': session_id,
        'category': 'policy',
        'reason': 'smoke',
    },
).json()
reset = client.post(f'/api/profiles/{profile_id}/reset').json()
print(report['processing_status']['code'])
print(reset['reset'])
print(client.get(f'/api/profiles/{profile_id}/home').json())
PY
```

## API

- `GET /api/health`
- `GET /api/plot-cards`
- `POST /api/profiles`
- `GET /api/profiles/{profile_id}`
- `PATCH /api/profiles/{profile_id}`
- `GET /api/profiles/{profile_id}/home`
- `GET /api/profiles/{profile_id}/continue`
- `POST /api/profiles/{profile_id}/reset`
- `POST /api/chat/turn`
- `GET /api/sessions/{session_id}/logbook`
- `POST /api/reports`
- `GET /api/admin/reports`
- `POST /api/admin/plot-cards/validate`

SQLite data is stored under `data/luminote.sqlite3` by default and is ignored by git.
