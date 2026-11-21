# Chimney inspection portal

NOVA+ manages 3D inspections and Land Survey projects. Flask serves the API, dashboards and reports. React provides the production login page. Inspection uploads use a background worker and a persistent uploads directory.

## Run locally

From the repository root, use Python 3.12 and Node.js 22.

```sh
python -m venv venv
. venv/bin/activate
python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
python seed_db.py --admin-email you@example.com
python app.py
```

Open `http://127.0.0.1:5000/`. Local development defaults to SQLite in `instance/nova.db`. The development server generates a new session key on restart unless `SECRET_KEY` is configured. For background uploads during development, run `python chimney_upload_worker.py` from the same environment in a second terminal. Use `python seed_db.py --demo` only when sample accounts and projects are wanted in a development database.

## Check a release

```sh
python -m unittest discover -s tests -v
npm --prefix frontend ci
npm --prefix frontend run build
for script in static/js/*.js; do node --check "$script" || exit 1; done
```

The PostgreSQL upgrade test uses a temporary schema when `CHIMNEY_TEST_POSTGRES_URL` is set. Point this variable at a disposable test database. The release workflow also builds the production image and checks both login roles through a browser.

## Deployment

Use the [Dokploy procedure](DOKPLOY_DEPLOY.md) for the container deployment and the [viewer checklist](docs/chimney_priority2_qa.md) for inspection acceptance. A [systemd and Nginx procedure](deploy.md) is available for a manually managed VPS.
