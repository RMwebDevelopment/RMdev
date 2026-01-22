# Backend (FastAPI + OpenAI)

Deployable backend for the chat widget. No local models are required; it calls OpenAI’s Chat Completions API with tool calling.

## Quick start (Render or any host)
1. Set repo root to this folder: `demo & Production Build/production_build/backend`.
2. Install deps: `pip install -r requirements.txt` (Python 3.10+).
3. Env vars:
   - `OPENAI_API_KEY` (required if you’re single-tenant; optional if you load keys from Sheets per tenant)
   - `MODEL_NAME` (optional, default `gpt-4o-mini`)
   - Optional Sheets: `SHEETS_SPREADSHEET_ID`, `SHEETS_PROMPT_RANGE` (default `Settings!A:C`), `SHEETS_LEADS_RANGE` (default `Leads!A:J`), `SHEETS_LEADS_URL` (webhook).
   - Multi-tenant keys via Sheets: set `SHEETS_SPREADSHEET_ID` and add a `Keys` tab with columns `business_id`, `openai_api_key`, `model` (optional), `sheet_id` (tenant-specific Sheets ID, optional), `status` (`active`/`paused`), `rate_limit_per_min` (optional). Configure range with `TENANT_KEYS_RANGE` (default `Keys!A:G`). Cache TTL via `TENANT_KEYS_CACHE_TTL` (seconds, default 300).
4. Run locally: `uvicorn server.main:app --host 0.0.0.0 --port 8000`

### Render one-liner
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn server.main:app --host 0.0.0.0 --port $PORT`
- **Env:** set the variables above in Render.

## API
- `POST /api/chat` – body `{business_id, conversation_id?, message}`; returns `{reply, routing, conversation_id, profile, lead_captured}`.
- `POST /api/lead` – body `{business_id, conversation_id?, name, email, phone, contact_method, preferred_time?, intent, urgency?, summary}`.
- `GET /api/health`, `/api/availability`, `/api/inventory` for diagnostics.

## Data & prompts
- `server/availability.json`, `server/inventory.json`, `server/prompt.txt` are read-only defaults. Override with env `SYSTEM_PROMPT_PATH`, `SHEETS_SPREADSHEET_ID` if you want live sheet data.
- SQLite data lives in `server/data/app.db` (auto-created). Mount a persistent disk in production.

## CORS & frontend
- The backend allows all origins by default. To restrict, set `CORS_ALLOW_ORIGINS` to a comma-separated list (e.g., `https://yoursite.com,https://clientsite.com`).
- Point the frontend’s `API_BASE` to the deployed host (e.g., `https://yourapp.onrender.com`); see the frontend README.
