# FreeLancer Pro — AI-Powered Freelance Escrow Platform

> **ESCROWQI WHATEVER**  
> Tech Stack: Python (Flask) · HTML · CSS · JavaScript · SQLite

---

## Overview

ESCROW QI is a full-stack web application that simulates a real-world freelance marketplace. It addresses key problems in the freelancing ecosystem — payment trust, fraud, inefficient hiring — through an escrow system and rule-based AI features.

---

## Features

| Feature | Description |
|---|---|
| **User Auth** | Register/Login with role-based access (Client / Freelancer) |
| **Job Management** | Post, browse, search, and filter job listings |
| **Proposal System** | Freelancers apply with bids, timelines, and cover letters |
| **AI Fraud Detection** | Rule-based analysis assigns Low/Medium/High risk to every job |
| **AI Smart Matching** | Skill-based algorithm matches top freelancers to each job |
| **AI Proposal Generator** | Auto-generates personalized proposal text from job details |
| **Escrow Simulation** | Clients lock funds → work happens → release or refund |
| **Notifications** | Real-time system messages for all key events |
| **Responsive UI** | Works on desktop and mobile |

---

## Quick Start

### Requirements
- Python 3.8+
- Flask (pre-installed in most environments)

### Run

```bash
python3 run.py
```

Open **http://localhost:5000** in your browser.

### Demo Accounts (auto-created on first run)

| Role | Email | Password |
|---|---|---|
| Client | sarah@demo.com | demo123 |
| Client | ahmed@demo.com | demo123 |
| Freelancer | alex@demo.com | demo123 |
| Freelancer | priya@demo.com | demo123 |
| Freelancer | omar@demo.com | demo123 |
| Freelancer | lena@demo.com | demo123 |

---

## Project Structure

```
freelance_platform/
├── app.py              # Flask app — all routes, API, AI engine, DB logic
├── run.py              # Startup script with demo data seeding
├── freelance.db        # SQLite database (auto-created)
├── templates/
│   ├── base.html           # Shared layout, navbar, toast, notifications
│   ├── index.html          # Landing page
│   ├── register.html       # Registration with role picker
│   ├── login.html          # Login page
│   ├── dashboard_client.html    # Client dashboard + post job modal
│   ├── dashboard_freelancer.html # Freelancer dashboard + proposals
│   ├── job_detail.html     # Job detail, apply, proposals, escrow
│   ├── jobs.html           # Browse + search + filter jobs
│   ├── profile.html        # User profile editor
│   └── escrow.html         # Escrow transaction history
└── README.md
```

---

## AI Features Explained

### 1. Fraud Detection
Every job posting is scanned by a rule-based engine that checks for:
- Urgency language ("urgent", "ASAP")
- Suspicious payment methods ("bitcoin", "wire transfer")
- Unrealistic guarantees ("100%", "guaranteed")
- Get-rich-quick language
- Very short descriptions (low effort)
- Suspicious external links
- Sensitive info requests

Scores 0–3 = **Low**, 4–7 = **Medium**, 8+ = **High** risk.

### 2. Smart Freelancer Matching
Given a job's required skills, the engine:
1. Compares them against every freelancer's skill list
2. Calculates a % overlap score
3. Returns the top 5 matches ranked by skill match + rating

### 3. Proposal Generator
Takes the job title, description, required skills, and the freelancer's name/skills, then fills a professional proposal template with context-specific content.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | /api/register | Create account |
| POST | /api/login | Sign in |
| POST | /api/logout | Sign out |
| POST | /api/jobs | Post a new job |
| DELETE | /api/jobs/:id | Delete a job |
| POST | /api/proposals | Submit a proposal |
| POST | /api/proposals/:id/accept | Accept a proposal |
| POST | /api/proposals/:id/reject | Reject a proposal |
| POST | /api/escrow/deposit | Lock payment in escrow |
| POST | /api/escrow/:id/release | Release payment to freelancer |
| POST | /api/escrow/:id/refund | Refund payment to client |
| POST | /api/ai/generate-proposal | AI-generate a proposal |
| GET | /api/ai/match-freelancers/:id | Get AI-matched freelancers |
| GET | /api/stats | Dashboard stats |
| GET | /api/notifications | Get notifications |
| POST | /api/notifications/read | Mark all as read |
| PUT | /api/profile | Update profile |

---

## Database Schema

- **users** — id, username, email, password (hashed), role, skills, bio, rating, balance
- **jobs** — id, client_id, title, description, skills, budget, deadline, status, fraud_score, fraud_level
- **proposals** — id, job_id, freelancer_id, cover_letter, bid_amount, timeline, status
- **escrow** — id, job_id, client_id, freelancer_id, amount, status, released_at
- **notifications** — id, user_id, message, type, is_read

---

*Built for the Web Programming Course — demonstrates full-stack development with Python, REST APIs, SQLite, and frontend JavaScript.*
