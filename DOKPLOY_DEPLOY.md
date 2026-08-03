# Deploying Chimney (NOVA+) to Dokploy

This replaces the manual Nginx/systemd setup in `deploy.md` — Dokploy builds
the `Dockerfile` in this repo, runs it as a container, and handles the
reverse proxy + SSL automatically via its built-in Traefik.

---

## 0. Before you start

- Rotate the Gmail app password and Gemini API key — the ones that shipped
  in earlier versions of this project were exposed and must be treated as
  compromised.
- Push this repo (with the `Dockerfile`, `.dockerignore`, and the updated
  `app.py`) to GitHub if it isn't already there.

---

## 1. Create the PostgreSQL database in Dokploy

In the Dokploy dashboard:

1. **Create Project** (if you don't have one yet) → give it a name like
   `chimney`.
2. Inside the project: **Create → Database → PostgreSQL**.
3. Set a database name (e.g. `drogo_chimney_landsurvey`), a root/user
   password — Dokploy will show you the **internal connection string**
   once it's running (something like
   `postgresql://user:pass@chimney-postgresql:5432/drogo_chimney_landsurvey`).
   Copy this — you'll need it for step 3.

---

## 2. Create the app from this repo

1. Inside the same project: **Create → Application**.
2. **Source**: connect your GitHub account (if not already) and select
   `sunildrogo-bot/drogo-aerospace-chimney`, branch `main`.
3. **Build type**: Dockerfile (Dokploy should auto-detect the `Dockerfile`
   at the repo root).
4. **Port**: `8000` (matches `EXPOSE 8000` / the Gunicorn bind in the
   Dockerfile).

---

## 3. Set environment variables

In the app's **Environment** tab, add:

```
DATABASE_URL=postgresql+pypostgresql://<user>:<password>@<postgresql-service-name>:5432/drogo_chimney_landsurvey
SECRET_KEY=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
GMAIL_ADDRESS=<your rotated Gmail address, optional>
GMAIL_APP_PASSWORD=<your rotated app password, optional>
MAIL_SENDER_NAME=Drogo Aerospace
GEMINI_API_KEY=<your rotated key, optional>
```

Use `postgresql+pypostgresql://` (not the bare `postgresql://` Dokploy shows you) — that
prefix is what SQLAlchemy needs to pick the right driver. The
`<postgresql-service-name>` is the internal hostname Dokploy assigned the
database service (visible on the database's own page — usually something
like the database's name).

---

## 4. Add a volume for uploads (recommended)

Without this, every redeploy wipes `static/uploads/` (defect photos,
tilesets, rectified images) since the container filesystem is ephemeral.

In the app's **Volumes** (or **Mounts**) tab, add:

```
Container path: /app/static/uploads
```

Dokploy will back this with a persistent volume on the host, so uploads
survive redeploys.

---

## 5. Deploy

Click **Deploy**. Dokploy will:
1. Clone the repo
2. Build the `Dockerfile` (compiles the React frontend, installs Python
   deps, packages everything into one image)
3. Start the container on port 8000

Watch the build logs — the frontend `npm run build` and Python
`pip install` steps will show here. A successful build ends with the
container showing as **Running**.

---

## 6. Seed the database (one-time)

Dokploy's app page has a **Terminal/Console** tab (or you can `docker
exec` into the container from the VPS if you have shell access). Run:

```bash
python seed_db.py
```

This creates all tables and demo users (safe to re-run). **Change the
seeded admin password after first login** — `sunil@drogodrones.com` /
`admin123` is a known default.

---

## 7. Point your domain at it

In the app's **Domains** tab in Dokploy:
1. Add `semistar.online` (and `www.semistar.online` if you want both).
2. Dokploy shows you the DNS target — usually just your VPS's IP for an
   A record, same as before:

   | Type | Name | Value |
   |---|---|---|
   | A | `@` | your VPS IP |
   | A | `www` | your VPS IP |

3. Enable **HTTPS** in the same tab — Dokploy's Traefik requests and
   renews the Let's Encrypt certificate automatically. No `certbot`
   commands needed.

---

## 8. Verify

- `https://semistar.online/` → Flask home page
- `https://semistar.online/login` → React login (background photo, glass
  card, animated Client/Admin toggle)
- Log in → `/admin` or `/dashboard` → original Jinja pages, unchanged
- Upload a defect photo → confirm it persists after a redeploy (tests the
  volume from step 4)

## Redeploying after code changes

Push to `main` on GitHub, then click **Deploy** again in Dokploy (or
enable auto-deploy on push in the app's settings). No manual `git pull` /
`npm run build` / `systemctl restart` — Dokploy rebuilds the whole image
fresh each time.

## Notes on what changed from the manual VPS setup

- `app.py` now serves `frontend/dist/index.html` directly at `/login` and
  the built JS/CSS at `/assets/*` — no separate Nginx `location` blocks
  needed to split traffic between React and Flask.
- Everything else (`/admin`, `/dashboard`, `/dvc`, etc.) is untouched —
  still plain Jinja-rendered Flask routes, exactly as before.
