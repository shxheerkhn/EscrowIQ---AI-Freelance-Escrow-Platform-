from __future__ import annotations

import json

from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app import analyze_fraud, get_engine, init_db


CLIENT = {
    "username": "ai_test_client",
    "full_name": "AI Test Client",
    "email": "ai_test_client@escrowiq.local",
    "role": "client",
    "skills": "",
    "bio": "Internal account for fraud and matching test scenarios.",
    "rating": 4.9,
    "total_reviews": 8,
    "balance": 5000.0,
}

FREELANCERS = [
    {
        "username": "ayesha_ai",
        "full_name": "Ayesha Khan",
        "email": "ayesha_ai@escrowiq.local",
        "role": "freelancer",
        "skills": "Python, Flask, PostgreSQL, REST API, Dashboards",
        "bio": "Backend engineer focused on Flask apps, analytics dashboards, reporting workflows, API design, and production database work.",
        "rating": 4.8,
        "total_reviews": 24,
        "balance": 1200.0,
    },
    {
        "username": "bilal_ai",
        "full_name": "Bilal Ahmed",
        "email": "bilal_ai@escrowiq.local",
        "role": "freelancer",
        "skills": "React, UI/UX, JavaScript, CSS",
        "bio": "Frontend specialist for polished interfaces, design systems, and responsive dashboards.",
        "rating": 4.6,
        "total_reviews": 18,
        "balance": 1100.0,
    },
    {
        "username": "sara_ai",
        "full_name": "Sara Noor",
        "email": "sara_ai@escrowiq.local",
        "role": "freelancer",
        "skills": "Machine Learning, NLP, Data Science, Python",
        "bio": "I build semantic search, text similarity, recommendation systems, and model-backed ranking flows for marketplaces.",
        "rating": 4.7,
        "total_reviews": 12,
        "balance": 1150.0,
    },
]

JOBS = [
    {
        "title": "URGENT crypto payment assistant needed today only",
        "description": "We need someone immediately for a simple task. Payment will be in USDT or Bitcoin. Click here and go to our external site to get started right now. No contract needed, trust me. This only takes a few minutes and can double your money fast.",
        "skills_required": "Data Entry, Crypto, Admin Support",
        "budget": 200.0,
        "deadline": "2030-01-15",
    },
    {
        "title": "Quick outreach help for lead list cleanup",
        "description": "Need help ASAP cleaning a sales spreadsheet and contacting prospects. This is a simple task and we want someone who can start immediately. We may move part of the conversation off-platform if things go well.",
        "skills_required": "Excel, Lead Generation, Communication",
        "budget": 350.0,
        "deadline": "2030-01-20",
    },
    {
        "title": "Escrow marketplace analytics dashboard",
        "description": "Build a reporting dashboard for a freelance escrow platform with Flask, PostgreSQL, charts, filters, authentication, and API endpoints for summary metrics.",
        "skills_required": "Python, Flask, PostgreSQL, REST API",
        "budget": 1800.0,
        "deadline": "2030-02-01",
    },
    {
        "title": "Recommendation and ranking improvements for hiring marketplace",
        "description": "We want to improve how freelancers are ranked for jobs using semantic similarity, profile understanding, text scoring, and recommendation logic.",
        "skills_required": "Python, Machine Learning, Ranking Systems, NLP",
        "budget": 2200.0,
        "deadline": "2030-02-10",
    },
]


def upsert_user(conn, payload):
    existing = conn.execute(
        text("SELECT id FROM users WHERE email=:email"),
        {"email": payload["email"]},
    ).scalar_one_or_none()

    values = {
        "username": payload["username"],
        "full_name": payload["full_name"],
        "email": payload["email"],
        "password": generate_password_hash("demo123"),
        "role": payload["role"],
        "skills": payload["skills"],
        "bio": payload["bio"],
        "rating": payload["rating"],
        "reviews": payload["total_reviews"],
        "balance": payload["balance"],
        "email_verified": True,
    }

    if existing:
        conn.execute(
            text(
                """
                UPDATE users
                SET username=:username,
                    full_name=:full_name,
                    password=:password,
                    role=:role,
                    skills=:skills,
                    bio=:bio,
                    rating=:rating,
                    total_reviews=:reviews,
                    balance=:balance,
                    email_verified=:email_verified,
                    email_verified_at=CURRENT_TIMESTAMP
                WHERE email=:email
                """
            ),
            values,
        )
        return existing

    return conn.execute(
        text(
            """
            INSERT INTO users (username, full_name, email, password, role, skills, bio, rating, total_reviews, balance, email_verified, email_verified_at)
            VALUES (:username, :full_name, :email, :password, :role, :skills, :bio, :rating, :reviews, :balance, :email_verified, CURRENT_TIMESTAMP)
            RETURNING id
            """
        ),
        values,
    ).scalar_one()


def upsert_job(conn, client_id, payload):
    fraud_score, fraud_level, fraud_reasons, _categories = analyze_fraud(payload["title"], payload["description"])
    existing = conn.execute(
        text("SELECT id FROM jobs WHERE client_id=:client_id AND title=:title"),
        {"client_id": client_id, "title": payload["title"]},
    ).scalar_one_or_none()

    values = {
        "client_id": client_id,
        "title": payload["title"],
        "description": payload["description"],
        "skills_required": payload["skills_required"],
        "budget": payload["budget"],
        "deadline": payload["deadline"],
        "status": "open",
        "fraud_score": fraud_score,
        "fraud_level": fraud_level,
        "fraud_reasons": json.dumps(fraud_reasons),
    }

    if existing:
        conn.execute(
            text(
                """
                UPDATE jobs
                SET description=:description,
                    skills_required=:skills_required,
                    budget=:budget,
                    deadline=:deadline,
                    status=:status,
                    fraud_score=:fraud_score,
                    fraud_level=:fraud_level,
                    fraud_reasons=:fraud_reasons
                WHERE id=:existing_id
                """
            ),
            {**values, "existing_id": existing},
        )
        return existing

    return conn.execute(
        text(
            """
            INSERT INTO jobs (client_id, title, description, skills_required, budget, deadline, status, fraud_score, fraud_level, fraud_reasons)
            VALUES (:client_id, :title, :description, :skills_required, :budget, :deadline, :status, :fraud_score, :fraud_level, :fraud_reasons)
            RETURNING id
            """
        ),
        values,
    ).scalar_one()


def main():
    init_db()
    engine = get_engine()

    with engine.begin() as conn:
        client_id = upsert_user(conn, CLIENT)
        for freelancer in FREELANCERS:
            upsert_user(conn, freelancer)
        for job in JOBS:
            upsert_job(conn, client_id, job)

    print("Seeded AI test data.")
    print("Client login: ai_test_client@escrowiq.local / demo123")
    print("Freelancers: ayesha_ai@escrowiq.local, bilal_ai@escrowiq.local, sara_ai@escrowiq.local / demo123")


if __name__ == "__main__":
    main()
