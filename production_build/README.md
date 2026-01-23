# Production Build Layout

- `backend/` — FastAPI service wired to OpenAI (no local models). Deploy to Render/Fly/any host that runs Python. See `backend/README.md`.
- `frontend/` — Static chat widget (HTML/CSS/JS). Drag-and-drop to any host; set `window.RM_API_BASE` to point at your backend. See `frontend/README.md`.
