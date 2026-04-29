# EscrowIQ

EscrowIQ is a freelance marketplace prototype built around an escrow-first workflow: clients post jobs, freelancers send proposals, one proposal is accepted, funds are locked in escrow, work is submitted for review, and payment is either released, revised, disputed, or refunded.

The project combines a Flask backend, PostgreSQL persistence, server-rendered Jinja templates, session auth, SMTP email notifications, and lightweight AI-style features for fraud analysis, ranking, and proposal drafting.

## Highlights

- Client and freelancer accounts with email verification
- Session-based authentication with CSRF protection
- Job posting with fraud scoring and validation
- Proposal lifecycle with accept/reject flows
- Escrow funding tied to the accepted freelancer and accepted bid amount
- Work submission with delivery note, link, zip upload, or folder upload
- Change requests, complaints, and admin complaint resolution
- In-app notifications plus branded email notifications
- AI-style fraud analysis, matching, and proposal generation
- Cookie consent banner for a more realistic frontend experience

## Tech Stack

- Backend: Flask, SQLAlchemy Core, psycopg2
- Database: PostgreSQL
- Frontend: Jinja2 templates, vanilla JavaScript, custom CSS
- ML / scoring: scikit-learn TF-IDF similarity plus rule-based logic
- Email: SMTP
- Password hashing: Werkzeug security helpers
- Testing: Python `unittest`

## Repository Layout

```text
Project/
├─ Backend/
│  ├─ app.py                  # Main Flask app, routes, schema creation, emails, escrow logic
│  ├─ run.py                  # Local startup + demo data seeding
│  ├─ seed_ai_test_data.py    # Optional AI-specific seed script
│  ├─ fraud_detection.py      # Fraud scoring logic
│  ├─ ml_matching.py          # TF-IDF semantic matching helpers
│  ├─ requirements.txt        # Backend dependency list
│  ├─ .env                    # Local environment variables
│  └─ uploads/                # Submitted work archives
├─ Frontend/
│  ├─ templates/              # Jinja templates
│  └─ static/                 # Static assets, images, logo
├─ tests/
│  └─ test_core_flows.py      # Integration-style workflow tests
├─ requirements.txt           # Root dependency list
├─ AI_TEST_CASES.md
├─ PROPOSAL_ALIGNMENT_REVIEW.md
├─ VERCEL_DEPLOYMENT.md
└─ vercel.json
```

## Core User Flows

### Client Flow

1. Register and verify email
2. Post a job with title, description, skills, budget, and deadline
3. Review incoming proposals
4. Accept one proposal
5. Fund escrow for the accepted freelancer
6. Review submitted work
7. Approve work, request changes, or file a complaint

### Freelancer Flow

1. Register with at least one skill and a stronger password
2. Verify email and complete profile
3. Browse jobs or matched opportunities
4. Submit a proposal with bid, timeline, and cover letter
5. Wait for acceptance and escrow funding
6. Submit work using note, link, zip, or folder upload
7. Respond to changes requested or complaint outcomes

### Admin Flow

1. Sign in using `ADMIN_EMAIL` and `ADMIN_PASSWORD`
2. Review complaint queue
3. Resolve with one of:
   - `release`
   - `refund`
   - `close`
4. System updates escrow, job, and submission state atomically

## Feature Breakdown

### Authentication and Account Security

- Email verification by 6-digit code
- Password reset by 6-digit code
- Session-backed login
- CSRF enforcement for mutating API routes
- Registration validation:
  - freelancer skills required
  - stronger passwords required
- Profile editing for name, bio, and freelancer skills

### Job Posting

- Clients only
- Required fields:
  - title
  - description
  - required skills
  - budget
  - deadline
- Validation includes:
  - minimum title length
  - more realistic description length / word count
  - at least 2 required skills
  - valid future deadline

### Proposal Lifecycle

- Freelancers only
- One proposal per freelancer per job
- Clients can accept one proposal
- Other pending proposals are auto-rejected when one is accepted
- Proposal events create in-app notifications and branded emails

### Escrow

- Only clients can fund escrow
- Only for the accepted freelancer
- Escrow amount must match the accepted bid amount
- Balance is deducted atomically when escrow is created
- Release / refund actions update balances and statuses atomically

### Work Submission

- Freelancer must be the accepted freelancer
- Escrow must already be funded
- Supported submission content:
  - delivery note
  - external work link
  - zip file
  - folder upload packaged server-side into a zip
- Validation includes:
  - no empty submissions
  - `http://` or `https://` link format
  - zip / folder mutual exclusivity

### Review, Revisions, and Complaints

- Clients can:
  - approve work
  - request changes
  - file a complaint
- Change requests require detailed feedback
- Complaints move the job into a disputed state
- Admin can resolve complaints and notify both parties

### Notifications and Email

- In-app notification dropdown
- Email notifications for:
  - verification
  - password reset
  - proposals
  - escrow funding
  - work submitted
  - changes requested
  - complaint opened
  - complaint resolved
  - payment released
- Branded HTML email layout with embedded logo support

### AI / Ranking Features

#### Fraud Detection

- Rule-based and TF-IDF-style hybrid scoring
- Risk labels:
  - Low
  - Medium
  - High
- Stores fraud reasons and score per job

#### Matching

- Semantic similarity using TF-IDF
- Skill overlap and synonym expansion
- Rating and review count signal blending

#### Proposal Generation

- Template-based proposal drafts
- Uses job title, description, and skill context

## Local Setup

### Prerequisites

- Python 3.10+
- PostgreSQL
- SMTP credentials for email delivery

### Install Dependencies

From the project root:

```powershell
pip install -r requirements.txt
```

If you prefer the backend-specific list:

```powershell
pip install -r Backend/requirements.txt
```

## Environment Variables

This project currently reads local environment variables from `Backend/.env`.

Typical keys used by the app:

```env
SECRET_KEY=change-me
DATABASE_URL=postgresql://username:password@localhost:5432/escrowiq

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-email@example.com
SMTP_USE_TLS=true

ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=change-me
FOUNDER_ALERT_EMAILS=founder@example.com

SESSION_COOKIE_SECURE=false
AI_MODE=hybrid
AI_FALLBACK_ENABLED=true
```

## Running the App

The intended local entry point is:

```powershell
python Backend/run.py
```

What `Backend/run.py` does:

- loads `Backend/.env`
- initializes the schema if needed
- seeds demo users and jobs
- starts the Flask app

Default local URL:

```text
http://localhost:5000
```

## Demo / Seed Data

`Backend/run.py` seeds sample clients, freelancers, and jobs for a richer local demo.

There is also an optional AI-focused seed script:

```powershell
python Backend/seed_ai_test_data.py
```

That script creates:

- `ai_test_client@escrowiq.local`
- several freelancer profiles with matching-friendly skills
- jobs tailored to fraud scoring and recommendation scenarios

Default seeded password used there:

```text
demo123
```

## Running Tests

```powershell
python -m unittest tests.test_core_flows
```

Notes:

- tests are integration-style and expect PostgreSQL
- if `DATABASE_URL` is missing or not PostgreSQL, tests are skipped
- some test behavior depends on app config such as `TESTING=True`

## Important Files

### Backend

- [Backend/app.py](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/Backend/app.py>)
  Main application logic, routes, schema management, validation, escrow, emails, notifications.

- [Backend/run.py](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/Backend/run.py>)
  Local startup script and demo data seeding.

- [Backend/seed_ai_test_data.py](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/Backend/seed_ai_test_data.py>)
  Optional AI testing dataset.

- [Backend/fraud_detection.py](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/Backend/fraud_detection.py>)
  Fraud analysis implementation.

- [Backend/ml_matching.py](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/Backend/ml_matching.py>)
  TF-IDF semantic matching logic.

### Frontend

- [Frontend/templates/base.html](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/Frontend/templates/base.html>)
  Shared layout, navbar, notifications, toast system, cookie consent banner.

- [Frontend/templates/dashboard_client.html](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/Frontend/templates/dashboard_client.html>)
  Client dashboard and job creation UI.

- [Frontend/templates/job_detail.html](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/Frontend/templates/job_detail.html>)
  Proposal review, escrow actions, work submission, complaint flow.

## Deployment Notes

This repository includes:

- [vercel.json](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/vercel.json>)
- [VERCEL_DEPLOYMENT.md](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/VERCEL_DEPLOYMENT.md>)

Before deployment:

- set all required environment variables
- ensure PostgreSQL is reachable from the host
- confirm SMTP credentials are valid in production
- set `SESSION_COOKIE_SECURE=true` behind HTTPS
- use a strong `SECRET_KEY`

## Current Realism / UX Notes

- The new cookie banner is a frontend realism feature and stores consent in `localStorage`
- Essential cookies are still used by the app for sessions and CSRF regardless of optional preference consent
- The project is still a prototype, not a production-hardened legal/privacy implementation

## Known Limitations

- No full migrations system such as Alembic
- Cookie consent is UI-only, not a full compliance framework
- SMTP and admin auth are environment-driven and fairly simple
- The app uses server-rendered templates rather than a component frontend
- Some docs in the repository are legacy notes and overlap with this README

## Related Project Notes

- [AI_TEST_CASES.md](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/AI_TEST_CASES.md>)
- [PROPOSAL_ALIGNMENT_REVIEW.md](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/PROPOSAL_ALIGNMENT_REVIEW.md>)
- [VERCEL_DEPLOYMENT.md](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/VERCEL_DEPLOYMENT.md>)
- [# EscrowIQ — Developer README.txt](</d:/FAST 6th Semester/Web Programming/Semester Project/Project Files/Web-Programming-main/Web-Programming-main/Project/# EscrowIQ — Developer README.txt>)

## Quick Start Summary

```powershell
pip install -r requirements.txt
python Backend/run.py
```

Then open:

```text
http://localhost:5000
```

