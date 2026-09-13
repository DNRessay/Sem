# SEMBLANCE — Running It

Production deployment is on AWS now — see **[AWS_DEPLOYMENT.md](./AWS_DEPLOYMENT.md)**
for the full setup (Lambda, Neon, DynamoDB cache, Modal embeddings, CI/CD, cost
breakdown). This page covers local development only.

## What you need

Copy `.env.example` → `.env` and fill in:

```env
GROQ_API_KEY=
GROQ_MODEL=qwen/qwen3-32b
GROQ_PLANNING_MODEL=deepseek-r1-distill-llama-70b
NEON_DATABASE_URL=postgresql://user:pass@host/semblance?sslmode=require
MODAL_EMBEDDINGS_URL=
SECRET_KEY=change-me
TRUST_MODE=AUTO
```

`MODAL_EMBEDDINGS_URL` can be left blank for local dev — `storage/embeddings.py`
falls back to a deterministic (non-semantic) vector so the pipeline still runs
without deploying the Modal function first.

`NEON_DATABASE_URL` needs a real Postgres with the `vector` extension
available — Neon's free tier has it preinstalled; a local Postgres works too
(`CREATE EXTENSION vector;` once, if your local build has pgvector).

## Local (dev)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000 by default
npm run dev
```

Deploys to Cloudflare Pages via `.github/workflows/cloudflare-pages.yml` on
push — see `docs/AWS_DEPLOYMENT.md` for the one-time Cloudflare setup.

## Tests

```bash
pytest tests/ -v
ruff check .
```

Tests use `moto` to mock DynamoDB and `respx` to mock the Groq API — no real
AWS credentials or network access needed to run the suite.

## Deploying the embeddings function (Modal)

```bash
pip install modal
modal setup
modal deploy modal_app/embeddings.py
```

## AWS deploy

```bash
pip install aws-sam-cli
sam build --use-container
sam deploy --guided
```

Full details, IAM/OIDC setup for CI, and the cost breakdown:
**[AWS_DEPLOYMENT.md](./AWS_DEPLOYMENT.md)**.
