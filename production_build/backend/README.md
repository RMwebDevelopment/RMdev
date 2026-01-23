# Backend (FastAPI + OpenAI)

Deployable backend for the chat widget. No local models are required; it calls OpenAI’s Chat Completions API with tool calling.

## Quick start (Render or any host)
1. Set repo root to this folder: `demo & Production Build/production_build/backend`.
2. Install deps: `pip install -r requirements.txt` (Python 3.10+).
3. Env vars:
   - `OPENAI_API_KEY` (required for cloud/openai providers)
   - `MODEL_NAME` (optional, default `gpt-4o-mini`)
   - Sheets: `SHEETS_SPREADSHEET_ID`, `SHEETS_PROMPT_RANGE` (default `Settings!A:C`), `SHEETS_LEADS_RANGE` (default `Leads!A:J`), `SHEETS_LEADS_URL` (webhook), `SHEETS_LISTINGS_RANGE` (default `Listings!A:R`).
4. Run locally: `uvicorn server.main:app --host 0.0.0.0 --port 8000`

### Render one-liner
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn server.main:app --host 0.0.0.0 --port $PORT`
- **Env:** set the variables above in Render.

## API
- `POST /api/chat` – body `{conversation_id?, message, sheet_id?}`; returns `{reply, routing, conversation_id, profile, lead_captured}`.
- `POST /api/lead` – body `{conversation_id?, name, email, phone, contact_method, preferred_time?, intent, urgency?, summary, sheet_id?}`.
- `GET /api/health` for diagnostics.
- `GET /api/listings` returns the Listings tab (if configured) for quick verification.

## Data & prompts
- `server/prompt.txt` is the default system prompt. Override with env `SYSTEM_PROMPT_PATH` or load tone/name from the `Settings` tab via `SHEETS_SPREADSHEET_ID`.
- SQLite data lives in `server/data/app.db` (auto-created). Mount a persistent disk in production.

## CORS & frontend
- The backend allows all origins by default. To restrict, set `CORS_ALLOW_ORIGINS` to a comma-separated list (e.g., `https://yoursite.com,https://clientsite.com`).
- Point the frontend’s `API_BASE` to the deployed host (e.g., `https://yourapp.onrender.com`); see the frontend README.
