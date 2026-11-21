# Chimney deployment on Dokploy

The application runs Flask, Gunicorn and a background inspection-upload worker in one image. Flask serves the React login and the server-rendered dashboards. Dokploy routes HTTPS traffic to port 8000.

## Existing installation

1. Record the current image or Git commit, the PostgreSQL backup identifier and the backup of the uploads volume. Verify that the backups can be restored to a separate environment. Keep the existing upload volume mounted at `/app/static/uploads`.
2. Build the candidate Git revision in staging with its own database and uploads volume. To test an upgrade, restore copies of both production backups there. Use staging credentials for external integrations.
3. Follow the release checks below. After they pass, select the same Git revision in the production application and choose **Deploy**. Keep manual deployments enabled. Check the running revision in Dokploy.
4. If a check fails, redeploy the previous image against the same database and uploads volume. Review schema compatibility first. A database or volume restore can discard newer writes and requires a separate recovery decision.

## First installation

1. Create a PostgreSQL database and a Dokploy Application backed by this repository. Select the root Dockerfile and container port 8000.
2. Set a persistent, randomly generated `SECRET_KEY` in the application's environment. Use the same value across workers and redeploys. Set `DATABASE_URL` to the internal database connection string, for example:

   ```text
   postgresql+psycopg://USER:PASSWORD@DATABASE_HOST:5432/DATABASE_NAME
   ```

   URL-encode special characters in credentials. The production supervisor requires both settings. Configure `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` for welcome email, and `GEMINI_API_KEY` for the portal assistant, if those features are needed. Earlier repository versions contained mail and AI credentials. Verify those credentials have been revoked before enabling either integration.

3. Mount a persistent volume at `/app/static/uploads`. Both inspection assets and the background job queue use this directory.
4. Deploy. The supervisor checks the database schema before launching Gunicorn and the upload worker. An unsuccessful check stops startup and appears in the deployment logs.
5. In the application console, create the first administrator with:

   ```sh
   python seed_db.py --admin-email you@example.com
   ```

   Enter the password at the prompt. Running the command again preserves an existing administrator's password. Use `python seed_db.py` to initialize role and module lookups only. Older installations should review any demo accounts already present.
6. Attach the intended domain to the application, enable HTTPS and verify the certificate and DNS point to this deployment.

## Release checks

| Check | Expected result |
| --- | --- |
| Home, login and dashboards | Home and login load. Signing in as Admin or Client opens the matching dashboard. A refresh preserves the session. |
| Project assignments | A restricted client sees their assigned Land Survey and inspection projects. An administrator can manage projects. |
| Upload worker | In a staging project, submit a small known-good file and watch it move from queued to completed. Confirm the file survives a staging redeploy. |
| Reports | An assigned client can open their inspection PDF. An administrator can download a combined PDF containing Land Survey and 3D Inspection projects. |
| Existing 3D model | Verify the saved model, a known finding, its image and its location in the viewer. Compare map styles with the same reference point. |
| External integrations | Use designated test accounts to check mail and the assistant if enabled. Review web and worker logs for errors. |

Use the [viewer checklist](docs/chimney_priority2_qa.md) for the compass, measurement, PDF and mobile checks. Keep the previous image available until the checks pass on the released revision.
