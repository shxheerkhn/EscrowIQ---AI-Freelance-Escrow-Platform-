#!/usr/bin/env python3
"""
EscrowIQ startup script.

Supports:
- DATABASE_URL-driven database setup
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, timedelta

# ── Load .env FIRST, before any app imports ──────────────────────────────────
# run.py lives in the same folder as .env, so we look there directly.
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH, "r", encoding="utf-8") as _env_file:
        for _raw_line in _env_file:
            _line = _raw_line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _val = _line.split("=", 1)
            _key = _key.strip()
            _val = _val.strip().strip('"').strip("'")
            if _key and _key not in os.environ:
                os.environ[_key] = _val
# ─────────────────────────────────────────────────────────────────────────────

from sqlalchemy import text
from werkzeug.security import generate_password_hash


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from app import get_engine, init_db


CLIENTS = [
    {
        "username": "sarah_mitchell",
        "full_name": "Sarah Mitchell",
        "email": "sarah@demo.com",
        "bio": "Product director at Northstar Commerce, focused on digital growth and customer experience.",
        "rating": 4.9,
        "reviews": 21,
        "balance": 8500.0,
        "company": "Northstar Commerce",
    },
    {
        "username": "ahmed_raza",
        "full_name": "Ahmed Raza",
        "email": "ahmed@demo.com",
        "bio": "Operations lead at Vertex Digital, hiring specialists for fast-moving client work.",
        "rating": 4.8,
        "reviews": 27,
        "balance": 6200.0,
        "company": "Vertex Digital",
    },
    {
        "username": "maya_chen",
        "full_name": "Maya Chen",
        "email": "maya@demo.com",
        "bio": "Founder building healthcare and productivity products for distributed teams.",
        "rating": 4.7,
        "reviews": 18,
        "balance": 9100.0,
        "company": "Clarity Labs",
    },
    {
        "username": "daniel_brooks",
        "full_name": "Daniel Brooks",
        "email": "daniel@demo.com",
        "bio": "Agency partner overseeing web, analytics, and automation projects.",
        "rating": 4.8,
        "reviews": 24,
        "balance": 7100.0,
        "company": "Harbor Studio",
    },
]

FREELANCERS = [
    {
        "username": "alex_dev",
        "full_name": "Alex Morgan",
        "email": "alex@demo.com",
        "skills": "Python, Django, Flask, FastAPI, REST API, PostgreSQL, Docker",
        "bio": "Backend engineer focused on scalable APIs, workflows, and cloud-ready platforms.",
        "rating": 4.9,
        "reviews": 28,
        "balance": 2200.0,
    },
    {
        "username": "priya_design",
        "full_name": "Priya Nair",
        "email": "priya@demo.com",
        "skills": "React, JavaScript, TypeScript, CSS, Tailwind, Figma, UI/UX",
        "bio": "Frontend engineer and product designer building clean, polished interfaces.",
        "rating": 4.8,
        "reviews": 22,
        "balance": 1800.0,
    },
    {
        "username": "omar_fullstack",
        "full_name": "Omar Hassan",
        "email": "omar@demo.com",
        "skills": "Node.js, React, Next.js, MongoDB, Express, Python, AWS",
        "bio": "Full-stack developer with strong delivery habits across product, infra, and ops.",
        "rating": 4.8,
        "reviews": 34,
        "balance": 3100.0,
    },
    {
        "username": "lena_mobile",
        "full_name": "Lena Park",
        "email": "lena@demo.com",
        "skills": "Flutter, React Native, Firebase, Swift, Kotlin, Mobile UX",
        "bio": "Mobile app specialist for consumer products, onboarding flows, and subscriptions.",
        "rating": 4.6,
        "reviews": 16,
        "balance": 900.0,
    },
    {
        "username": "bilal_data",
        "full_name": "Bilal Farooq",
        "email": "bilal@demo.com",
        "skills": "Python, Pandas, SQL, Power BI, ETL, Data Visualization, PostgreSQL",
        "bio": "Analytics engineer helping teams turn messy data into clear operational insight.",
        "rating": 4.7,
        "reviews": 17,
        "balance": 1400.0,
    },
    {
        "username": "sofia_growth",
        "full_name": "Sofia Almeida",
        "email": "sofia@demo.com",
        "skills": "Webflow, SEO, Copywriting, Landing Pages, Analytics, CRO",
        "bio": "Growth-focused freelancer combining content, conversion strategy, and execution.",
        "rating": 4.7,
        "reviews": 20,
        "balance": 1600.0,
    },
]

JOB_BLUEPRINTS = [
    {
        "title": "Customer Portal Modernization",
        "skills": ["React", "TypeScript", "REST API", "PostgreSQL", "Authentication"],
        "budget": (1400, 2600),
        "days": (12, 35),
        "summary": "Modernize an existing client portal with role-based access, improved navigation, and cleaner account workflows.",
        "deliverables": [
            "responsive dashboard screens",
            "secure authentication flows",
            "account settings and permissions",
            "release-ready QA notes",
        ],
    },
    {
        "title": "Operations Analytics Dashboard",
        "skills": ["React", "Chart.js", "Python", "SQL", "PostgreSQL"],
        "budget": (1000, 2200),
        "days": (10, 28),
        "summary": "Build an internal analytics dashboard for operations leaders with live metrics and exportable reports.",
        "deliverables": [
            "filterable KPI views",
            "CSV export support",
            "trend and cohort charts",
            "documentation for handoff",
        ],
    },
    {
        "title": "Freelance Marketplace Backend API",
        "skills": ["Python", "Flask", "REST API", "PostgreSQL", "Docker"],
        "budget": (1200, 2800),
        "days": (14, 32),
        "summary": "Design and implement a production-style API for accounts, jobs, messaging, and transaction flows.",
        "deliverables": [
            "database schema design",
            "authenticated CRUD endpoints",
            "error handling and validation",
            "deployment notes",
        ],
    },
    {
        "title": "Mobile Onboarding Flow Refresh",
        "skills": ["React Native", "Figma", "JavaScript", "Firebase", "Mobile UX"],
        "budget": (900, 1800),
        "days": (8, 24),
        "summary": "Refresh onboarding for a consumer mobile app to improve activation and early retention.",
        "deliverables": [
            "updated screen designs",
            "implemented onboarding flow",
            "tracking events",
            "handoff assets",
        ],
    },
    {
        "title": "Lead Capture Website Rebuild",
        "skills": ["Next.js", "SEO", "TypeScript", "CMS", "Performance"],
        "budget": (1100, 2400),
        "days": (10, 30),
        "summary": "Rebuild a marketing site for stronger performance, clearer messaging, and better lead conversion.",
        "deliverables": [
            "homepage and service pages",
            "CMS-driven content sections",
            "technical SEO improvements",
            "analytics events",
        ],
    },
    {
        "title": "Workflow Automation for Support Team",
        "skills": ["Python", "Zapier", "APIs", "Automation", "Google Sheets"],
        "budget": (700, 1600),
        "days": (7, 20),
        "summary": "Automate repetitive support tasks across forms, spreadsheets, CRM updates, and notifications.",
        "deliverables": [
            "automation map",
            "integrated workflows",
            "error logging",
            "operator guide",
        ],
    },
    {
        "title": "Data Cleanup and Reporting Pipeline",
        "skills": ["Python", "ETL", "SQL", "Pandas", "Power BI"],
        "budget": (950, 2100),
        "days": (9, 27),
        "summary": "Create a repeatable reporting pipeline for multi-source operations and sales data.",
        "deliverables": [
            "data normalization logic",
            "scheduled refresh pipeline",
            "executive dashboard",
            "quality checks",
        ],
    },
    {
        "title": "Subscription Billing Admin Panel",
        "skills": ["Django", "React", "Stripe API", "PostgreSQL", "Admin UX"],
        "budget": (1500, 3200),
        "days": (15, 36),
        "summary": "Build an internal billing admin area for managing plans, failed payments, credits, and customer accounts.",
        "deliverables": [
            "billing overview panels",
            "refund and credit actions",
            "audit history",
            "permission-aware controls",
        ],
    },
]


def random_job_description(client, blueprint, rng):
    deliverables = ", ".join(blueprint["deliverables"][:-1]) + f", and {blueprint['deliverables'][-1]}"
    priorities = [
        "clean code structure",
        "clear stakeholder communication",
        "production-ready QA",
        "documentation the internal team can maintain",
        "fast but reliable delivery",
        "a polished user experience",
    ]
    priority_a, priority_b = rng.sample(priorities, 2)
    return (
        f"{client['company']} is hiring for a {blueprint['title'].lower()} initiative. "
        f"We need someone who can {blueprint['summary'].lower()} "
        f"The ideal freelancer should be comfortable owning delivery from implementation through review. "
        f"Expected deliverables include {deliverables}. "
        f"We care about {priority_a} and {priority_b}, and we want someone who can work independently while giving concise updates. "
        f"This project should feel production-ready rather than prototype-level."
    )


def build_dynamic_jobs(client_ids):
    rng = random.Random()
    jobs = []
    today = date.today()

    for client in CLIENTS:
        client_id = client_ids[client["username"]]
        blueprints = JOB_BLUEPRINTS[:]
        rng.shuffle(blueprints)

        for blueprint in blueprints[:5]:
            min_budget, max_budget = blueprint["budget"]
            min_days, max_days = blueprint["days"]
            deadline = today + timedelta(days=rng.randint(min_days, max_days))
            title_suffixes = [
                "for Growth Team",
                "for Internal Ops",
                "for Product Launch",
                "for Client Delivery",
                "for Q3 Rollout",
            ]
            title = f"{blueprint['title']} {rng.choice(title_suffixes)}"
            description = random_job_description(client, blueprint, rng)
            skills = ", ".join(blueprint["skills"])
            budget = float(rng.randrange(min_budget, max_budget + 100, 100))

            jobs.append(
                {
                    "client_id": client_id,
                    "title": title,
                    "description": description,
                    "skills_required": skills,
                    "budget": budget,
                    "deadline": deadline.isoformat(),
                    "status": "open",
                    "fraud_score": 0,
                    "fraud_level": "Low",
                    "fraud_reasons": "[]",
                }
            )

    jobs.sort(key=lambda item: (item["deadline"], item["budget"]))
    return jobs


def sync_demo_user(conn, payload, role):
    existing = conn.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": payload["email"]},
    ).scalar_one_or_none()

    values = {
        "username": payload["username"],
        "full_name": payload["full_name"],
        "email": payload["email"],
        "password": generate_password_hash("demo123"),
        "skills": payload.get("skills", ""),
        "bio": payload["bio"],
        "rating": payload["rating"],
        "reviews": payload["reviews"],
        "balance": payload["balance"],
        "role": role,
        "email_verified": True,
    }

    if existing:
        conn.execute(
            text(
                """
                UPDATE users
                SET username = :username,
                    full_name = :full_name,
                    password = :password,
                    role = :role,
                    skills = :skills,
                    bio = :bio,
                    rating = :rating,
                    total_reviews = :reviews,
                    balance = :balance,
                    email_verified = :email_verified
                WHERE email = :email
                """
            ),
            values,
        )
        return existing

    return conn.execute(
        text(
            """
            INSERT INTO users (username, full_name, email, password, role, skills, bio, rating, total_reviews, balance, email_verified)
            VALUES (:username, :full_name, :email, :password, :role, :skills, :bio, :rating, :reviews, :balance, :email_verified)
            RETURNING id
            """
        ),
        values,
    ).scalar_one()


def seed_demo_data():
    engine = get_engine()

    with engine.begin() as conn:
        print("  Seeding professional demo data...")

        for client in CLIENTS:
            sync_demo_user(conn, client, "client")

        for freelancer in FREELANCERS:
            sync_demo_user(conn, freelancer, "freelancer")

        client_id_rows = conn.execute(
            text("SELECT id, username FROM users WHERE role='client'")
        ).mappings()
        client_ids = {row["username"]: row["id"] for row in client_id_rows}

        jobs = build_dynamic_jobs(client_ids)
        existing_titles = {
            row["title"]
            for row in conn.execute(text("SELECT title FROM jobs")).mappings().all()
        }
        added_jobs = 0
        for job in jobs:
            if job["title"] in existing_titles:
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO jobs (
                        client_id, title, description, skills_required, budget,
                        deadline, status, fraud_score, fraud_level, fraud_reasons
                    )
                    VALUES (
                        :client_id, :title, :description, :skills_required, :budget,
                        :deadline, :status, :fraud_score, :fraud_level, :fraud_reasons
                    )
                    """
                ),
                job,
            )
            added_jobs += 1

        welcome_names = [person["full_name"] for person in CLIENTS] + [person["full_name"] for person in FREELANCERS]
        user_rows = conn.execute(text("SELECT id, full_name FROM users")).mappings().all()
        user_map = {row["full_name"]: row["id"] for row in user_rows}
        for name in welcome_names:
            already_has_welcome = conn.execute(
                text("SELECT COUNT(*) FROM notifications WHERE user_id = :user_id AND message = :message"),
                {
                    "user_id": user_map[name],
                    "message": f"Welcome to EscrowIQ, {name}. Your profile is ready.",
                },
            ).scalar_one()
            if already_has_welcome:
                continue

            conn.execute(
                text("INSERT INTO notifications (user_id, message, type) VALUES (:user_id, :message, 'success')"),
                {
                    "user_id": user_map[name],
                    "message": f"Welcome to EscrowIQ, {name}. Your profile is ready.",
                },
            )

        total_users = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
        total_jobs = conn.execute(text("SELECT COUNT(*) FROM jobs")).scalar_one()
        print(f"  Demo users synced. Added {added_jobs} new dynamic job postings.")
        print(f"  Database now has {total_users} users and {total_jobs} jobs.")
        print()
        print("  Demo logins")
        print("  CLIENTS")
        for client in CLIENTS:
            print(f"    {client['full_name']:<18} {client['email']:<24} demo123")
        print("  FREELANCERS")
        for freelancer in FREELANCERS:
            print(f"    {freelancer['full_name']:<18} {freelancer['email']:<24} demo123")
        print()


def ensure_requirements_file():
    requirements_path = os.path.join(CURRENT_DIR, "requirements.txt")
    if os.path.exists(requirements_path):
        return

    with open(requirements_path, "w", encoding="utf-8") as handle:
        handle.write("Flask>=3.1\n")
        handle.write("SQLAlchemy>=2.0\n")
        handle.write("psycopg2-binary>=2.9\n")
        handle.write("Werkzeug>=3.1\n")
        handle.write("scikit-learn>=1.5\n")


if __name__ == "__main__":
    print()
    print("  EscrowIQ")
    print("  Starting application...")
    print()

    ensure_requirements_file()

    # Show what DB we are connecting to so the user can spot misconfigs fast
    db_url = os.environ.get("DATABASE_URL", "NOT SET")
    # Mask password for display
    try:
        from urllib.parse import urlparse
        _parsed = urlparse(db_url)
        _safe_url = db_url.replace(_parsed.password, "****") if _parsed.password else db_url
    except Exception:
        _safe_url = db_url
    print(f"  Connecting to: {_safe_url}")
    print("  (if this hangs, PostgreSQL is not reachable at that address)")
    print()

    try:
        init_db()
    except Exception as exc:
        print()
        print("  ERROR: Could not connect to PostgreSQL.")
        print(f"  Detail: {exc}")
        print()
        print("  Things to check:")
        print("  1. PostgreSQL is running (open pgAdmin or run: pg_isready)")
        print("  2. The database 'freelance_pro' exists")
        print("  3. DATABASE_URL in your .env matches your local credentials")
        print(f"  4. Your .env is at: {_ENV_PATH}")
        print()
        sys.exit(1)

    print(f"  Database engine: {get_engine().dialect.name}")
    seed_demo_data()

    from app import app

    port = int(os.environ.get("PORT", 5000))
    print(f"  Server URL: http://localhost:{port}")
    print("  Press CTRL+C to stop.")
    print()
    app.run(debug=False, port=port, host="0.0.0.0")