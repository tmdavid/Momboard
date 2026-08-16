# Getting Started

Requirements: Python 3.11, Node.js 20+, SQLite (bundled). Postgres optional.

```bash
git clone https://github.com/tmdavid/Momboard && cd Momboard

python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

cp .env.example .env      # set OPENAI_API_KEY, or see [[Local LLM Setup]]
mkdir -p data

.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed                       # seeds the tag taxonomy
.venv/bin/python -m app.users create --email you@example.com --role admin

cd web && npm install && npm run build && cd ..
.venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000, log in, hit **＋ New conversation**, and paste a transcript — the fixtures in `fixtures/` (see [[Fixtures and Evals]]) are made for exactly this first run.

## The first five minutes

1. Upload `fixtures/enforcement_heavy_user.vtt` with any metadata.
2. Watch the pipeline chips: normalizing → tagging → analyzing → ready.
3. Open the conversation. Review suggestions keyboard-first: `j`/`k` to move, `a` accept, `x` reject.
4. Check the analysis sidebar — summary, top pains, commitments, and the Mom Test critique score.
5. Go to **Explore**, filter by ⚡ pain, and click *Synthesize this view* once you have a few conversations in.

## Configuration

Everything is env-driven (`.env`): `DATABASE_URL` (SQLite default, swap to Postgres per `DESIGN.md` §8), `LLM_BACKEND` (`openai` | `local`), per-agent model names, `SESSION_SECRET`. Deployment (Docker, Fly.io, backups) is covered in the repo's `DEPLOY.md`.
