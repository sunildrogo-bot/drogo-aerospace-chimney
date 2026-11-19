# Chimney on a manually managed VPS

The primary release procedure uses [Dokploy](DOKPLOY_DEPLOY.md). This alternative runs the same supervisor on an Ubuntu server with systemd and Nginx.

1. Use a non-root deployment account and check out the intended revision in `/home/deploy/chimney-app`. Install Python 3.12 with venv support, Node.js 22, Nginx and the selected database service.
2. Create the database and application user. In the repository root, create a private `.env` file readable by the deployment user. Set a persistent random `SECRET_KEY` and `DATABASE_URL`. Use `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB` with PostgreSQL or `mysql+pymysql://USER:PASSWORD@HOST:3306/DB` with MySQL. The database account needs permission to create missing tables and add columns. Keep the uploads directory and database across releases.
3. Build from the repository root:

   ```sh
   python3 -m venv venv
   . venv/bin/activate
   python -m pip install -r requirements.txt
   npm --prefix frontend ci
   npm --prefix frontend run build
   python -m unittest discover -s tests -v
   ```

4. For a first installation, run `python seed_db.py --admin-email you@example.com` and enter the administrator password at the prompt. Subsequent deployments use the existing accounts.
5. Install `deploy/chimney.service` under `/etc/systemd/system/`. Check the working directory, environment-file path and service user. The supervisor starts the database check, Gunicorn and the background upload worker. The service configures Gunicorn to listen on `/home/deploy/chimney-app/chimney.sock`.
6. Install `deploy/nginx_chimney.conf` under `/etc/nginx/sites-available/`, set the intended domain and enable the site. Give Nginx access to the socket and its parent directories. Configure TLS for that domain.
7. Apply the configuration:

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now chimney
   sudo nginx -t && sudo systemctl reload nginx
   sudo systemctl status chimney
   ```

For upgrades, record the previous revision, verify database and upload backups, build and test the candidate, and then restart the service with `sudo systemctl restart chimney`. Use the release checks and rollback procedure in the [deployment guide](DOKPLOY_DEPLOY.md). Inspect startup and upload-worker messages with `journalctl -u chimney`.
