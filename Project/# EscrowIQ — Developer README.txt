# EscrowIQ — Developer README

> Freelance escrow marketplace with built-in fraud detection, hybrid AI matching, and secure payment flows.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Getting Started](#3-getting-started)
4. [Environment Variables](#4-environment-variables)
5. [What Has Been Implemented](#5-what-has-been-implemented)
6. [AI Features — Implementation Detail](#6-ai-features--implementation-detail)
7. [Implementation Status vs Developer Brief](#7-implementation-status-vs-developer-brief)
8. [Known Gaps and Remaining Work](#8-known-gaps-and-remaining-work)
9. [File Structure](#9-file-structure)
10. [Demo Accounts](#10-demo-accounts)

---

## 1. Project Overview

EscrowIQ is an escrow-backed freelance hiring platform. Clients post jobs, freelancers apply with proposals, a single proposal is accepted, funds are locked in escrow, work is submitted and reviewed, and payment is released or refunded. A dispute/complaint system routes unresolved cases to an admin.

Three AI-backed features sit inside the platform flow:

- **Fraud Detection** — each job posting is scored for risk before it goes live.
- **Hybrid Matching** — freelancers are ranked for jobs (and jobs for freelancers) using a blend of semantic similarity and business signals.
- **Proposal Generation** — freelancers can generate a cover letter draft from the job context.

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask 3.x |
| Database | PostgreSQL (via SQLAlchemy Core + psycopg2) |
| Frontend | Server-rendered Jinja2 templates, vanilla JS |
| AI — Fraud | TF-IDF cosine similarity + regex rule engine (scikit-learn) |
| AI — Matching | TF-IDF cosine similarity + weighted business signals (scikit-learn) |
| AI — Proposals | Template-based generation (3 styles) |
| Auth | Session-based with email verification codes (SMTP) |
| Email | SMTP via Gmail (configurable) |

---

## 3. Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL running locally
- A Gmail account (or other SMTP provider) for email delivery

### Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd escrowiq

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment
cp _env .env
# Edit .env with your database credentials and SMTP settings

# 4. Run the app (seeds demo data automatically)
python run.py
```

The server starts at `http://localhost:5000`.

`run.py` handles schema creation and demo data seeding on first run. You do not need to run migrations manually.

### Seeding AI Test Data (optional)

```bash
python seed_ai_test_data.py
```

This adds a dedicated client account and three freelancer profiles designed to exercise the fraud detection and hybrid matching systems. See `AI_TEST_CASES.md` for the exact scenarios.

---

## 4. Environment Variables

All variables live in `.env` in the project root.

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Flask session secret | *(required — set a strong value)* |
| `DATABASE_URL` | PostgreSQL connection string | *(required)* |
| `PORT` | Server port | `5000` |
| `SMTP_HOST` | SMTP server hostname | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USERNAME` | SMTP login username | *(required)* |
| `SMTP_PASSWORD` | SMTP login password / app password | *(required)* |
| `SMTP_FROM_EMAIL` | Sender address | *(required)* |
| `SMTP_USE_TLS` | Use STARTTLS | `true` |
| `SESSION_COOKIE_SECURE` | Require HTTPS for cookies | `false` (set `true` in production) |
| `ADMIN_EMAIL` | Admin login email | *(required)* |
| `ADMIN_PASSWORD` | Admin login password | *(required)* |
| `FOUNDER_ALERT_EMAILS` | Comma-separated emails for admin login alerts | *(optional)* |
| `AI_MODE` | AI fraud mode: `rules`, `hybrid`, or `model` | `hybrid` |
| `AI_FALLBACK_ENABLED` | Fall back to rule-based scoring if AI fails | `true` |

---

## 5. What Has Been Implemented

### User Management
- Registration with role selection (client / freelancer)
- Email verification via 6-digit code (SMTP delivery)
- Login / logout with session management
- Password reset via emailed code
- Profile editing (name, bio, skills)
- Role-based route access (client, freelancer, admin)
- CSRF token enforcement on all mutating API routes

### Job Lifecycle
- Clients post jobs with title, description, required skills, budget, and deadline
- Each job is fraud-scored at post time before saving
- Jobs display fraud level badge (Low / Medium / High) with reason breakdown
- Clients can delete open jobs
- Jobs page supports live search and risk-level filtering

### Proposal Lifecycle
- Freelancers submit proposals with cover letter, bid, and timeline
- Clients accept one proposal (remaining pending proposals auto-rejected atomically)
- Clients can manually reject individual proposals
- Notifications and emails sent to all affected parties on acceptance/rejection

### Escrow System
- Clients fund escrow for the accepted freelancer only (enforced server-side)
- Balance check before deposit
- Escrow deposit, release, and refund are all atomic transactions (no partial state)
- Escrow status visible on job detail page and dedicated escrow page
- Freelancers see funded escrow before they can submit work

### Work Submission and Review
- Freelancers submit work via delivery note, external URL, zip upload, or folder upload
- Folder uploads are packaged into a zip archive server-side
- Clients can approve (releases escrow), request changes (with written feedback), or file a complaint
- Change requests enforce a minimum feedback length and must stay within original scope

### Dispute and Complaint System
- Either party can file a complaint on a disputed job
- Complaint sets job and submission status to `disputed`
- Admin queue shows all open complaints with full context (job details, delivery, feedback)
- Admin can release escrow (to freelancer), refund escrow (to client), or close without payment change
- All resolutions trigger notifications and emails to both parties

### Notifications
- In-app notification bell with unread count
- Notifications generated for all major state changes
- Email delivery runs alongside in-app notifications
- Admin login events trigger alert emails to founder addresses

### Admin Panel
- Separate admin session (not a user row — credentials from environment variables)
- Admin login triggers founder alert emails with IP and user-agent
- Complaint queue with full job, delivery, and feedback context
- Download links for submitted work archives

---

## 6. AI Features — Implementation Detail

### 6.1 Fraud Detection

**File:** `fraud_detection.py`  
**Mode control:** `AI_MODE` environment variable

The fraud detector runs every time a client posts a job. It operates in three modes:

**`rules` mode** — regex pattern matching only. 14 patterns covering payment methods, urgency language, false claims, external redirects, and quality signals. Short descriptions and short titles add additional weight. Score capped at 10.

**`hybrid` mode (default)** — blends rule score and TF-IDF semantic similarity:
```
final_score = round(0.4 * rule_score + 0.6 * ai_score)
```

**`model` mode** — TF-IDF similarity score takes full precedence; rules act as a reasoning fallback only.

The TF-IDF model is trained on 30 fraud exemplars and 30 legitimate job exemplars at first call (lazy-loaded). It computes cosine similarity between the job text and both exemplar sets, normalizes the result to a 0–10 scale, and returns a confidence value.

Risk labels: `Low` (0–2), `Medium` (3–5), `High` (6–10).

All scoring components (rule score, AI score, final score, confidence, similarity values, fallback flag) are returned to the job detail page and stored in the `jobs` table.

### 6.2 Hybrid Freelancer Matching

**Files:** `app.py` (`hybrid_match_freelancers`, `match_jobs_for_freelancer`), `ml_matching.py`

**Composite score formula:**
```
hybrid_score = 0.55 * semantic_score
             + 0.25 * skill_overlap
             + 0.15 * rating_norm
             + 0.05 * exp_norm
```

Where:
- `semantic_score` — TF-IDF cosine similarity between job text and freelancer skills+bio (0–100), from `ml_matching.py`
- `skill_overlap` — percentage of required job skills covered by freelancer skills, with synonym expansion and partial substring matching
- `rating_norm` — freelancer rating normalized from 0–5 to 0–100
- `exp_norm` — review count log-scaled to 0–100 (50 reviews ≈ 100%)

Skill synonym map resolves common aliases (e.g. `js → javascript`, `k8s → kubernetes`, `postgres → postgresql`).

The job-for-freelancer direction (`match_jobs_for_freelancer`) uses a lighter formula:
```
hybrid_score = 0.65 * semantic_score + 0.35 * skill_overlap
```

Both the client job detail page ("AI Best Matches" sidebar) and the freelancer dashboard/jobs list show the hybrid score with a breakdown of semantic, skill, and rating components.

### 6.3 Proposal Generation

**File:** `app.py` (`generate_proposal`, `/api/ai/generate-proposal`)

Three template styles: **Professional**, **Direct**, and **Detailed**. Selection defaults to random but can be requested by style name.

Each template is populated with:
- Job title
- First 4 required skills
- First 4 freelancer skills
- First 20 words of job description as a summary
- Freelancer's display name

Generated proposals are returned to the UI for editing before submission — they are a starting point, not a final submission.

---

## 7. Implementation Status vs Developer Brief

The developer brief (`EscrowIQ_Developer_Implementation_Brief.docx`) defined priorities across three tiers. Here is the current status against each item.

### Fully Implemented (beyond the brief's baseline)

| Brief Item | Status |
|---|---|
| PostgreSQL (listed as P2 migration) | ✅ Already on PostgreSQL from the start |
| Hybrid fraud score blend (0.4 rule + 0.6 model) | ✅ Implemented exactly as specified |
| Semantic + business signal matching weights (0.55/0.25/0.15/0.05) | ✅ Implemented exactly as specified |
| `AI_MODE` and `AI_FALLBACK_ENABLED` feature flags | ✅ Implemented via `.env` |
| Deterministic fallback when AI fails | ✅ Implemented with `try/except` + flag check |
| Atomic transactions for escrow/payment state | ✅ All multi-step writes use `engine.begin()` |
| Role-based authorization on all major routes | ✅ Implemented |
| Email verification flow | ✅ Implemented |
| CSRF protection on API routes | ✅ Implemented |
| Fraud reasons stored per job for explainability | ✅ Stored in `fraud_reasons` JSON column |
| Work submission with file upload support | ✅ Zip and folder upload both supported |

### Partially Implemented

| Brief Item | Current State | Gap |
|---|---|---|
| AI service abstraction layer | AI logic lives in `fraud_detection.py` and `ml_matching.py` — separated from routes but not behind a formal service interface | No `services/ai/provider.py` abstraction with normalized output contract |
| Proposal generation (LLM-backed) | Template-based, 3 styles | No LLM integration yet; brief calls for LLM with guardrails and validation |
| API response schema consistency | Most endpoints consistent | Some edge-case fields not guaranteed across all error paths |

### Not Yet Implemented

| Brief Item | Priority in Brief |
|---|---|
| Automated test suite (auth, job, proposal, escrow flows) | P0 |
| Blueprint/domain modularization of `app.py` | P1 |
| `ai_inference_logs` table | P1 (AI lifecycle) |
| `ai_feedback` table | P1 (AI lifecycle) |
| Rate limiting | P2 |
| Async workers for background tasks | P2 |
| Structured logging and observability stack | P2 |
| WebSocket / SSE for real-time notifications | P2 |
| API versioning | P2 |
| CI/CD pipeline | P2 |
| Milestone-based escrow | P2 |

---

## 8. Known Gaps and Remaining Work

### P0 — Immediate

1. **No automated tests.** The escrow release, refund, and dispute resolution paths have no test coverage. Any refactor carries regression risk.
2. **`app.py` is monolithic.** Routes, DB access, business logic, and AI logic are all in one file (~1,400 lines). Refactoring into Flask Blueprints is the next structural priority.

### P1 — Short-term

3. **No AI inference logging.** Model outputs are not stored. There is no way to audit what the fraud detector or matcher returned for a given job without replaying the input.
4. **Proposal generation is template-only.** The brief calls for LLM-backed generation with a structured prompt, output validation, length bounds, and a template fallback.
5. **No service abstraction for AI.** The normalized output contract described in the brief (`source`, `version`, `score`, `label`, `reasons`, `latency_ms`) is not yet enforced uniformly.

### P2 — Production readiness

6. **No observability.** No structured logging, no error tracking, no performance metrics.
7. **No rate limiting.** Auth endpoints and AI endpoints are unprotected against abuse.
8. **`SESSION_COOKIE_SECURE` defaults to `false`.** Must be set to `true` before any HTTPS deployment.
9. **`SECRET_KEY` defaults to a hardcoded dev value** if not set. This will warn at startup but should be treated as a hard error before any production deployment.

---

## 9. File Structure

```
escrowiq/
├── app.py                  # Main Flask application — routes, DB, business logic, AI logic
├── fraud_detection.py      # TF-IDF fraud scorer + rule engine
├── ml_matching.py          # TF-IDF semantic freelancer matching
├── run.py                  # Startup script — schema init, demo data seeding, server
├── seed_ai_test_data.py    # Seeds AI-specific test users and jobs
├── requirements.txt        # Python dependencies
├── .env                    # Environment configuration (not committed)
├── AI_TEST_CASES.md        # Manual test scenarios for fraud and matching
│
├── 404.html                # Error page
├── 500.html                # Error page
├── base.html               # Base layout, navbar, toast, notification dropdown
├── index.html              # Landing page
├── login.html              # Sign in
├── register.html           # Account creation
├── verify_email.html       # Email verification
├── forgot_password.html    # Password reset
├── dashboard_client.html   # Client dashboard — job listings, post job modal
├── dashboard_freelancer.html # Freelancer dashboard — matched jobs, proposals
├── jobs.html               # Job browse/search page
├── job_detail.html         # Full job view — proposals, escrow, matching, work submission
├── escrow.html             # Escrow transaction list
├── profile.html            # Profile edit page
└── admin_complaints.html   # Admin complaint queue
```

---

## 10. Demo Accounts

All demo accounts use the password `demo123`.

### Clients

| Name | Email |
|---|---|
| Sarah Mitchell | sarah@demo.com |
| Ahmed Raza | ahmed@demo.com |
| Maya Chen | maya@demo.com |
| Daniel Brooks | daniel@demo.com |

### Freelancers

| Name | Email | Skills |
|---|---|---|
| Alex Morgan | alex@demo.com | Python, Django, Flask, FastAPI, PostgreSQL, Docker |
| Priya Nair | priya@demo.com | React, TypeScript, CSS, Tailwind, Figma, UI/UX |
| Omar Hassan | omar@demo.com | Node.js, React, Next.js, MongoDB, Python, AWS |
| Lena Park | lena@demo.com | Flutter, React Native, Firebase, Swift, Kotlin |
| Bilal Farooq | bilal@demo.com | Python, Pandas, SQL, Power BI, ETL, PostgreSQL |
| Sofia Almeida | sofia@demo.com | Webflow, SEO, Copywriting, Landing Pages, Analytics |

### Admin

| Email | Password |
|---|---|
| admin@example.com | 12345678 |

*(Set via `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`)*

### AI Test Accounts (after running `seed_ai_test_data.py`)

| Name | Email | Role |
|---|---|---|
| AI Test Client | ai_test_client@escrowiq.local | Client |
| Ayesha Khan | ayesha_ai@escrowiq.local | Freelancer |
| Bilal Ahmed | bilal_ai@escrowiq.local | Freelancer |
| Sara Noor | sara_ai@escrowiq.local | Freelancer |

---

*Last updated against codebase revision with hybrid matching, atomic escrow transactions, and TF-IDF fraud scoring.*