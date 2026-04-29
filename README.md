# EscrowIQ

EscrowIQ is a Flask-based freelance marketplace prototype with escrow-backed payments, fraud scoring, hybrid freelancer matching, email verification, complaints/admin resolution, and in-app notifications.

## Overview

The application supports two primary roles:

- Clients can post jobs, review proposals, accept a freelancer, fund escrow, review submitted work, and raise complaints.
- Freelancers can maintain a skills profile, browse matched jobs, submit proposals, deliver work, and track escrow-backed payments.

An admin flow exists outside the normal user table and is configured through environment variables. Admins can review disputes and resolve them by releasing escrow, refunding the client, or closing the complaint without changing payout state.

## Core Features

- Role-based authentication with registration, login, logout, email verification, and password reset
- Job posting and browsing with fraud analysis on submission
- Proposal submission, acceptance, and rejection
- Escrow deposit, release, and refund flows
- Work delivery via note, external link, zip upload, or folder upload
- Complaint/dispute workflow with admin resolution
- In-app notifications plus SMTP email delivery
- Job messaging between the accepted client and freelancer
- AI-assisted fraud scoring, freelancer matching, and proposal drafting

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask 3.x |
| Database | PostgreSQL via SQLAlchemy Core + `psycopg2` |
| Frontend | Jinja templates + vanilla JavaScript |
| Matching / Fraud AI | scikit-learn TF-IDF + cosine similarity |
| Auth | Session-based auth |
| Email | SMTP |

## Project Structure

```text
Project/
├── Backend/
│   ├── app.py
│   ├── fraud_detection.py
│   ├── ml_matching.py
│   ├── run.py
│   ├── seed_ai_test_data.py
│   └── requirements.txt
├── Frontend/
│   ├── static/
│   └── templates/
├── tests/
│   └── test_core_flows.py
├── AI_TEST_CASES.md
├── PROPOSAL_ALIGNMENT_REVIEW.md
├── VERCEL_DEPLOYMENT.md
├── requirements.txt
└── vercel.json
```

## Architecture Notes

- `Backend/app.py` is the main application entrypoint and currently contains routes, schema initialization, auth helpers, notification/email helpers, business logic, and some AI-related orchestration.
- `Backend/fraud_detection.py` contains the hybrid fraud scoring logic.
- `Backend/ml_matching.py` contains TF-IDF semantic freelancer matching.
- Templates live under `Frontend/templates`, while static assets live under `Frontend/static`.
- The database schema is created automatically at startup through `init_db()`.

## AI Features

### 1. Fraud Detection

Jobs are analyzed before being saved. The fraud system supports:

- Rule-based scoring
- TF-IDF semantic similarity scoring
- Hybrid mode combining both

Environment flags:

- `AI_MODE=rules|hybrid|model`
- `AI_FALLBACK_ENABLED=true|false`

### 2. Hybrid Freelancer Matching

Clients can view recommended freelancers for a job, and freelancers can see jobs matched to their profile. Matching combines:

- Semantic similarity
- Skill overlap
- Rating normalization
- Review-count/experience weighting

### 3. Proposal Generation

Freelancers can generate proposal drafts from job context. The current implementation is template-driven and produces editable starter content rather than final submissions.

## Local Setup

### Prerequisites

- Python 3.10+
- PostgreSQL running locally
- A PostgreSQL database created manually before first run
- SMTP credentials for email delivery

### 1. Install Dependencies

From the project root:

```bash
pip install -r requirements.txt
```

Or from `Backend/`:

```bash
pip install -r requirements.txt
```

### 2. Create `Backend/.env`

Example:

```env
SECRET_KEY=replace-me
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/escrowIQ_db
PORT=5000
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=12345678
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM_EMAIL=your_email@gmail.com
SMTP_USE_TLS=true
SESSION_COOKIE_SECURE=false
FOUNDER_ALERT_EMAILS=founder1@example.com,founder2@example.com
AI_MODE=hybrid
AI_FALLBACK_ENABLED=true
```

Notes:

- `DATABASE_URL` must point to an existing PostgreSQL database.
- The app creates tables automatically, but it does not create the PostgreSQL database itself.
- Gmail requires an App Password if 2FA is enabled.

### 3. Run the App

Recommended:

```bash
cd Backend
python run.py
```

Alternative:

```bash
cd Backend
python app.py
```

Why `run.py` is recommended:

- It initializes the schema
- It seeds demo users/jobs
- It prints startup diagnostics

The app will be available at:

```text
http://localhost:5000
```

## Demo Data

`Backend/run.py` seeds demo accounts automatically when started successfully.

Default demo password:

```text
demo123
```

Seeded accounts include:

- Client demo users
- Freelancer demo users
- Welcome notifications
- Dynamic demo job postings

You can also seed AI-specific test data manually:

```bash
cd Backend
python seed_ai_test_data.py
```

See [AI_TEST_CASES.md](AI_TEST_CASES.md) for suggested fraud and matching scenarios.

## Testing

Integration-style tests live in [tests/test_core_flows.py](tests/test_core_flows.py).

They cover major flows including:

- Registration, verification, and login
- Password reset
- Proposal acceptance rules
- Escrow funding/release/refund
- Work submission
- Complaint resolution
- Notification/email side effects

Run tests from the project root:

```bash
python -m unittest tests.test_core_flows
```

Important:

- Tests require a valid PostgreSQL `DATABASE_URL`
- The suite is skipped if PostgreSQL is not configured

## Deployment

### Vercel

This repo includes [vercel.json](vercel.json) to route requests to `Backend/app.py`.

If this project is deployed from a larger monorepo, set the Vercel root directory to:

```text
Project
```

Required production environment variables include:

- `SECRET_KEY`
- `DATABASE_URL`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`

Production notes:

- Do not use a local `localhost` database URL on Vercel
- Use a hosted PostgreSQL database instead
- Set `SESSION_COOKIE_SECURE=true`
- Uploaded files are currently stored on the local filesystem, which is not durable on typical serverless platforms

See [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md) for the current deployment notes.

## Main Routes

### Pages

- `/`
- `/register`
- `/login`
- `/verify-email`
- `/forgot-password`
- `/dashboard`
- `/jobs`
- `/jobs/<job_id>`
- `/profile`
- `/escrow`
- `/admin/complaints`

### APIs

- `/api/register`
- `/api/login`
- `/api/logout`
- `/api/auth/verify-email`
- `/api/auth/resend-verification`
- `/api/auth/request-password-reset`
- `/api/auth/reset-password`
- `/api/jobs`
- `/api/proposals`
- `/api/escrow/deposit`
- `/api/submissions/<submission_id>/approve`
- `/api/jobs/<job_id>/complaints`
- `/api/admin/complaints/<complaint_id>/resolve`
- `/api/ai/generate-proposal`
- `/api/ai/analyze-fraud`
- `/api/ai/match-freelancers/<job_id>`
- `/api/ai/ml-match/<job_id>`

## Current Limitations

- `Backend/app.py` is still monolithic and would benefit from blueprints/services
- Proposal generation is template-based, not LLM-backed
- File uploads are stored locally rather than in object storage
- Some deployment targets may need extra handling for persistent file storage
- There is a Python deprecation warning around `datetime.utcnow()` that should be cleaned up later

## Additional Documentation

- [AI_TEST_CASES.md](AI_TEST_CASES.md)
- [PROPOSAL_ALIGNMENT_REVIEW.md](PROPOSAL_ALIGNMENT_REVIEW.md)
- [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md)

