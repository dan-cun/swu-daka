# checkin-web architecture

This project separates source code from runtime data.

- Source code lives in `backend/`, `frontend/`, `docs/`, and `scripts/`.
- Runtime data lives in `data/`.
- Local secrets live in `.env` or an OS key store, never in source files.
- SQLite database files and logs are ignored by Git.

Current implemented database tables:

- `users`
- `credentials`

Planned placeholders:

- check-in task persistence
- check-in run persistence
- API event indexing
- password hashing
- school password encryption
- log cleanup policy

