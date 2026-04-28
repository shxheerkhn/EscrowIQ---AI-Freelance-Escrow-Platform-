Vercel deployment prep

This project now includes `vercel.json` so Vercel can route requests to `Backend/app.py`.

Before deploying:

1. Set the required environment variables in Vercel:
   `SECRET_KEY`
   `DATABASE_URL`
   `ADMIN_EMAIL`
   `ADMIN_PASSWORD`
   `SMTP_HOST`
   `SMTP_PORT`
   `SMTP_USERNAME`
   `SMTP_PASSWORD`
   `SMTP_FROM_EMAIL`

2. Make sure the PostgreSQL database is reachable from Vercel.

3. Confirm the production database already exists and the app has permission to create/alter tables.

Notes:

- This repository can be deployed from Vercel after the environment is configured.
- The live deployment itself was not executed from this workspace.
