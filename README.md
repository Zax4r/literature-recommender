# literature-recommender

Backend (FastAPI + PostgreSQL) for the book recommendation system. Current scope: registration, login, user profiles, book feed, favorites, minimal web UI at `/`.

## Run with Docker

    cp .env.example .env   # set SECRET_KEY
    docker compose up --build

API on http://localhost:8000, docs on /docs. Migrations run on container start.

## Local development

    uv sync
    docker compose up -d db          # Postgres; compose doesn't publish :5432, so run your own or add `ports`
    uv run alembic upgrade head
    uv run uvicorn app.main:app --reload

## Checks

    uv run ruff check . && uv run ruff format --check .
    uv run mypy .
    uv run pytest                    # uses in-memory SQLite

New migration: `uv run alembic revision --autogenerate -m "message"` (import new models in `app/models/__init__.py`).

## API (`/api/v1`)

| Method | Path | Auth | |
|---|---|---|---|
| POST | /auth/register | - | email, username, password |
| POST | /auth/login | - | form: `username` = email or username, `password`; returns JWT |
| GET / PATCH | /users/me | Bearer | own profile (display_name, bio) |
| GET | /users/{username} | - | public profile |
| POST | /books/import?count=100 | Bearer (admin) | streams the first usable books from the UCSD Book Graph; idempotent |
| GET | /books?offset=0&limit=20 | - | book feed (limit 1..100), returns `items`, `total`, `offset`, `limit` |
| GET | /books/{id} | - | title, authors, first 250 chars of description |
| PUT / DELETE | /books/{id}/favorite | Bearer | add / remove favorite (idempotent, 204) |
| GET | /users/me/favorites?offset&limit | Bearer | paginated favorites |

Book feed and details are public; with a Bearer token they also include `is_favorite`.

## Admin

A migration creates the default admin: login `admin`, password `admin` (**development only, change it before any real deployment**).
Only admins can run the import. Web UI: open http://localhost:8000/, log in as admin, press "Import 100 books".

## Data license

Books come from the [UCSD Book Graph](https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/UCSD%20Book%20Graph.html) (Goodreads),
collected for academic use only: no commercial use, no redistribution (don't commit the data or expose a public deployment).
Cite: Wan & McAuley, RecSys'18; Wan, Misra, Nakashole & McAuley, ACL'19.
