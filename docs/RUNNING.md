# SEMBLANCE — Local development

This page is for running the app on your own machine. Deployment (AWS, Cloudflare, Modal, GitHub secrets)
is in [AWS_DEPLOYMENT.md](./AWS_DEPLOYMENT.md).

## Backend

Python 3.13 (what CI and Lambda use).

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt   # requirements-dev.txt alone has only the test/lint tools
cp .env.example .env
```

Minimum `.env` to get chat working:

```env
GROQ_API_KEY=<your Groq key>
NEON_DATABASE_URL=postgresql://user:pass@host/semblance?sslmode=require
SECRET_KEY=<any long random string>
```

- `NEON_DATABASE_URL` must be a Postgres where the `vector` extension can be created. Neon has it; a local
  Postgres with pgvector installed also works. The app creates the extension and its tables on startup.
- Login needs an `owner` account in that database. Create one with the seed script:

  ```bash
  NEON_DATABASE_URL=... OWNER_ACCOUNTS_JSON='[{"id":"owner","passphrase":"<pick one>","role":"owner"}]' \
    python scripts/seed_accounts.py
  ```

- Everything else is optional. Blank `MODAL_EMBEDDINGS_URL` uses a deterministic, non-semantic fallback
  vector. Blank `MODAL_REPO_URL` makes "Add repo" a one-shot text dump instead of a live clone. Without
  AWS credentials the DynamoDB cache falls back to in-memory. Other keys (Gemini, Cohere, Modal video, etc.)
  are listed in `config.py`; each feature is off until its key is set.

Run it:

```bash
uvicorn main:app --reload --port 8000
```

Locally (not on Lambda) KAIROS runs as a background loop inside the server instead of the 15-minute tick.

## Frontend

```bash
cd frontend
npm install
cp .env.example .env    # contains VITE_API_URL=http://localhost:8000
npm run dev
```

`VITE_API_URL` is read at build time; point it at `http://localhost:8000` for local work or at the Lambda
Function URL (no trailing slash) to use the deployed backend.

## Tests and lint

```bash
python -m pytest -q
ruff check .
```

The tests mock DynamoDB with `moto` and HTTP calls with `respx`, so they need no AWS credentials or network.
CI runs the same two commands (`python -m pytest tests/ -v --tb=short`) before every deploy.
