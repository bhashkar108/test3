# Gov Form Guide (AI-02)

```
govform-guide/
├── backend/   main.py, requirements.txt, .env.example
└── frontend/  src/App.jsx  (drop into a Vite React app)
```

## 1. API key
Get a key at https://aistudio.google.com/apikey. Keep it **server-side only** (never in React code or git).

## 2. Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # paste GEMINI_API_KEY
uvicorn main:app --reload --port 8000                # docs: http://localhost:8000/docs
```

## 3. Frontend
```bash
cd frontend
cp .env.example .env        # VITE_API_URL=http://localhost:8000
npm install
npm run dev                 # http://localhost:5173
```

## 4. Deploy
**Backend → Render** (Web Service, root `backend`): build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`. Env vars: `GEMINI_API_KEY`, `ALLOWED_ORIGINS=https://<your-netlify-site>`.
**Frontend → Netlify**: build `npm run build`, publish `dist`, env `VITE_API_URL=https://<render-app>.onrender.com`.
Render free tier sleeps; open `/api/health` before your demo.

## Demo notes / hardening
- Sessions are in memory (lost on restart); use Redis/DB for production.
- Uploads are never written to disk; ID images are processed in memory only. Add auth + rate limiting before real use.
- Run `python backend/smoke_test.py <base_url> [image] [form.pdf]` before presenting.
- `render.yaml` (repo root) deploys the backend; `frontend/netlify.toml` configures Netlify (set base directory to `frontend`).
- Compression uses JPEG binary search on quality, then downscales if needed.
- Auto-rotate falls back to 0° if Gemini is unreachable.
- TTS uses the browser Web Speech API; regional voices depend on the device.
