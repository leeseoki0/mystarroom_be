# Development Log

## 2026-06-11 — Initial MVP backend baseline

### Summary

- Initialized `mystarroom_be` as the FastAPI + SQLite backend repository.
- Added MVP APIs for health checks, official plot cards, chat turns, logbook lookup, and operator plot-card validation.
- Added SQLite persistence for sessions and logbook entries.
- Added safety checks for real IP references, external contact/private info, and overdependence patterns.

### Verification

```bash
PYTHONPATH=. python3 -m pytest tests -q
```

Result: `4 passed, 1 warning`.

## 2026-06-11 — Local frontend CORS fix

### Summary

- Added loopback frontend origins for local Vite development: `http://127.0.0.1:5173` and preview `http://127.0.0.1:4173`.
- Added a regression test covering both `localhost:5173` and `127.0.0.1:5173` CORS preflight requests.

### Verification

```bash
PYTHONPATH=. python3 -m pytest tests -q
```

Result: `5 passed, 1 warning`.

### Merge policy note

During the initial MVP build, changes are merged directly into `main` after local verification, with this log used as the merge record. Final product review will focus on the latest `main` state.
