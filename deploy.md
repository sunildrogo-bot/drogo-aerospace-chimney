# Deploying Chimney (NOVA+) to Hostinger VPS

Stack: Flask (Gunicorn) + MySQL + Nginx + React frontend, all on one Ubuntu VPS.

Config templates referenced below live in `deploy/`:
- `deploy/chimney.service` — systemd unit for Gunicorn
- `deploy/nginx_chimney.conf` — Nginx site config

---

## 0. Before you start

- **Rotate secrets.** The `.env` that used to ship with this project had a real Gmail app password and Gemini API key in it. Treat both as compromised: revoke the Gmail app password and generate a new one at https://myaccount.google.com/apppasswords, and revoke/rotate the Gemini key at https://aistudio.google.com/apikey. Do not reuse the old values.
- **Point your domain at the VPS.** In Hostinger's DNS panel, add an A record for your domain (and `www`) pointing to the VPS's IP address.

---

## 1. Server setup

SSH in as root, update, and create a non-root deploy user:

```bash
ssh root@your_server_ip
apt update && apt upgrade -y
adduser deploy
usermod -aG sudo deploy
su - deploy
```

Install everything the stack needs:

```bash
sudo apt install python3-pip python3-venv python3-dev build-essential \
  default-libmysqlclient-dev pkg-config mysql-server nginx git nodejs npm -y
```

---

## 2. MySQL

```bash
sudo mysql_secure_installation
sudo mysql -u root -p
```

Inside the MySQL prompt:

```sql
CREATE DATABASE drogo_chimney_landsurvey CHARACTER SET utf8mb4;
CREATE USER 'chimney_user'@'localhost' IDENTIFIED BY 'strong_password_here';
GRANT ALL PRIVILEGES ON drogo_chimney_landsurvey.* TO 'chimney_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

Remember the password you set — you'll put it in `.env` in the next step.

---

## 3. Get the code onto the server

```bash
cd /home/deploy
git clone <your_repo_url> chimney-app
cd chimney-app
```

(Or `scp -r` this whole folder up if you're not using git.)

---

## 4. Configure `.env`

The `.env` in this project is a template with empty/placeholder values. Edit it on the server:

```bash
nano .env
```

Fill in:
- `DATABASE_URL` — put the real password you set for `chimney_user` in step 2
- `SECRET_KEY` — generate one: `python3 -c "import secrets; print(secrets.token_hex(32))"`
- `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` — your rotated Gmail app password (optional — without it, "welcome" emails just won't send)
- `GEMINI_API_KEY` — your rotated Gemini key (optional — without it, the chat assistant widget shows a "not configured" message instead of replying)

---

## 5. Backend: venv, dependencies, database tables

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python seed_db.py
```

`seed_db.py` creates all tables and a few demo users (safe to re-run — existing users are skipped by email match). **Log in and change the seeded admin password after first login** — it ships as `admin123` in `seed_db.py`.

Quick smoke test:

```bash
gunicorn --bind 0.0.0.0:8000 app:app
```

Visit `http://your_server_ip:8000` in a browser — you should see the login page. Ctrl+C once confirmed.

---

## 6. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

This produces `frontend/dist/` — the built React app that Nginx will serve directly (see step 8).

---

## 7. Gunicorn as a systemd service

Copy the provided unit file into place, adjusting paths/user if yours differ:

```bash
sudo cp deploy/chimney.service /etc/systemd/system/chimney.service
sudo systemctl daemon-reload
sudo systemctl start chimney
sudo systemctl enable chimney
sudo systemctl status chimney
```

`chimney.sock` will appear in `/home/deploy/chimney-app/` once it's running — that's what Nginx talks to.

---

## 8. Nginx

This app is a hybrid: the React SPA (built in step 6) currently owns `/`, `/login`, `/dashboard`, and `/admin` (which just bounces back into Flask); every other page (`/dvc`, `/mpptcl`, `/land-survey`, etc.) is still server-rendered by Flask, and `/api/`, `/uploads/`, `/static/` always go to Flask. The provided Nginx config routes accordingly.

```bash
sudo cp deploy/nginx_chimney.conf /etc/nginx/sites-available/chimney
sudo nano /etc/nginx/sites-available/chimney   # replace yourdomain.com with your real domain
sudo ln -s /etc/nginx/sites-available/chimney /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
```

As you migrate more pages from Jinja to React later, add them to the regex in the `location ~ ^/(login|dashboard|admin)$` block.

---

## 9. Firewall + SSL

```bash
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable

sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Certbot will edit the Nginx config to add HTTPS and set up auto-renewal.

---

## 10. Verify

- `https://yourdomain.com/` → React login page
- Log in with the seeded admin account, then **change its password immediately**
- Click into a module (e.g. 3D Inspection / Chimney) → should hit the Flask-rendered pages fine
- Upload a defect photo or similar → confirm it lands in `static/uploads/` and is served back via `/uploads/...`

## Troubleshooting

- **502 Bad Gateway** → Gunicorn isn't running or the socket path is wrong: `sudo systemctl status chimney` and check `journalctl -u chimney -e`
- **Blank page at `/dashboard` or `/login`** → `frontend/dist/` wasn't built, or Nginx isn't pointing `root` at the right path
- **DB connection errors on startup** → check `DATABASE_URL` in `.env` matches the MySQL user/password/db you created in step 2
- **Assistant widget says "not configured"** → `GEMINI_API_KEY` is empty in `.env`
