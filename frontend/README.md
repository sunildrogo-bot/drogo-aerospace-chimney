# DROGO AEROSPACE — Frontend (React SPA)

This is the new, decoupled frontend, talking to the existing Flask backend
purely over JSON APIs. It replaces the server-rendered Jinja templates
**incrementally** — see "Migration strategy" below.

## Architecture decision

We're **not** splitting the backend into microservices. With one team and
no current scaling pressure, that would add real operational cost
(service discovery, distributed auth, network failure handling, running
multiple processes instead of one) with no matching benefit right now.

Instead: the backend stays **one service**, already organized into
modules via Flask blueprints (`chimney_routes.py`, `projects_routes.py`,
`users_routes.py`, etc.) — a "modular monolith." This frontend is a
**separate, independently-run app** that talks to it only through the
JSON API. If a real need for microservices ever shows up, those module
boundaries are already there to split along.

## Local development

Two processes, run separately:

```bash
# Terminal 1 — the existing Flask backend, unchanged
cd ..
python app.py          # runs on http://127.0.0.1:5000

# Terminal 2 — this frontend
cd frontend
npm ci
npm run dev             # runs on http://localhost:5173
```

Open `http://localhost:5173`. Vite's dev server proxies `/api`,
`/static`, and `/uploads` requests to the Flask backend (see
`vite.config.js`), so the browser sees everything as same-origin — the
existing session cookie just works, no CORS setup needed.

## Production

Run `npm ci` and `npm run build` in this directory. Flask serves the built login page at `/login` and its files under `/assets/`. Both dashboards load as Flask pages after sign-in. The Vite development server also includes a React client-dashboard preview.

See the [deployment procedure](../DOKPLOY_DEPLOY.md) for the container build, acceptance checks and rollback.
