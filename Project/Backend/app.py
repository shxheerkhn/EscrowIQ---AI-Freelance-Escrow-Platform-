"""
FreeLancer Pro
Backend: Flask + SQLAlchemy Core with PostgreSQL
"""
from __future__ import annotations

import json
import os
import random
import re
import secrets
import smtplib
import ssl
import zipfile
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from io import BytesIO

from flask import Flask, g, jsonify, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ML matching module — TF-IDF semantic matching (addition, not replacement)
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fraud_detection import analyze_fraud_ai, fraud_ai_mode, fraud_fallback_enabled, fraud_level_from_score
from ml_matching import ml_match_freelancers


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(BASE_DIR, "Backend")
TEMPLATE_DIR = os.path.join(BASE_DIR, "Frontend", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "Frontend", "static")
UPLOADS_DIR = os.path.join(BACKEND_DIR, "uploads")
SUBMISSIONS_DIR = os.path.join(UPLOADS_DIR, "submissions")

# ML matching module — TF-IDF semantic matching (addition, not replacement of existing matcher)
def load_local_env():
    # Search for .env in multiple candidate locations so it works whether
    # app.py is imported directly or via run.py from a different directory.
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),  # same dir as app.py
        os.path.join(os.getcwd(), ".env"),                                  # current working directory
        os.path.join(BASE_DIR, ".env"),                                     # legacy parent dir
    ]
    for env_path in candidates:
        if not os.path.exists(env_path):
            continue
        with open(env_path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        break  # stop after first .env found


load_local_env()

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    import warnings
    _secret = "dev-secret-key-change-in-production"
    warnings.warn(
        "SECRET_KEY is not set in your .env file. Using an insecure default. "
        "Set SECRET_KEY in your .env before deploying.",
        stacklevel=2,
    )
app.secret_key = _secret
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

_engine = None
_schema_ready = False


def admin_email():
    return os.environ.get("ADMIN_EMAIL", "").strip().lower()


def admin_password():
    return os.environ.get("ADMIN_PASSWORD", "")


def is_admin_session():
    return session.get("is_admin") is True


def founder_alert_emails():
    raw_value = os.environ.get("FOUNDER_ALERT_EMAILS", "").strip()
    if not raw_value:
        return []
    return [email.strip().lower() for email in raw_value.split(",") if email.strip()]


def get_database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set. PostgreSQL is required.")
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            future=True,
            connect_args={"connect_timeout": 5},  # fail in 5s instead of hanging forever
        )
    return _engine


def is_postgres():
    return True  # PostgreSQL only


def ensure_schema_ready():
    global _schema_ready
    if not _schema_ready:
        os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
        init_db()
        _schema_ready = True


def prepare_query(query, args=None):
    if args is None:
        return query, {}
    if isinstance(args, dict):
        return query, args

    values = list(args)
    counter = 0

    def replace_placeholder(_match):
        nonlocal counter
        token = f"p{counter}"
        counter += 1
        return f":{token}"

    converted = re.sub(r"\?", replace_placeholder, query)
    if counter != len(values):
        raise ValueError("Mismatch between placeholders and query arguments")
    return converted, {f"p{i}": value for i, value in enumerate(values)}


def get_db():
    ensure_schema_ready()
    conn = getattr(g, "_database", None)
    if conn is None:
        conn = g._database = get_engine().connect()
    return conn


@app.teardown_appcontext
def close_db(_exc):
    conn = getattr(g, "_database", None)
    if conn is not None:
        conn.close()


def query_db(query, args=None, one=False):
    statement, params = prepare_query(query, args)
    result = get_db().execute(text(statement), params)
    rows = [dict(row) for row in result.mappings().all()]
    return (rows[0] if rows else None) if one else rows


def mutate_db(query, args=None):
    statement, params = prepare_query(query, args)
    conn = get_db()
    result = conn.execute(text(statement), params)

    returned_id = None
    if result.returns_rows:
        row = result.first()
        if row is not None:
            returned_id = row[0]
    elif getattr(result, "lastrowid", None) is not None:
        returned_id = result.lastrowid

    conn.commit()
    return returned_id


def init_db():
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    username VARCHAR(30) UNIQUE NOT NULL,
                    full_name VARCHAR(120) DEFAULT '',
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    email_verified BOOLEAN DEFAULT FALSE,
                    email_verified_at TIMESTAMP,
                    role VARCHAR(20) NOT NULL CHECK (role IN ('client', 'freelancer')),
                    skills TEXT DEFAULT '',
                    bio TEXT DEFAULT '',
                    rating DOUBLE PRECISION DEFAULT 0.0,
                    total_reviews INTEGER DEFAULT 0,
                    balance DOUBLE PRECISION DEFAULT 1000.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    client_id INTEGER NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    skills_required TEXT NOT NULL,
                    budget DOUBLE PRECISION NOT NULL,
                    deadline TEXT NOT NULL,
                    status VARCHAR(30) DEFAULT 'open',
                    fraud_score INTEGER DEFAULT 0,
                    fraud_level VARCHAR(20) DEFAULT 'Low',
                    fraud_reasons TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    freelancer_id INTEGER NOT NULL REFERENCES users(id),
                    cover_letter TEXT NOT NULL,
                    bid_amount DOUBLE PRECISION NOT NULL,
                    timeline TEXT NOT NULL,
                    status VARCHAR(30) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_id, freelancer_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS escrow (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    client_id INTEGER NOT NULL REFERENCES users(id),
                    freelancer_id INTEGER REFERENCES users(id),
                    amount DOUBLE PRECISION NOT NULL,
                    status VARCHAR(30) DEFAULT 'held',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    released_at TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    message TEXT NOT NULL,
                    action_url TEXT DEFAULT '',
                    type VARCHAR(30) DEFAULT 'info',
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS work_submissions (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    freelancer_id INTEGER NOT NULL REFERENCES users(id),
                    escrow_id INTEGER REFERENCES escrow(id),
                    delivery_message TEXT NOT NULL,
                    delivery_url TEXT DEFAULT '',
                    upload_archive_name TEXT DEFAULT '',
                    upload_archive_path TEXT DEFAULT '',
                    status VARCHAR(30) DEFAULT 'submitted',
                    client_feedback TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS complaints (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    escrow_id INTEGER REFERENCES escrow(id),
                    submission_id INTEGER REFERENCES work_submissions(id),
                    complainant_id INTEGER REFERENCES users(id),
                    against_user_id INTEGER REFERENCES users(id),
                    message TEXT NOT NULL,
                    status VARCHAR(40) DEFAULT 'open',
                    admin_notes TEXT DEFAULT '',
                    resolution_action TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS email_codes (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    email VARCHAR(255) NOT NULL,
                    purpose VARCHAR(50) NOT NULL,
                    code VARCHAR(6) NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    consumed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    sender_id INTEGER NOT NULL REFERENCES users(id),
                    recipient_id INTEGER NOT NULL REFERENCES users(id),
                    content TEXT NOT NULL,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120) DEFAULT ''"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP"))
        conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_url TEXT DEFAULT ''"))
        conn.execute(text("ALTER TABLE work_submissions ADD COLUMN IF NOT EXISTS upload_archive_name TEXT DEFAULT ''"))
        conn.execute(text("ALTER TABLE work_submissions ADD COLUMN IF NOT EXISTS upload_archive_path TEXT DEFAULT ''"))

        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_client ON jobs(client_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_proposals_job ON proposals(job_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_proposals_fl ON proposals(freelancer_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_work_submissions_job ON work_submissions(job_id, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notifs_user ON notifications(user_id, is_read)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_email_codes_lookup ON email_codes(email, purpose, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_messages_job_created ON messages(job_id, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_messages_recipient_unread ON messages(recipient_id, is_read, created_at DESC)"))


# ══════════════════════════════════════════════════════════════
#  AI ENGINE — EscrowIQ Intelligence Module
#  1. Fraud Detection   — analyzes job postings for risk signals
#  2. Smart Matching    — weighted skill + rating + experience scoring
#  3. Proposal Generator — context-aware cover letter builder
# ══════════════════════════════════════════════════════════════

FRAUD_RULES = [
    (r"\b(bitcoin|crypto|cryptocurrency|ethereum|usdt)\b", 5, "Payment", "Cryptocurrency payment method requested"),
    (r"\b(western union|wire transfer|money order|zelle)\b", 4, "Payment", "Untraceable payment method mentioned"),
    (r"\b(bank account|routing number|ssn|social security)\b", 5, "Personal", "Sensitive financial information requested"),
    (r"\b(urgent|asap|immediately|right now|today only)\b", 2, "Urgency", "Artificial urgency or pressure language"),
    (r"\b(limited time|expires soon|act now|last chance)\b", 2, "Urgency", "Scarcity manipulation tactics"),
    (r"\b(guaranteed|100%|risk.?free|no experience needed)\b", 2, "False Claims", "Unrealistic or misleading guarantees"),
    (r"\b(get rich|easy money|passive income|make money fast)\b", 3, "False Claims", "Get-rich-quick language detected"),
    (r"\b(double your|triple your|10x your)\b", 3, "False Claims", "Unrealistic financial multiplier claims"),
    (r"\b(click here|visit link|go to|external site|dm me)\b", 3, "External", "Suspicious redirection away from platform"),
    (r"https?://(?!escrow)", 2, "External", "External URL embedded in posting"),
    (r"(.)\1{4,}", 1, "Quality", "Repetitive characters suggest spam"),
    (r"[A-Z]{8,}", 1, "Quality", "Excessive use of capital letters"),
    (r"\b(simple task|easy job|just need|only takes)\b", 1, "Scope", "Vague or minimized job scope"),
    (r"\b(no contract|no nda|trust me|informal)\b", 2, "Scope", "Attempts to bypass formal agreements"),
]


def analyze_fraud_rules(title, description):
    raw_text = f"{title} {description}"
    text_blob = raw_text.lower()
    raw_score = 0
    reasons = []
    categories = {}

    for pattern, weight, category, reason in FRAUD_RULES:
        target = raw_text if pattern == r"[A-Z]{8,}" else text_blob
        if re.search(pattern, target):
            raw_score += weight
            reasons.append({"flag": reason, "category": category, "weight": weight, "source": "rules"})
            categories[category] = categories.get(category, 0) + weight

    word_count = len((description or "").split())
    if word_count < 15:
        raw_score += 3
        reasons.append({"flag": "Extremely short description (under 15 words)", "category": "Quality", "weight": 3, "source": "rules"})
    elif word_count < 30:
        raw_score += 1
        reasons.append({"flag": "Short description with limited job detail", "category": "Quality", "weight": 1, "source": "rules"})

    if len((title or "").split()) < 3:
        raw_score += 1
        reasons.append({"flag": "Very short job title", "category": "Quality", "weight": 1, "source": "rules"})

    score = min(raw_score, 10)
    return {
        "score": score,
        "label": fraud_level_from_score(score),
        "reasons": reasons,
        "categories": categories,
    }


def analyze_fraud_details(title, description):
    rule_result = analyze_fraud_rules(title, description)
    mode = fraud_ai_mode()

    if mode == "rules":
        return {
            "score": rule_result["score"],
            "label": rule_result["label"],
            "reasons": rule_result["reasons"],
            "categories": rule_result["categories"],
            "components": {
                "rule_score": rule_result["score"],
                "ai_score": None,
                "final_score": rule_result["score"],
                "ai_confidence": 0,
                "fraud_similarity": 0,
                "legit_similarity": 0,
                "mode": "rules",
                "fallback_used": False,
            },
        }

    try:
        ai_result = analyze_fraud_ai(title, description)
        final_score = round(0.4 * rule_result["score"] + 0.6 * ai_result["score"])
        final_label = fraud_level_from_score(final_score)
        combined_reasons = rule_result["reasons"] + ai_result["reasons"]
        categories = dict(rule_result["categories"])
        if ai_result["reasons"]:
            categories["AI Similarity"] = ai_result["score"]

        if mode == "model":
            final_score = ai_result["score"]
            final_label = ai_result["label"]
            combined_reasons = ai_result["reasons"] or rule_result["reasons"]

        return {
            "score": final_score,
            "label": final_label,
            "reasons": combined_reasons,
            "categories": categories,
            "components": {
                "rule_score": rule_result["score"],
                "ai_score": ai_result["score"],
                "final_score": final_score,
                "ai_confidence": ai_result.get("confidence", 0),
                "fraud_similarity": ai_result.get("fraud_similarity", 0),
                "legit_similarity": ai_result.get("legit_similarity", 0),
                "ai_model": ai_result.get("model"),
                "mode": mode,
                "fallback_used": False,
            },
        }
    except Exception:
        if not fraud_fallback_enabled():
            raise
        return {
            "score": rule_result["score"],
            "label": rule_result["label"],
            "reasons": rule_result["reasons"],
            "categories": rule_result["categories"],
            "components": {
                "rule_score": rule_result["score"],
                "ai_score": None,
                "final_score": rule_result["score"],
                "ai_confidence": 0,
                "fraud_similarity": 0,
                "legit_similarity": 0,
                "mode": mode,
                "fallback_used": True,
            },
        }


def analyze_fraud(title, description):
    analysis = analyze_fraud_details(title, description)
    return analysis["score"], analysis["label"], analysis["reasons"], analysis["categories"]


# ── FEATURE 2: SMART MATCHING ────────────────────────────────
# Skill synonym map — partial matching for common tech aliases
SKILL_SYNONYMS = {
    'js':           'javascript',
    'node':         'node.js',
    'nodejs':       'node.js',
    'react.js':     'react',
    'reactjs':      'react',
    'vue.js':       'vue',
    'vuejs':        'vue',
    'postgres':     'postgresql',
    'psql':         'postgresql',
    'mongo':        'mongodb',
    'py':           'python',
    'django rest':  'django',
    'drf':          'django',
    'scss':         'css',
    'sass':         'css',
    'ts':           'typescript',
    'k8s':          'kubernetes',
    'tf':           'tensorflow',
    'ml':           'machine learning',
    'ai':           'machine learning',
    'ui':           'ui/ux',
    'ux':           'ui/ux',
    'figma':        'ui/ux',
    'rest':         'rest api',
    'restful':      'rest api',
    'api':          'rest api',
}


def normalise_skill(skill):
    s = skill.strip().lower()
    return SKILL_SYNONYMS.get(s, s)


def parse_skills(skills_str):
    return {normalise_skill(s) for s in (skills_str or "").split(",") if s.strip()}


def match_freelancers(job_skills_str, all_freelancers):
    """
    Weighted matching algorithm:
      - Skill match score: % of job skills covered (with synonym expansion + partial matching)
      - Rating boost: normalised 0-100 from 5-star scale
      - Experience boost: log-scaled from review count
      - Final composite = 0.65 * skill_match + 0.25 * rating_norm + 0.10 * exp_norm
    Returns top 5 with full scoring breakdown.
    """
    import math
    job_skills = {normalise_skill(s) for s in job_skills_str.split(",") if s.strip()}
    if not job_skills:
        return []

    results = []
    for fl in all_freelancers:
        raw_fl_skills = [s for s in (fl.get("skills") or "").split(",") if s.strip()]
        if not raw_fl_skills:
            continue
        fl_skills = {normalise_skill(s) for s in raw_fl_skills}

        # Direct + synonym-expanded skill overlap
        matched = job_skills & fl_skills
        # Also check partial substring matches for tech stacks
        partial = set()
        for js in job_skills:
            for fs in fl_skills:
                if js in fs or fs in js:
                    matched.add(js)
                    partial.add(js)

        if not matched:
            continue

        skill_pct   = round(len(matched) / max(len(job_skills), 1) * 100)

        # Rating component: normalised 0-100
        rating      = float(fl.get("rating") or 0)
        rating_norm = max(0, min(100, (rating / 5.0) * 100))

        # Experience component: logarithmic scale (0 reviews = 0, 50 reviews ≈ 100)
        reviews     = int(fl.get("total_reviews") or 0)
        exp_norm    = min(100, math.log1p(reviews) / math.log1p(50) * 100)

        # Composite weighted score
        composite   = round(0.65 * skill_pct + 0.25 * rating_norm + 0.10 * exp_norm)

        results.append({
            "id":              fl["id"],
            "username":        fl["username"],
            "full_name":       fl.get("full_name") or fl["username"],
            "skills":          fl["skills"],
            "rating":          rating,
            "total_reviews":   reviews,
            "bio":             fl.get("bio") or "",
            "matched_skills":  sorted(list(matched)),
            "partial_matches": sorted(list(partial)),
            "missing_skills":  sorted(list(job_skills - matched)),
            "skill_pct":       skill_pct,
            "rating_norm":     round(rating_norm),
            "exp_norm":        round(exp_norm),
            "composite":       composite,
            "match_pct":       composite,  # alias for backward compat
        })

    results.sort(key=lambda x: (-x["composite"], -x["rating"]))
    return results[:5]


def hybrid_match_freelancers(job, all_freelancers, limit=5):
    """
    Hybrid client-side matching:
      final = 0.55 * semantic + 0.25 * skill_overlap + 0.15 * rating + 0.05 * experience
    Keeps the existing rule-based matcher and blends it with the ML semantic score.
    """
    heuristic_matches = match_freelancers(job.get("skills_required") or "", all_freelancers)
    heuristic_by_id = {item["id"]: dict(item) for item in heuristic_matches}

    try:
        semantic_matches = ml_match_freelancers(dict(job), [dict(f) for f in all_freelancers])
    except Exception:
        semantic_matches = []
    semantic_by_id = {item["id"]: dict(item) for item in semantic_matches}

    merged = []
    for freelancer in all_freelancers:
        freelancer_id = freelancer["id"]
        heuristic = heuristic_by_id.get(freelancer_id, {})
        semantic = semantic_by_id.get(freelancer_id, {})

        semantic_score = int(semantic.get("ml_score") or 0)
        skill_overlap = int(heuristic.get("skill_pct") or 0)
        rating_norm = int(heuristic.get("rating_norm") or round(max(0, min(100, (float(freelancer.get("rating") or 0) / 5.0) * 100))))
        exp_norm = int(heuristic.get("exp_norm") or 0)
        final_score = round(
            0.55 * semantic_score +
            0.25 * skill_overlap +
            0.15 * rating_norm +
            0.05 * exp_norm
        )

        matched_skills = heuristic.get("matched_skills")
        if matched_skills is None:
            job_skills = parse_skills(job.get("skills_required") or "")
            freelancer_skills = parse_skills(freelancer.get("skills") or "")
            matched_skills = sorted(job_skills & freelancer_skills)

        partial_matches = heuristic.get("partial_matches", [])
        missing_skills = heuristic.get("missing_skills")
        if missing_skills is None:
            job_skills = parse_skills(job.get("skills_required") or "")
            missing_skills = sorted(job_skills - set(matched_skills))

        if final_score <= 0:
            continue

        rationale = []
        if semantic_score:
            rationale.append(f"semantic {semantic_score}%")
        if skill_overlap:
            rationale.append(f"skill overlap {skill_overlap}%")
        if matched_skills:
            rationale.append("matched " + ", ".join(matched_skills[:3]))

        merged.append({
            "id": freelancer_id,
            "username": freelancer["username"],
            "full_name": freelancer.get("full_name") or freelancer["username"],
            "skills": freelancer.get("skills") or "",
            "bio": freelancer.get("bio") or "",
            "rating": float(freelancer.get("rating") or 0),
            "total_reviews": int(freelancer.get("total_reviews") or 0),
            "semantic_score": semantic_score,
            "skill_pct": skill_overlap,
            "rating_norm": rating_norm,
            "exp_norm": exp_norm,
            "matched_skills": matched_skills,
            "partial_matches": partial_matches,
            "missing_skills": missing_skills,
            "heuristic_score": int(heuristic.get("composite") or 0),
            "ml_score": semantic_score,
            "hybrid_score": final_score,
            "match_pct": final_score,
            "rationale": rationale,
        })

    merged.sort(key=lambda item: (-item["hybrid_score"], -item["semantic_score"], -item["rating"]))
    return merged[:limit]


def match_jobs_for_freelancer(all_jobs, freelancer):
    freelancer_skills = parse_skills(freelancer.get("skills") or "")
    if not freelancer_skills and not (freelancer.get("bio") or "").strip():
        return []

    matched_jobs = []
    for job in all_jobs:
        job_skills = parse_skills(job.get("skills_required") or "")
        common = sorted(freelancer_skills & job_skills)
        skill_overlap = round(len(common) / len(job_skills) * 100) if job_skills else 0

        try:
            semantic_matches = ml_match_freelancers(dict(job), [dict(freelancer)])
            semantic_score = int(semantic_matches[0]["ml_score"]) if semantic_matches else 0
        except Exception:
            semantic_score = 0

        hybrid_score = round(0.65 * semantic_score + 0.35 * skill_overlap)
        if hybrid_score <= 0:
            continue

        enriched = dict(job)
        enriched["matched_skills"] = common
        enriched["skill_pct"] = skill_overlap
        enriched["semantic_score"] = semantic_score
        enriched["hybrid_score"] = hybrid_score
        enriched["match_pct"] = hybrid_score
        enriched["rationale"] = [
            f"semantic {semantic_score}%",
            f"skill overlap {skill_overlap}%",
        ]
        matched_jobs.append(enriched)

    matched_jobs.sort(key=lambda item: (-item["hybrid_score"], item["fraud_score"], -item["budget"]))
    return matched_jobs


# ── FEATURE 3: PROPOSAL GENERATOR ────────────────────────────
PROPOSAL_TEMPLATES = [
    {
        "style": "Professional",
        "text": """Dear Hiring Manager,

I am writing to express my strong interest in the "{title}" project. Having reviewed your requirements thoroughly, I am confident that my expertise in {fl_skills} makes me an excellent candidate for this role.

Your project requires {skills} — areas where I have hands-on professional experience. Based on your description, I understand the core deliverable is: {summary}. I will approach this systematically, beginning with a detailed scoping session to align on expectations, followed by incremental deliveries with your feedback incorporated at each stage.

What you can expect from me:
- Clear communication and regular progress updates
- Clean, well-documented code and deliverables
- On-time delivery within the agreed timeline
- Post-delivery support for any revisions

I am available to start immediately and would welcome the opportunity to discuss the finer details of your project.

Looking forward to your response.

Best regards,
{name}""",
    },
    {
        "style": "Direct",
        "text": """Hello,

Your "{title}" project is exactly the type of work I specialise in. My background in {fl_skills} gives me the foundation needed to deliver this effectively.

Here is my understanding of what you need: {summary}. I have handled similar projects before and know the common challenges — I will navigate them proactively so you do not have to.

My approach: start fast, communicate clearly, and deliver exactly what was agreed. I do not over-promise. I use {skills} regularly in my work and can hit the ground running from day one.

Ready to start. Let us talk.

{name}""",
    },
    {
        "style": "Detailed",
        "text": """Dear Client,

Thank you for posting this opportunity. After carefully reading through the "{title}" project details, I would like to submit my proposal.

**My Understanding of Your Requirements:**
You need: {summary}. The key technical requirements include {skills}, all of which are within my core competency.

**My Relevant Experience:**
I work extensively with {fl_skills}. I have completed multiple projects of similar scope and complexity, which means I understand not just the technical execution but also the edge cases and pitfalls to avoid.

**My Proposed Approach:**
1. Discovery — review all requirements and ask clarifying questions upfront
2. Planning — break down the work into clear milestones
3. Execution — deliver iteratively with regular check-ins
4. Review — incorporate your feedback and finalise

I am committed to transparent communication throughout. You will always know where the project stands.

Please feel free to reach out with any questions. I look forward to the possibility of working together.

Warm regards,
{name}""",
    },
]


def generate_proposal(job_title, job_description, job_skills, freelancer_name, freelancer_skills, style="random"):
    """
    Generates a professional, context-aware proposal cover letter.
    style: 'random', 'Professional', 'Direct', or 'Detailed'
    Returns: (proposal_text, style_used)
    """
    if style == "random" or style not in [t["style"] for t in PROPOSAL_TEMPLATES]:
        chosen = random.choice(PROPOSAL_TEMPLATES)
    else:
        chosen = next(t for t in PROPOSAL_TEMPLATES if t["style"] == style)

    skill_list = ", ".join(s.strip() for s in job_skills.split(",")[:4] if s.strip()) or "the required technologies"
    fl_list    = ", ".join(s.strip() for s in freelancer_skills.split(",")[:4] if s.strip()) or "relevant technologies"
    words      = job_description.split()
    summary    = " ".join(words[:20]) + ("..." if len(words) > 20 else "")

    text = chosen["text"].format(
        title=job_title,
        skills=skill_list,
        fl_skills=fl_list,
        summary=summary,
        name=freelancer_name,
    )
    return text, chosen["style"]


def current_user():
    if is_admin_session():
        email = session.get("admin_email") or admin_email()
        return {
            "id": None,
            "username": "admin",
            "full_name": "Admin",
            "email": email,
            "role": "admin",
            "email_verified": True,
        }
    user_id = session.get("user_id")
    if user_id:
        return query_db("SELECT * FROM users WHERE id=?", [user_id], one=True)
    return None


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id") and not is_admin_session():
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login_page"))
        return func(*args, **kwargs)

    return wrapper


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_admin_session():
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Admin access required"}), 403
            return redirect(url_for("dashboard"))
        return func(*args, **kwargs)

    return wrapper


def notify(user_id, message, notification_type="info", action_url=""):
    """Insert a notification row. Silently swallows errors so it never crashes a caller."""
    try:
        mutate_db(
            "INSERT INTO notifications (user_id, message, action_url, type) VALUES (?, ?, ?, ?) RETURNING id",
            [user_id, message, action_url, notification_type],
        )
    except Exception:
        pass


def user_contact(user_id):
    return query_db(
        "SELECT id, username, full_name, email FROM users WHERE id=?",
        [user_id],
        one=True,
    )


def notify_and_email(user_id, message, notification_type="info", email_subject=None, email_body=None, action_url="", email_html=None):
    notify(user_id, message, notification_type, action_url=action_url)
    if not email_subject or not email_body:
        return

    recipient = user_contact(user_id)
    if not recipient or not recipient.get("email"):
        return

    try:
        deliver_email(recipient["email"], email_subject, email_body, email_html)
    except Exception:
        pass


def email_admin(subject, body, html_body=None):
    recipient = admin_email()
    if not recipient:
        return
    try:
        deliver_email(recipient, subject, body, html_body)
    except Exception:
        pass


def email_founders(subject, body, html_body=None):
    for recipient in founder_alert_emails():
        try:
            deliver_email(recipient, subject, body, html_body)
        except Exception:
            pass


def allowed_upload_name(filename):
    if not filename:
        return False
    lowered = filename.lower()
    return lowered.endswith(".zip") or "." in lowered


def save_submission_archive(job_id, freelancer_id, uploaded_zip=None, uploaded_files=None, relative_paths=None):
    os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
    token = secrets.token_hex(8)
    archive_name = f"job_{job_id}_freelancer_{freelancer_id}_{token}.zip"
    archive_path = os.path.join(SUBMISSIONS_DIR, archive_name)

    if uploaded_zip is not None:
        uploaded_zip.save(archive_path)
        display_name = secure_filename(uploaded_zip.filename) or archive_name
        return display_name, archive_name

    uploaded_files = uploaded_files or []
    relative_paths = relative_paths or []
    if not uploaded_files:
        return "", ""

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, uploaded in enumerate(uploaded_files):
            if not uploaded or not uploaded.filename:
                continue
            rel_path = relative_paths[index] if index < len(relative_paths) else uploaded.filename
            rel_path = rel_path.replace("\\", "/").strip().lstrip("/")
            rel_path = "/".join(part for part in rel_path.split("/") if part not in ("", ".", ".."))
            if not rel_path:
                rel_path = secure_filename(uploaded.filename)
            archive.writestr(rel_path, uploaded.read())

    return f"job_{job_id}_submission_folder.zip", archive_name


def get_json_safe():
    try:
        return request.get_json(force=True) or {}
    except Exception:
        return {}


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(16)
        session["csrf_token"] = token
    return token


def format_date(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y")
    text_value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text_value, fmt).strftime("%b %d, %Y")
        except ValueError:
            continue
    return text_value


def iso_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text_value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text_value, fmt).isoformat()
        except ValueError:
            continue
    return text_value.replace(" ", "T")


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["format_date"] = format_date


@app.before_request
def enforce_csrf():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        csrf_token()
        return None
    if not request.path.startswith("/api/"):
        return None
    expected = session.get("csrf_token")
    provided = request.headers.get("X-CSRF-Token", "")
    if not expected or provided != expected:
        return jsonify({"error": "Invalid CSRF token"}), 403
    return None


def smtp_settings():
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    from_email = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    port_raw = os.environ.get("SMTP_PORT", "587").strip() or "587"
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT must be an integer.") from exc
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "from_email": from_email,
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
    }


def ensure_mail_configured():
    if app.config.get("TESTING"):
        return None
    settings = smtp_settings()
    required = ("host", "port", "username", "password", "from_email")
    missing = [key for key in required if not settings.get(key)]
    if missing:
        raise RuntimeError(
            "Email delivery is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL."
        )
    return settings


def html_email(title, body_html, cta_label=None, cta_url=None):
    """
    Builds a branded HTML email with EscrowIQ styling.
    Returns (html_content, plain_text_fallback).
    """
    cta_block = ""
    if cta_label and cta_url:
        cta_block = f"""
        <div style="text-align:center;margin:28px 0 8px">
          <a href="{cta_url}"
             style="display:inline-block;background:linear-gradient(135deg,#14b8a6,#2dd4bf);color:#06211d;
                    text-decoration:none;font-weight:700;font-size:14px;padding:12px 28px;
                    border-radius:10px;letter-spacing:.02em">
            {cta_label}
          </a>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head>
<body style="margin:0;padding:0;background:#0b1118;font-family:Inter,Helvetica,Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0b1118;padding:32px 16px">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px">

        <!-- Header / Logo -->
        <tr><td style="padding-bottom:20px;text-align:center">
          <div style="display:inline-flex;align-items:center;gap:12px;text-decoration:none">
            <img src="data:image/png;base64,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" alt="EscrowIQ" width="56" height="56" style="border-radius:50%;display:block;flex-shrink:0">
            <span style="font-size:20px;font-weight:800;color:#e5edf5;letter-spacing:-.01em">EscrowIQ</span>
          </div>
        </td></tr>

        <!-- Card -->
        <tr><td style="background:linear-gradient(180deg,rgba(18,25,34,.97),rgba(22,31,43,.99));
                        border:1px solid rgba(148,163,184,.12);border-radius:18px;overflow:hidden">

          <!-- Accent bar -->
          <div style="height:3px;background:linear-gradient(90deg,#14b8a6,#2dd4bf,#67e8f9)"></div>

          <!-- Body -->
          <div style="padding:32px 32px 24px">
            <h2 style="margin:0 0 16px;font-size:20px;font-weight:800;color:#e5edf5;line-height:1.3">
              {title}
            </h2>
            <div style="color:#98a8ba;font-size:14px;line-height:1.75">
              {body_html}
            </div>
            {cta_block}
          </div>

          <!-- Footer -->
          <div style="padding:16px 32px 24px;border-top:1px solid rgba(148,163,184,.1)">
            <p style="margin:0;font-size:12px;color:#64748b;text-align:center">
              This email was sent by EscrowIQ · Freelance Escrow Platform<br>
              If you did not expect this email, you can safely ignore it.
            </p>
          </div>

        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return html


def deliver_email(recipient, subject, text_body, html_body=None):
    if app.config.get("TESTING"):
        return
    settings = ensure_mail_configured()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["from_email"]
    message["To"] = recipient
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    if settings["use_tls"]:
        with smtplib.SMTP(settings["host"], settings["port"], timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
        return

    with smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=20, context=ssl.create_default_context()) as smtp:
        smtp.login(settings["username"], settings["password"])
        smtp.send_message(message)


def generate_email_code():
    return f"{random.randint(0, 999999):06d}"


def store_email_code(email, purpose, code, ttl_minutes=15, user_id=None):
    expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
    if user_id is None:
        user = query_db("SELECT id FROM users WHERE email=?", [email], one=True)
        if not user:
            raise ValueError("Cannot create an email code for a missing user.")
        user_id = user["id"]
    mutate_db("DELETE FROM email_codes WHERE email=? AND purpose=? AND consumed_at IS NULL", [email, purpose])
    mutate_db(
        "INSERT INTO email_codes (user_id, email, purpose, code, expires_at) VALUES (?, ?, ?, ?, ?)",
        [user_id, email, purpose, code, expires_at],
    )


def latest_email_code(email, purpose):
    return query_db(
        """
        SELECT *
        FROM email_codes
        WHERE email=? AND purpose=? AND consumed_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [email, purpose],
        one=True,
    )


def consume_email_code(email, purpose, code):
    row = latest_email_code(email, purpose)
    if not row:
        return False, "Code not found. Request a new one."
    expires_at = row["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00").replace(" ", "T"))
    if expires_at < datetime.utcnow():
        mutate_db(
            "UPDATE email_codes SET consumed_at=CURRENT_TIMESTAMP WHERE email=? AND purpose=? AND consumed_at IS NULL",
            [email, purpose],
        )
        return False, "Code expired. Request a new one."
    if row["code"] != code:
        return False, "Invalid code."
    mutate_db("UPDATE email_codes SET consumed_at=CURRENT_TIMESTAMP WHERE id=?", [row["id"]])
    return True, None


def send_email_code(email, purpose, user_id=None):
    code = generate_email_code()
    store_email_code(email, purpose, code, user_id=user_id)

    if purpose == "verify_email":
        subject = "EscrowIQ — Verify your email"
        text_body = (
            f"Your EscrowIQ verification code is {code}. It expires in 15 minutes.\n\n"
            "If you did not create this account, you can ignore this email."
        )
        html_body = html_email(
            "Verify your email address",
            f"""<p>Welcome to EscrowIQ. Use the code below to verify your email and activate your account.</p>
            <div style="margin:24px 0;text-align:center">
              <div style="display:inline-block;background:rgba(45,212,191,.1);border:1.5px solid rgba(45,212,191,.25);
                          border-radius:12px;padding:16px 36px">
                <span style="font-size:32px;font-weight:800;letter-spacing:.18em;color:#2dd4bf">{code}</span>
              </div>
            </div>
            <p style="font-size:13px;color:#64748b;text-align:center">This code expires in 15 minutes. If you did not sign up for EscrowIQ, you can safely ignore this email.</p>""",
        )
    else:
        subject = "EscrowIQ — Password reset code"
        text_body = (
            f"Your EscrowIQ password reset code is {code}. It expires in 15 minutes.\n\n"
            "If you did not request a password reset, you can ignore this email."
        )
        html_body = html_email(
            "Reset your password",
            f"""<p>You requested a password reset for your EscrowIQ account. Use the code below to set a new password.</p>
            <div style="margin:24px 0;text-align:center">
              <div style="display:inline-block;background:rgba(245,158,11,.08);border:1.5px solid rgba(245,158,11,.22);
                          border-radius:12px;padding:16px 36px">
                <span style="font-size:32px;font-weight:800;letter-spacing:.18em;color:#f59e0b">{code}</span>
              </div>
            </div>
            <p style="font-size:13px;color:#64748b;text-align:center">This code expires in 15 minutes. If you did not request this, your account is safe — just ignore this email.</p>""",
        )

    deliver_email(email, subject, text_body, html_body)
    return code


@app.route("/")
def index():
    total_jobs = query_db("SELECT COUNT(*) AS c FROM jobs", one=True)["c"]
    total_users = query_db("SELECT COUNT(*) AS c FROM users", one=True)["c"]
    total_escrow = query_db(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM escrow WHERE status='released'",
        one=True,
    )["s"]
    open_jobs = query_db(
        """
        SELECT j.*, COALESCE(u.full_name, u.username) AS client_name
        FROM jobs j
        JOIN users u ON j.client_id=u.id
        WHERE j.status='open'
        ORDER BY j.created_at DESC
        LIMIT 4
        """
    )
    return render_template(
        "index.html",
        user=current_user(),
        total_jobs=total_jobs,
        total_users=total_users,
        total_escrow=total_escrow,
        open_jobs=open_jobs,
    )


@app.route("/register")
def register_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/verify-email")
def verify_email_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("verify_email.html", preset_email=request.args.get("email", "").strip().lower())


@app.route("/forgot-password")
def forgot_password_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("forgot_password.html", preset_email=request.args.get("email", "").strip().lower())


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_complaints_page"))
    if user["role"] == "client":
        jobs = query_db(
            """
            SELECT j.*, (SELECT COUNT(*) FROM proposals WHERE job_id=j.id) AS proposal_count
            FROM jobs j
            WHERE j.client_id=?
            ORDER BY j.created_at DESC
            """,
            [user["id"]],
        )
        return render_template("dashboard_client.html", user=user, jobs=jobs)

    jobs = query_db(
        """
        SELECT j.*, COALESCE(u.full_name, u.username) AS client_name,
               (SELECT COUNT(*) FROM proposals WHERE job_id=j.id) AS proposal_count
        FROM jobs j
        JOIN users u ON j.client_id=u.id
        WHERE j.status='open'
        ORDER BY j.created_at DESC
        """
    )
    jobs = match_jobs_for_freelancer(jobs, user)
    my_proposals = query_db(
        """
        SELECT p.*, j.title AS job_title, j.budget AS job_budget,
               j.status AS job_status, COALESCE(u.full_name, u.username) AS client_name
        FROM proposals p
        JOIN jobs j ON p.job_id=j.id
        JOIN users u ON j.client_id=u.id
        WHERE p.freelancer_id=?
        ORDER BY p.created_at DESC
        """,
        [user["id"]],
    )
    return render_template("dashboard_freelancer.html", user=user, jobs=jobs, my_proposals=my_proposals)


@app.route("/jobs")
@login_required
def jobs_page():
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_complaints_page"))
    if user["role"] == "client":
        return redirect(url_for("dashboard"))
    jobs = query_db(
        """
        SELECT j.*, COALESCE(u.full_name, u.username) AS client_name,
               (SELECT COUNT(*) FROM proposals WHERE job_id=j.id) AS proposal_count
        FROM jobs j
        JOIN users u ON j.client_id=u.id
        WHERE j.status='open'
        ORDER BY j.created_at DESC
        """
    )
    if user["role"] == "freelancer":
        jobs = match_jobs_for_freelancer(jobs, user)
    return render_template("jobs.html", user=user, jobs=jobs)


@app.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id):
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_complaints_page"))
    job = query_db(
        """
        SELECT j.*, COALESCE(u.full_name, u.username) AS client_name, u.rating AS client_rating,
               u.total_reviews AS client_reviews,
               (SELECT COUNT(*) FROM proposals WHERE job_id=j.id) AS proposal_count
        FROM jobs j
        JOIN users u ON j.client_id=u.id
        WHERE j.id=?
        """,
        [job_id],
        one=True,
    )
    if not job:
        return redirect(url_for("jobs_page"))

    proposals = []
    escrow_info = None
    matched = []
    user_proposal = None
    accepted_proposal = query_db(
        """
        SELECT p.*, COALESCE(u.full_name, u.username) AS freelancer_name
        FROM proposals p
        JOIN users u ON p.freelancer_id=u.id
        WHERE p.job_id=? AND p.status='accepted'
        LIMIT 1
        """,
        [job_id],
        one=True,
    )
    latest_submission = query_db(
        """
        SELECT ws.*, COALESCE(u.full_name, u.username) AS freelancer_name
        FROM work_submissions ws
        JOIN users u ON ws.freelancer_id=u.id
        WHERE ws.job_id=?
        ORDER BY ws.created_at DESC, ws.id DESC
        LIMIT 1
        """,
        [job_id],
        one=True,
    )
    open_complaints = query_db(
        """
        SELECT c.*, COALESCE(u.full_name, u.username) AS complainant_name
        FROM complaints c
        LEFT JOIN users u ON c.complainant_id=u.id
        WHERE c.job_id=? AND c.status='open'
        ORDER BY c.created_at DESC, c.id DESC
        """,
        [job_id],
    )

    escrow_info = query_db("SELECT * FROM escrow WHERE job_id=? ORDER BY created_at DESC LIMIT 1", [job_id], one=True)

    if user["role"] == "client" and job["client_id"] == user["id"]:
        proposals = query_db(
            """
            SELECT p.*, COALESCE(u.full_name, u.username) AS freelancer_name, u.skills AS freelancer_skills,
                   u.rating AS freelancer_rating, u.total_reviews, u.bio AS freelancer_bio
            FROM proposals p
            JOIN users u ON p.freelancer_id=u.id
            WHERE p.job_id=?
            ORDER BY p.bid_amount ASC
            """,
            [job_id],
        )
        freelancers = query_db("SELECT * FROM users WHERE role='freelancer'")
        matched = hybrid_match_freelancers(job, freelancers)

    if user["role"] == "freelancer":
        user_proposal = query_db(
            "SELECT * FROM proposals WHERE job_id=? AND freelancer_id=?",
            [job_id, user["id"]],
            one=True,
        )

    can_chat = False
    chat_partner = None
    messages = []
    if accepted_proposal:
        if user["role"] == "client" and job["client_id"] == user["id"]:
            can_chat = True
            chat_partner = {
                "id": accepted_proposal["freelancer_id"],
                "name": accepted_proposal["freelancer_name"],
            }
        elif user["role"] == "freelancer" and accepted_proposal["freelancer_id"] == user["id"]:
            can_chat = True
            chat_partner = {
                "id": job["client_id"],
                "name": job["client_name"],
            }

    if can_chat:
        messages = query_db(
            """
            SELECT m.*, COALESCE(u.full_name, u.username) AS sender_name
            FROM messages m
            JOIN users u ON m.sender_id=u.id
            WHERE m.job_id=?
            ORDER BY m.created_at ASC, m.id ASC
            """,
            [job_id],
        )
        mutate_db("UPDATE messages SET is_read=1 WHERE job_id=? AND recipient_id=?", [job_id, user["id"]])

    fraud_reasons = json.loads(job["fraud_reasons"] or "[]")
    return render_template(
        "job_detail.html",
        user=user,
        job=job,
        proposals=proposals,
        escrow_info=escrow_info,
        user_proposal=user_proposal,
        matched=matched,
        fraud_reasons=fraud_reasons,
        latest_submission=latest_submission,
        open_complaints=open_complaints,
        accepted_proposal=accepted_proposal,
        can_chat=can_chat,
        chat_partner=chat_partner,
        messages=messages,
    )


@app.route("/profile")
@login_required
def profile_page():
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_complaints_page"))
    extra = {}
    if user["role"] == "client":
        extra["recent_jobs"] = query_db(
            """
            SELECT j.*, (SELECT COUNT(*) FROM proposals WHERE job_id=j.id) AS proposal_count
            FROM jobs j
            WHERE j.client_id=?
            ORDER BY created_at DESC
            LIMIT 5
            """,
            [user["id"]],
        )
    else:
        extra["recent_proposals"] = query_db(
            """
            SELECT p.*, j.title AS job_title, j.budget AS job_budget
            FROM proposals p
            JOIN jobs j ON p.job_id=j.id
            WHERE p.freelancer_id=?
            ORDER BY p.created_at DESC
            LIMIT 5
            """,
            [user["id"]],
        )
    return render_template("profile.html", user=user, **extra)


@app.route("/escrow")
@login_required
def escrow_page():
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_complaints_page"))
    if user["role"] == "client":
        escrows = query_db(
            """
            SELECT e.*, j.title AS job_title, COALESCE(u.full_name, u.username) AS freelancer_name
            FROM escrow e
            JOIN jobs j ON e.job_id=j.id
            LEFT JOIN users u ON e.freelancer_id=u.id
            WHERE e.client_id=?
            ORDER BY e.created_at DESC
            """,
            [user["id"]],
        )
    else:
        escrows = query_db(
            """
            SELECT e.*, j.title AS job_title, COALESCE(u.full_name, u.username) AS client_name
            FROM escrow e
            JOIN jobs j ON e.job_id=j.id
            JOIN users u ON e.client_id=u.id
            WHERE e.freelancer_id=?
            ORDER BY e.created_at DESC
            """,
            [user["id"]],
        )
    return render_template("escrow.html", user=user, escrows=escrows)


@app.route("/admin/complaints")
@login_required
@admin_required
def admin_complaints_page():
    complaints = query_db(
        """
        SELECT c.*,
               j.title AS job_title,
               j.description AS job_description,
               j.skills_required,
               ws.delivery_message,
               ws.delivery_url,
               ws.upload_archive_path,
               ws.client_feedback,
               COALESCE(cp.full_name, cp.username, 'Unknown') AS complainant_name,
               COALESCE(ag.full_name, ag.username, 'Unknown') AS against_name
        FROM complaints c
        JOIN jobs j ON c.job_id=j.id
        LEFT JOIN work_submissions ws ON c.submission_id=ws.id
        LEFT JOIN users cp ON c.complainant_id=cp.id
        LEFT JOIN users ag ON c.against_user_id=ag.id
        ORDER BY
            CASE WHEN c.status='open' THEN 0 ELSE 1 END,
            c.created_at DESC,
            c.id DESC
        """
    )
    return render_template("admin_complaints.html", user=current_user(), complaints=complaints)


@app.route("/submissions/<int:submission_id>/download")
@login_required
def download_submission_archive(submission_id):
    submission = query_db(
        """
        SELECT ws.*, j.client_id, e.freelancer_id
        FROM work_submissions ws
        JOIN jobs j ON ws.job_id=j.id
        LEFT JOIN escrow e ON ws.escrow_id=e.id
        WHERE ws.id=?
        """,
        [submission_id],
        one=True,
    )
    if not submission or not submission.get("upload_archive_path"):
        return redirect(url_for("dashboard"))

    user = current_user()
    if user["role"] != "admin":
        user_id = user.get("id")
        allowed = user_id in {submission["client_id"], submission["freelancer_id"], submission["freelancer_id"]}
        if not allowed:
            return redirect(url_for("dashboard"))

    archive_path = os.path.join(SUBMISSIONS_DIR, submission["upload_archive_path"])
    if not os.path.exists(archive_path):
        return redirect(url_for("dashboard"))

    return send_file(
        archive_path,
        as_attachment=True,
        download_name=submission.get("upload_archive_name") or os.path.basename(archive_path),
    )


@app.route("/api/register", methods=["POST"])
def api_register():
    data = get_json_safe()
    username = data.get("username", "").strip()
    full_name = data.get("full_name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    role = data.get("role", "")
    skills = data.get("skills", "").strip()
    bio = data.get("bio", "").strip()

    if not all([username, email, password, role]):
        return jsonify({"error": "All fields are required"}), 400
    if role not in ("client", "freelancer"):
        return jsonify({"error": "Invalid role"}), 400
    if len(username) < 3 or len(username) > 30:
        return jsonify({"error": "Username must be 3-30 characters"}), 400
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        return jsonify({"error": "Username: letters, numbers, underscores only"}), 400
    if full_name and len(full_name) > 120:
        return jsonify({"error": "Full name must be 120 characters or fewer"}), 400
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return jsonify({"error": "Please enter a valid email address"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if query_db("SELECT id FROM users WHERE username=?", [username], one=True):
        return jsonify({"error": "Username already taken"}), 409
    if query_db("SELECT id FROM users WHERE email=?", [email], one=True):
        return jsonify({"error": "Email already registered"}), 409

    hashed = generate_password_hash(password)
    insert_user_sql = """
        INSERT INTO users (username, full_name, email, password, email_verified, role, skills, bio)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    if is_postgres():
        insert_user_sql += " RETURNING id"

    user_id = mutate_db(
        insert_user_sql,
        [username, full_name, email, hashed, False, role, skills, bio],
    )
    try:
        send_email_code(email, "verify_email")
    except RuntimeError as exc:
        mutate_db("DELETE FROM users WHERE id=?", [user_id])
        return jsonify({"error": str(exc)}), 503
    except Exception:
        mutate_db("DELETE FROM users WHERE id=?", [user_id])
        return jsonify({"error": "Unable to send verification email right now. Please try again later."}), 502

    notify(user_id, f"Welcome to EscrowIQ, {full_name or username}. Verify your email to activate the account.", "info", "/verify-email")
    return jsonify({"message": "Account created. Check your inbox for the verification code.", "redirect": f"/verify-email?email={email}"}), 201


@app.route("/api/login", methods=["POST"])
def api_login():
    data = get_json_safe()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    if admin_email() and email == admin_email() and password == admin_password():
        session.clear()
        session["is_admin"] = True
        session["admin_email"] = email
        session["username"] = "admin"
        session["full_name"] = "Admin"
        session["role"] = "admin"
        csrf_token()
        _ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
        _ua = request.headers.get('User-Agent', 'unknown')
        _time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        email_founders(
            "EscrowIQ admin login detected",
            (
                "An admin login was detected on EscrowIQ.\n\n"
                f"Admin email: {email}\n"
                f"Time: {_time} UTC\n"
                f"IP: {_ip}\n"
                f"User-Agent: {_ua}"
            ),
            html_email(
                "⚠️ Admin Login Detected",
                f"""<p>An admin login was recorded on EscrowIQ. If this was not you, investigate immediately.</p>
                <table style="width:100%;border-collapse:collapse;margin-top:16px">
                  <tr><td style="padding:8px 0;color:#64748b;font-size:13px;border-bottom:1px solid rgba(148,163,184,.1)">Email</td><td style="padding:8px 0;font-size:13px;color:#e5edf5;text-align:right">{email}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;font-size:13px;border-bottom:1px solid rgba(148,163,184,.1)">Time (UTC)</td><td style="padding:8px 0;font-size:13px;color:#e5edf5;text-align:right">{_time}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;font-size:13px;border-bottom:1px solid rgba(148,163,184,.1)">IP Address</td><td style="padding:8px 0;font-size:13px;color:#e5edf5;text-align:right">{_ip}</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;font-size:13px">User-Agent</td><td style="padding:8px 0;font-size:12px;color:#98a8ba;text-align:right;word-break:break-all">{_ua[:80]}</td></tr>
                </table>"""
            ),
        )
        return (
            jsonify(
                {
                    "message": "Admin login successful",
                    "redirect": "/admin/complaints",
                    "role": "admin",
                    "username": "admin",
                }
            ),
            200,
        )

    user = query_db("SELECT * FROM users WHERE email=?", [email], one=True)
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid email or password"}), 401
    if not user.get("email_verified"):
        return (
            jsonify(
                {
                    "error": "Email verification required",
                    "verification_required": True,
                    "redirect": f"/verify-email?email={email}",
                }
            ),
            403,
        )

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["full_name"] = user.get("full_name") or user["username"]
    session["role"] = user["role"]
    return (
        jsonify(
            {
                "message": "Login successful",
                "redirect": "/dashboard",
                "role": user["role"],
                "username": user["username"],
            }
        ),
        200,
    )


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"redirect": "/"}), 200


@app.route("/api/auth/verify-email", methods=["POST"])
def api_verify_email():
    data = get_json_safe()
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()

    if not email or not code:
        return jsonify({"error": "Email and code are required"}), 400

    user = query_db("SELECT id, username, full_name, email_verified FROM users WHERE email=?", [email], one=True)
    if not user:
        return jsonify({"error": "Account not found"}), 404
    if user.get("email_verified"):
        return jsonify({"message": "Email already verified.", "redirect": "/login"}), 200

    ok, error = consume_email_code(email, "verify_email", code)
    if not ok:
        return jsonify({"error": error}), 400

    mutate_db(
        "UPDATE users SET email_verified=TRUE, email_verified_at=CURRENT_TIMESTAMP WHERE email=?",
        [email],
    )
    notify(user["id"], f"Email verified for {user.get('full_name') or user['username']}. Your account is active.", "success", "/dashboard")
    return jsonify({"message": "Email verified successfully.", "redirect": "/login"}), 200


@app.route("/api/auth/resend-verification", methods=["POST"])
def api_resend_verification():
    data = get_json_safe()
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = query_db("SELECT id, email_verified FROM users WHERE email=?", [email], one=True)
    if not user:
        return jsonify({"error": "Account not found"}), 404
    if user.get("email_verified"):
        return jsonify({"message": "Email already verified."}), 200

    try:
        send_email_code(email, "verify_email")
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception:
        return jsonify({"error": "Unable to send verification email right now. Please try again later."}), 502
    return jsonify({"message": "Verification code sent to your email."}), 200


@app.route("/api/auth/request-password-reset", methods=["POST"])
def api_request_password_reset():
    data = get_json_safe()
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = query_db("SELECT id FROM users WHERE email=?", [email], one=True)
    if not user:
        return jsonify({"message": "If that email exists, a reset code has been sent."}), 200

    try:
        send_email_code(email, "reset_password")
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception:
        return jsonify({"error": "Unable to send password reset email right now. Please try again later."}), 502
    return jsonify({"message": "Reset code sent to your email."}), 200


@app.route("/api/auth/reset-password", methods=["POST"])
def api_reset_password():
    data = get_json_safe()
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()
    password = data.get("password", "")

    if not email or not code or not password:
        return jsonify({"error": "Email, code, and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    user = query_db("SELECT id FROM users WHERE email=?", [email], one=True)
    if not user:
        return jsonify({"error": "Account not found"}), 404

    ok, error = consume_email_code(email, "reset_password", code)
    if not ok:
        return jsonify({"error": error}), 400

    mutate_db("UPDATE users SET password=? WHERE email=?", [generate_password_hash(password), email])
    notify(user["id"], "Your password was updated successfully.", "success", "/profile")
    return jsonify({"message": "Password updated successfully.", "redirect": "/login"}), 200


@app.route("/api/jobs", methods=["POST"])
@login_required
def api_post_job():
    user = current_user()
    if user["role"] != "client":
        return jsonify({"error": "Only clients can post jobs"}), 403

    data = get_json_safe()
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    skills = data.get("skills_required", "").strip()
    budget = data.get("budget")
    deadline = data.get("deadline", "").strip()

    if not all([title, description, skills, budget, deadline]):
        return jsonify({"error": "All fields are required"}), 400
    if len(title) < 5:
        return jsonify({"error": "Job title must be at least 5 characters"}), 400

    try:
        budget = float(budget)
        if budget <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Budget must be a positive number"}), 400

    try:
        parsed_deadline = datetime.strptime(deadline, "%Y-%m-%d")
        if parsed_deadline.date() <= datetime.today().date():
            return jsonify({"error": "Deadline must be a future date"}), 400
    except ValueError:
        return jsonify({"error": "Invalid deadline format (YYYY-MM-DD)"}), 400

    fraud_analysis = analyze_fraud_details(title, description)
    fraud_score = fraud_analysis["score"]
    fraud_level = fraud_analysis["label"]
    fraud_reasons = fraud_analysis["reasons"]

    insert_job_sql = """
        INSERT INTO jobs (client_id, title, description, skills_required, budget, deadline, fraud_score, fraud_level, fraud_reasons)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    if is_postgres():
        insert_job_sql += " RETURNING id"

    job_id = mutate_db(
        insert_job_sql,
        [
            user["id"],
            title,
            description,
            skills,
            budget,
            deadline,
            fraud_score,
            fraud_level,
            json.dumps(fraud_reasons),
        ],
    )

    if fraud_level == "High":
        notify(user["id"], f"Job '{title}' was flagged as high risk. Consider revising it.", "warning", f"/jobs/{job_id}")

    return (
        jsonify(
            {
                "message": "Job posted successfully",
                "job_id": job_id,
                "fraud_level": fraud_level,
                "fraud_score": fraud_score,
                "fraud_reasons": fraud_reasons,
                "fraud_components": fraud_analysis["components"],
            }
        ),
        201,
    )


@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
@login_required
def api_delete_job(job_id):
    user = current_user()
    job = query_db("SELECT * FROM jobs WHERE id=?", [job_id], one=True)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["client_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403

    mutate_db("DELETE FROM proposals WHERE job_id=?", [job_id])
    mutate_db("DELETE FROM jobs WHERE id=?", [job_id])
    return jsonify({"message": "Job deleted"}), 200


@app.route("/api/proposals", methods=["POST"])
@login_required
def api_submit_proposal():
    user = current_user()
    if user["role"] != "freelancer":
        return jsonify({"error": "Only freelancers can submit proposals"}), 403

    data = get_json_safe()
    job_id = data.get("job_id")
    cover_letter = data.get("cover_letter", "").strip()
    bid_amount = data.get("bid_amount")
    timeline = data.get("timeline", "").strip()

    if not all([job_id, cover_letter, bid_amount, timeline]):
        return jsonify({"error": "All fields are required"}), 400
    if len(cover_letter) < 50:
        return jsonify({"error": "Cover letter must be at least 50 characters"}), 400

    try:
        bid_amount = float(bid_amount)
        if bid_amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Bid must be a positive number"}), 400

    job = query_db("SELECT * FROM jobs WHERE id=? AND status='open'", [job_id], one=True)
    if not job:
        return jsonify({"error": "Job not found or no longer accepting proposals"}), 404
    if job["client_id"] == user["id"]:
        return jsonify({"error": "You cannot apply to your own job"}), 403
    if query_db("SELECT id FROM proposals WHERE job_id=? AND freelancer_id=?", [job_id, user["id"]], one=True):
        return jsonify({"error": "You have already applied to this job"}), 409

    insert_proposal_sql = """
        INSERT INTO proposals (job_id, freelancer_id, cover_letter, bid_amount, timeline)
        VALUES (?, ?, ?, ?, ?)
    """
    if is_postgres():
        insert_proposal_sql += " RETURNING id"

    try:
        proposal_id = mutate_db(
            insert_proposal_sql,
            [job_id, user["id"], cover_letter, bid_amount, timeline],
        )
    except IntegrityError:
        return jsonify({"error": "You have already applied to this job"}), 409
    notify_and_email(
        job["client_id"],
        f"New proposal from {user.get('full_name') or user['username']} for '{job['title']}'",
        "info",
        email_subject=f"New proposal for {job['title']}",
        email_body=(
            f"{user.get('full_name') or user['username']} submitted a proposal for your job '{job['title']}'.\n\n"
            f"Bid amount: ${bid_amount:.2f}\n"
            f"Timeline: {timeline}\n\n"
            "Open EscrowIQ to review the application."
        ),
        action_url=f"/jobs/{job_id}",
    )
    return jsonify({"message": "Proposal submitted successfully", "proposal_id": proposal_id}), 201


@app.route("/api/proposals/<int:proposal_id>/accept", methods=["POST"])
@login_required
def api_accept_proposal(proposal_id):
    user = current_user()
    proposal = query_db(
        """
        SELECT p.*, j.title AS job_title, j.client_id
        FROM proposals p
        JOIN jobs j ON p.job_id=j.id
        WHERE p.id=?
        """,
        [proposal_id],
        one=True,
    )
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404
    if proposal["client_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    if proposal["status"] != "pending":
        return jsonify({"error": "Proposal is no longer pending"}), 400

    auto_rejected = query_db(
        """
        SELECT p.freelancer_id, COALESCE(u.full_name, u.username) AS freelancer_name
        FROM proposals p
        JOIN users u ON p.freelancer_id=u.id
        WHERE p.job_id=? AND p.id!=? AND p.status='pending'
        """,
        [proposal["job_id"], proposal_id],
    )

    # Wrap all state changes in one transaction — if any write fails, all roll back
    with get_engine().begin() as txn:
        txn.execute(text(
            "UPDATE proposals SET status='accepted' WHERE id=:pid"
        ), {"pid": proposal_id})
        txn.execute(text(
            "UPDATE proposals SET status='rejected' WHERE job_id=:jid AND id!=:pid AND status='pending'"
        ), {"jid": proposal["job_id"], "pid": proposal_id})
        txn.execute(text(
            "UPDATE jobs SET status='in_progress' WHERE id=:jid"
        ), {"jid": proposal["job_id"]})

    notify_and_email(
        proposal["freelancer_id"],
        f"Your proposal for '{proposal['job_title']}' was accepted.",
        "success",
        email_subject=f"Proposal accepted — {proposal['job_title']}",
        email_body=(
            f"Your proposal for '{proposal['job_title']}' was accepted.\n\n"
            "The client can now fund escrow to start the project."
        ),
        email_html=html_email(
            "🎉 Your proposal was accepted!",
            f"""<p>Great news! Your proposal for <strong style="color:#e5edf5">{proposal['job_title']}</strong> was accepted by the client.</p>
            <p>The next step is for the client to fund escrow. Once funded, you can begin work and submit your delivery.</p>""",
            cta_label="View Project", cta_url=f"/jobs/{proposal['job_id']}",
        ),
        action_url=f"/jobs/{proposal['job_id']}",
    )
    for rejected in auto_rejected:
        notify_and_email(
            rejected["freelancer_id"],
            f"Your proposal for '{proposal['job_title']}' was not selected.",
            "info",
            email_subject=f"Proposal update — {proposal['job_title']}",
            email_body=(
                f"Your proposal for '{proposal['job_title']}' was not selected this time.\n\n"
                "You can keep applying to other opportunities in EscrowIQ."
            ),
            email_html=html_email(
                "Proposal update",
                f"""<p>Your proposal for <strong style="color:#e5edf5">{proposal['job_title']}</strong> was not selected this time.</p>
                <p>Don't be discouraged — there are other opportunities waiting for you on EscrowIQ.</p>""",
                cta_label="Browse Jobs", cta_url="/jobs",
            ),
            action_url=f"/jobs/{proposal['job_id']}",
        )
    return jsonify({"message": "Proposal accepted"}), 200


@app.route("/api/proposals/<int:proposal_id>/reject", methods=["POST"])
@login_required
def api_reject_proposal(proposal_id):
    user = current_user()
    proposal = query_db(
        """
        SELECT p.*, j.client_id, j.title AS job_title
        FROM proposals p
        JOIN jobs j ON p.job_id=j.id
        WHERE p.id=?
        """,
        [proposal_id],
        one=True,
    )
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404
    if proposal["client_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    if proposal["status"] != "pending":
        return jsonify({"error": "Cannot reject a non-pending proposal"}), 400

    mutate_db("UPDATE proposals SET status='rejected' WHERE id=?", [proposal_id])
    notify_and_email(
        proposal["freelancer_id"],
        f"Your proposal for '{proposal['job_title']}' was not selected.",
        "info",
        email_subject=f"Proposal update for {proposal['job_title']}",
        email_body=(
            f"Your proposal for '{proposal['job_title']}' was not selected this time.\n\n"
            "You can keep applying to other opportunities in EscrowIQ."
        ),
        action_url=f"/jobs/{proposal['job_id']}",
    )
    return jsonify({"message": "Proposal rejected"}), 200


@app.route("/api/escrow/deposit", methods=["POST"])
@login_required
def api_escrow_deposit():
    user = current_user()
    if user["role"] != "client":
        return jsonify({"error": "Only clients can fund escrow"}), 403

    data = get_json_safe()
    job_id = data.get("job_id")
    amount = data.get("amount")
    freelancer_id = data.get("freelancer_id")

    if not job_id or amount is None:
        return jsonify({"error": "Job ID and amount are required"}), 400

    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Amount must be a positive number"}), 400

    job = query_db("SELECT * FROM jobs WHERE id=? AND client_id=?", [job_id, user["id"]], one=True)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if round(amount, 2) != round(float(job["budget"]), 2):
        return jsonify({"error": f"Escrow must be funded with the full agreed job budget of ${float(job['budget']):.2f}."}), 400
    if query_db("SELECT id FROM escrow WHERE job_id=? AND status='held'", [job_id], one=True):
        return jsonify({"error": "Active escrow already exists for this job"}), 409
    accepted = query_db(
        """
        SELECT freelancer_id
        FROM proposals
        WHERE job_id=? AND status='accepted'
        """,
        [job_id],
        one=True,
    )
    if not accepted:
        return jsonify({"error": "Accept a proposal before funding escrow"}), 400
    if not freelancer_id:
        return jsonify({"error": "Accepted freelancer is required before funding escrow"}), 400
    if accepted["freelancer_id"] != freelancer_id:
        return jsonify({"error": "Escrow can only be funded for the accepted freelancer"}), 400

    fresh = query_db("SELECT balance FROM users WHERE id=?", [user["id"]], one=True)
    if fresh["balance"] < amount:
        return jsonify({"error": f"Insufficient balance (${fresh['balance']:.2f} available)"}), 400

    # Atomic: deduct balance AND create escrow row together — no partial states
    with get_engine().begin() as txn:
        txn.execute(text(
            "UPDATE users SET balance=balance-:amt WHERE id=:uid"
        ), {"amt": amount, "uid": user["id"]})
        result = txn.execute(text(
            "INSERT INTO escrow (job_id, client_id, freelancer_id, amount) VALUES (:jid, :cid, :fid, :amt) RETURNING id"
        ), {"jid": job_id, "cid": user["id"], "fid": freelancer_id, "amt": amount})
        escrow_id = result.scalar()

    notify_and_email(
        user["id"],
        f"You funded escrow with ${amount:.2f} for '{job['title']}'.",
        "success",
        email_subject=f"Escrow funded — {job['title']}",
        email_body=(
            f"You funded escrow for '{job['title']}' with ${amount:.2f}.\n\n"
            "The funds are now held until you release or refund them."
        ),
        email_html=html_email(
            "Escrow funded successfully",
            f"""<p>You locked <strong style="color:#2dd4bf">${amount:.2f}</strong> in escrow for <strong style="color:#e5edf5">{job['title']}</strong>.</p>
            <p>The freelancer has been notified and can now begin work. Once they submit their delivery, you can approve it to release the funds.</p>""",
            cta_label="View Project", cta_url=f"/jobs/{job_id}",
        ),
        action_url="/escrow",
    )
    if freelancer_id:
        notify_and_email(
            freelancer_id,
            f"${amount:.2f} was locked in escrow for '{job['title']}'.",
            "success",
            email_subject=f"Escrow funded — {job['title']}",
            email_body=(
                f"The client funded escrow for '{job['title']}' with ${amount:.2f}.\n\n"
                "You can begin work knowing the funds are secured."
            ),
            email_html=html_email(
                "Escrow is funded — you can begin work",
                f"""<p>The client locked <strong style="color:#2dd4bf">${amount:.2f}</strong> in escrow for <strong style="color:#e5edf5">{job['title']}</strong>.</p>
                <p>The funds are secured. You can now submit your work for review when ready.</p>""",
                cta_label="Go to Project", cta_url=f"/jobs/{job_id}",
            ),
            action_url=f"/jobs/{job_id}",
        )
    return jsonify({"message": f"${amount:.2f} secured in escrow", "escrow_id": escrow_id}), 201


@app.route("/api/escrow/<int:escrow_id>/release", methods=["POST"])
@login_required
def api_escrow_release(escrow_id):
    user = current_user()
    escrow = query_db(
        """
        SELECT e.*, j.title AS job_title
        FROM escrow e
        JOIN jobs j ON e.job_id=j.id
        WHERE e.id=?
        """,
        [escrow_id],
        one=True,
    )
    if not escrow:
        return jsonify({"error": "Escrow not found"}), 404
    if escrow["client_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    if escrow["status"] != "held":
        return jsonify({"error": "Escrow is not in held status"}), 400
    submission = query_db(
        """
        SELECT *
        FROM work_submissions
        WHERE job_id=? AND freelancer_id=?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        [escrow["job_id"], escrow["freelancer_id"]],
        one=True,
    )
    if not submission or submission["status"] not in ("submitted", "disputed"):
        return jsonify({"error": "The freelancer must submit work before payment can be released"}), 400

    # Atomic: mark released + credit freelancer + complete job — all or nothing
    with get_engine().begin() as txn:
        txn.execute(text(
            "UPDATE escrow SET status='released', released_at=CURRENT_TIMESTAMP WHERE id=:eid"
        ), {"eid": escrow_id})
        txn.execute(text(
            "UPDATE work_submissions SET status='approved', reviewed_at=CURRENT_TIMESTAMP WHERE id=:sid"
        ), {"sid": submission["id"]})
        if escrow["freelancer_id"]:
            txn.execute(text(
                "UPDATE users SET balance=balance+:amt WHERE id=:fid"
            ), {"amt": escrow["amount"], "fid": escrow["freelancer_id"]})
        txn.execute(text(
            "UPDATE jobs SET status='completed' WHERE id=:jid"
        ), {"jid": escrow["job_id"]})

    notify_and_email(
        user["id"],
        f"You released ${escrow['amount']:.2f} for '{escrow['job_title']}'.",
        "success",
        email_subject=f"Payment released for {escrow['job_title']}",
        email_body=(
            f"You released ${escrow['amount']:.2f} from escrow for '{escrow['job_title']}'.\n\n"
            "The project has been marked completed."
        ),
        action_url="/escrow",
    )
    if escrow["freelancer_id"]:
        notify_and_email(
            escrow["freelancer_id"],
            f"${escrow['amount']:.2f} was released for '{escrow['job_title']}'.",
            "success",
            email_subject=f"Payment released for {escrow['job_title']}",
            email_body=(
                f"${escrow['amount']:.2f} was released to you for '{escrow['job_title']}'.\n\n"
                "The funds have been added to your balance."
            ),
            action_url="/escrow",
        )
    return jsonify({"message": f"${escrow['amount']:.2f} released to freelancer"}), 200


@app.route("/api/escrow/<int:escrow_id>/refund", methods=["POST"])
@login_required
def api_escrow_refund(escrow_id):
    user = current_user()
    escrow = query_db("SELECT * FROM escrow WHERE id=?", [escrow_id], one=True)
    if not escrow:
        return jsonify({"error": "Escrow not found"}), 404
    if escrow["client_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    if escrow["status"] != "held":
        return jsonify({"error": "Escrow is not in held status"}), 400
    submission = query_db(
        """
        SELECT id
        FROM work_submissions
        WHERE escrow_id=?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        [escrow_id],
        one=True,
    )
    if submission:
        return jsonify({"error": "Work has already been submitted. Please use the complaint flow so admin can review the case."}), 400

    with get_engine().begin() as txn:
        txn.execute(text(
            "UPDATE escrow SET status='refunded', released_at=CURRENT_TIMESTAMP WHERE id=:eid"
        ), {"eid": escrow_id})
        txn.execute(text(
            "UPDATE users SET balance=balance+:amt WHERE id=:uid"
        ), {"amt": escrow["amount"], "uid": user["id"]})
        txn.execute(text(
            "UPDATE jobs SET status='refunded' WHERE id=:jid"
        ), {"jid": escrow["job_id"]})

    notify_and_email(
        user["id"],
        f"You refunded ${escrow['amount']:.2f} for job #{escrow['job_id']}.",
        "warning",
        email_subject="Escrow refunded",
        email_body=(
            f"You refunded ${escrow['amount']:.2f} from escrow for job #{escrow['job_id']}.\n\n"
            "The amount has been returned to your balance."
        ),
        action_url="/escrow",
    )
    if escrow["freelancer_id"]:
        notify_and_email(
            escrow["freelancer_id"],
            f"Escrow for job #{escrow['job_id']} was refunded by the client.",
            "warning",
            email_subject="Escrow refunded",
            email_body=(
                f"The client refunded escrow for job #{escrow['job_id']}.\n\n"
                "No payment was released for this project."
            ),
            action_url=f"/jobs/{escrow['job_id']}",
        )
    return jsonify({"message": f"${escrow['amount']:.2f} refunded to your balance"}), 200


@app.route("/api/jobs/<int:job_id>/submit-work", methods=["POST"])
@login_required
def api_submit_work(job_id):
    user = current_user()
    if user["role"] != "freelancer":
        return jsonify({"error": "Only freelancers can submit work"}), 403

    accepted = query_db(
        """
        SELECT p.id, j.title, j.client_id
        FROM proposals p
        JOIN jobs j ON p.job_id=j.id
        WHERE p.job_id=? AND p.freelancer_id=? AND p.status='accepted'
        """,
        [job_id, user["id"]],
        one=True,
    )
    if not accepted:
        return jsonify({"error": "Only the accepted freelancer can submit work"}), 403

    escrow = query_db(
        "SELECT * FROM escrow WHERE job_id=? AND freelancer_id=? AND status='held'",
        [job_id, user["id"]],
        one=True,
    )
    if not escrow:
        return jsonify({"error": "Escrow must be funded before work can be submitted"}), 400

    if request.content_type and "multipart/form-data" in request.content_type:
        delivery_message = request.form.get("delivery_message", "").strip()
        delivery_url = request.form.get("delivery_url", "").strip()
        uploaded_zip = request.files.get("work_zip")
        uploaded_files = request.files.getlist("work_files")
        relative_paths = request.form.getlist("relative_paths")
    else:
        data = get_json_safe()
        delivery_message = data.get("delivery_message", "").strip()
        delivery_url = data.get("delivery_url", "").strip()
        uploaded_zip = None
        uploaded_files = []
        relative_paths = []

    if uploaded_zip and uploaded_zip.filename and not uploaded_zip.filename.lower().endswith(".zip"):
        return jsonify({"error": "Only .zip archives are allowed for direct file uploads"}), 400

    valid_folder_files = [item for item in uploaded_files if item and item.filename]
    if not delivery_message and not delivery_url and not uploaded_zip and not valid_folder_files:
        return jsonify({"error": "Add a delivery note, work link, zip file, or folder upload"}), 400

    archive_name = ""
    archive_path = ""
    if uploaded_zip and uploaded_zip.filename:
        archive_name, archive_path = save_submission_archive(
            job_id,
            user["id"],
            uploaded_zip=uploaded_zip,
        )
    elif valid_folder_files:
        archive_name, archive_path = save_submission_archive(
            job_id,
            user["id"],
            uploaded_files=valid_folder_files,
            relative_paths=relative_paths,
        )

    submission_id = mutate_db(
        """
        INSERT INTO work_submissions (job_id, freelancer_id, escrow_id, delivery_message, delivery_url, upload_archive_name, upload_archive_path, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [job_id, user["id"], escrow["id"], delivery_message, delivery_url, archive_name, archive_path, "submitted"],
    )
    mutate_db("UPDATE jobs SET status='submitted' WHERE id=?", [job_id])

    notify_and_email(
        accepted["client_id"],
        f"{user.get('full_name') or user['username']} submitted work for '{accepted['title']}'.",
        "info",
        email_subject=f"Work submitted for {accepted['title']}",
        email_body=(
            f"{user.get('full_name') or user['username']} submitted work for '{accepted['title']}'.\n\n"
            f"Delivery note:\n{delivery_message or 'Shared via link only.'}\n\n"
            f"Work link: {delivery_url or 'No external link provided.'}\n"
            f"Archive attached in app: {'Yes' if archive_path else 'No'}"
        ),
        action_url=f"/jobs/{job_id}",
    )
    return jsonify({"message": "Work submitted successfully. The client can now review it.", "submission_id": submission_id}), 201


@app.route("/api/submissions/<int:submission_id>/approve", methods=["POST"])
@login_required
def api_approve_submission(submission_id):
    user = current_user()
    if user["role"] != "client":
        return jsonify({"error": "Only clients can approve submitted work"}), 403

    submission = query_db(
        """
        SELECT ws.*, j.client_id, j.title AS job_title, e.amount, e.status AS escrow_status
        FROM work_submissions ws
        JOIN jobs j ON ws.job_id=j.id
        LEFT JOIN escrow e ON ws.escrow_id=e.id
        WHERE ws.id=?
        """,
        [submission_id],
        one=True,
    )
    if not submission:
        return jsonify({"error": "Submission not found"}), 404
    if submission["client_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    if submission["status"] == "approved":
        return jsonify({"error": "This submission has already been approved"}), 400
    if submission["escrow_status"] != "held":
        return jsonify({"error": "Escrow is not available for release"}), 400

    with get_engine().begin() as txn:
        txn.execute(text(
            "UPDATE work_submissions SET status='approved', reviewed_at=CURRENT_TIMESTAMP WHERE id=:sid"
        ), {"sid": submission_id})
        txn.execute(text(
            "UPDATE escrow SET status='released', released_at=CURRENT_TIMESTAMP WHERE id=:eid"
        ), {"eid": submission["escrow_id"]})
        txn.execute(text(
            "UPDATE users SET balance=balance+:amt WHERE id=:fid"
        ), {"amt": submission["amount"], "fid": submission["freelancer_id"]})
        txn.execute(text(
            "UPDATE jobs SET status='completed' WHERE id=:jid"
        ), {"jid": submission["job_id"]})
        txn.execute(text(
            "UPDATE complaints SET status='resolved_by_client', resolution_action='released', resolved_at=CURRENT_TIMESTAMP WHERE submission_id=:sid AND status='open'"
        ), {"sid": submission_id})

    notify_and_email(
        submission["freelancer_id"],
        f"Your work for '{submission['job_title']}' was approved and paid.",
        "success",
        email_subject=f"Payment released — {submission['job_title']}",
        email_body=(
            f"Your submitted work for '{submission['job_title']}' was approved.\n\n"
            f"${submission['amount']:.2f} has been released from escrow."
        ),
        email_html=html_email(
            "💰 Payment released!",
            f"""<p>Your work on <strong style="color:#e5edf5">{submission['job_title']}</strong> was approved by the client.</p>
            <p><strong style="color:#2dd4bf;font-size:22px">${submission['amount']:.2f}</strong> has been added to your balance.</p>""",
            cta_label="View Earnings", cta_url="/escrow",
        ),
        action_url=f"/jobs/{submission['job_id']}",
    )
    notify_and_email(
        user["id"],
        f"You approved the submitted work for '{submission['job_title']}'.",
        "success",
        email_subject=f"Work approved — {submission['job_title']}",
        email_body=(
            f"You approved the submitted work for '{submission['job_title']}'.\n\n"
            f"${submission['amount']:.2f} has been released from escrow."
        ),
        email_html=html_email(
            "Work approved & project complete",
            f"""<p>You approved the delivery for <strong style="color:#e5edf5">{submission['job_title']}</strong>.</p>
            <p><strong style="color:#2dd4bf;font-size:22px">${submission['amount']:.2f}</strong> was released to the freelancer. The project is now complete.</p>""",
            cta_label="View Escrow", cta_url="/escrow",
        ),
        action_url=f"/jobs/{submission['job_id']}",
    )
    return jsonify({"message": "Work approved and payment released"}), 200


@app.route("/api/submissions/<int:submission_id>/request-changes", methods=["POST"])
@login_required
def api_request_submission_changes(submission_id):
    user = current_user()
    if user["role"] != "client":
        return jsonify({"error": "Only clients can request changes on submitted work"}), 403

    submission = query_db(
        """
        SELECT ws.*, j.client_id, j.title AS job_title, e.status AS escrow_status
        FROM work_submissions ws
        JOIN jobs j ON ws.job_id=j.id
        LEFT JOIN escrow e ON ws.escrow_id=e.id
        WHERE ws.id=?
        """,
        [submission_id],
        one=True,
    )
    if not submission:
        return jsonify({"error": "Submission not found"}), 404
    if submission["client_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    if submission["status"] == "approved":
        return jsonify({"error": "Approved work can no longer be sent back for changes"}), 400
    if submission["escrow_status"] != "held":
        return jsonify({"error": "Changes can only be requested while escrow is still held"}), 400

    open_complaint = query_db(
        "SELECT id FROM complaints WHERE submission_id=? AND status='open'",
        [submission_id],
        one=True,
    )
    if open_complaint:
        return jsonify({"error": "An open complaint already exists for this delivery"}), 400

    data = get_json_safe()
    feedback = data.get("feedback", "").strip()
    if len(feedback) < 20:
        return jsonify({"error": "Please describe the requested changes in at least 20 characters and keep them within the original job requirements"}), 400

    with get_engine().begin() as txn:
        txn.execute(text(
            """
            UPDATE work_submissions
            SET status='changes_requested',
                client_feedback=:feedback,
                reviewed_at=CURRENT_TIMESTAMP
            WHERE id=:sid
            """
        ), {"feedback": feedback, "sid": submission_id})
        txn.execute(text(
            "UPDATE jobs SET status='changes_requested' WHERE id=:jid"
        ), {"jid": submission["job_id"]})

    notify_and_email(
        submission["freelancer_id"],
        f"Changes were requested for '{submission['job_title']}'.",
        "warning",
        email_subject=f"Changes requested for {submission['job_title']}",
        email_body=(
            f"The client requested changes for '{submission['job_title']}'.\n\n"
            "Requested revisions should stay within the original project scope.\n\n"
            f"Client feedback:\n{feedback}"
        ),
        action_url=f"/jobs/{submission['job_id']}",
    )
    return jsonify({"message": "Change request sent to the freelancer"}), 200


@app.route("/api/jobs/<int:job_id>/complaints", methods=["POST"])
@login_required
def api_file_complaint(job_id):
    user = current_user()
    if user["role"] not in ("client", "freelancer"):
        return jsonify({"error": "Only clients or freelancers can file complaints"}), 403

    job = query_db("SELECT * FROM jobs WHERE id=?", [job_id], one=True)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    accepted = query_db(
        "SELECT * FROM proposals WHERE job_id=? AND status='accepted'",
        [job_id],
        one=True,
    )
    if not accepted:
        return jsonify({"error": "No accepted proposal exists for this job"}), 400

    if user["role"] == "client" and job["client_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    if user["role"] == "freelancer" and accepted["freelancer_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403

    data = get_json_safe()
    message = data.get("message", "").strip()
    if len(message) < 15:
        return jsonify({"error": "Complaint details must be at least 15 characters"}), 400

    escrow = query_db("SELECT * FROM escrow WHERE job_id=? ORDER BY created_at DESC LIMIT 1", [job_id], one=True)
    submission = query_db(
        "SELECT * FROM work_submissions WHERE job_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        [job_id],
        one=True,
    )
    against_user_id = accepted["freelancer_id"] if user["role"] == "client" else job["client_id"]

    complaint_id = mutate_db(
        """
        INSERT INTO complaints (job_id, escrow_id, submission_id, complainant_id, against_user_id, message, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [
            job_id,
            escrow["id"] if escrow else None,
            submission["id"] if submission else None,
            user["id"],
            against_user_id,
            message,
            "open",
        ],
    )

    if submission:
        mutate_db("UPDATE work_submissions SET status='disputed' WHERE id=?", [submission["id"]])
    mutate_db("UPDATE jobs SET status='disputed' WHERE id=?", [job_id])

    email_admin(
        f"Complaint opened for {job['title']}",
        (
            f"A complaint was filed for '{job['title']}'.\n\n"
            f"Complainant: {user.get('full_name') or user['username']}\n"
            f"Message:\n{message}"
        ),
    )
    notify_and_email(
        against_user_id,
        f"A complaint was filed on '{job['title']}'. An admin will review it.",
        "warning",
        email_subject=f"Complaint opened for {job['title']}",
        email_body=(
            f"A complaint was filed on '{job['title']}'.\n\n"
            "An admin will review the case and decide the outcome."
        ),
        action_url=f"/jobs/{job_id}",
    )
    notify(
        user["id"],
        f"Your complaint for '{job['title']}' has been successfully submitted.",
        "success",
        f"/jobs/{job_id}",
    )
    return jsonify({"message": "Your complaint has been successfully submitted.", "complaint_id": complaint_id}), 201


@app.route("/api/admin/complaints/<int:complaint_id>/resolve", methods=["POST"])
@login_required
@admin_required
def api_admin_resolve_complaint(complaint_id):
    complaint = query_db(
        """
        SELECT c.*, j.title AS job_title, e.amount, e.status AS escrow_status, e.client_id, e.freelancer_id
        FROM complaints c
        JOIN jobs j ON c.job_id=j.id
        LEFT JOIN escrow e ON c.escrow_id=e.id
        WHERE c.id=?
        """,
        [complaint_id],
        one=True,
    )
    if not complaint:
        return jsonify({"error": "Complaint not found"}), 404
    if complaint["status"] != "open":
        return jsonify({"error": "Complaint has already been resolved"}), 400

    data = get_json_safe()
    action = data.get("action", "").strip().lower()
    admin_notes = data.get("admin_notes", "").strip()
    if action not in ("release", "refund", "close"):
        return jsonify({"error": "Action must be release, refund, or close"}), 400

    resolution_status = "resolved_closed"
    with get_engine().begin() as txn:
        if action == "release":
            if complaint["escrow_status"] != "held":
                return jsonify({"error": "Escrow cannot be released for this complaint"}), 400
            txn.execute(text(
                "UPDATE escrow SET status='released', released_at=CURRENT_TIMESTAMP WHERE id=:eid"
            ), {"eid": complaint["escrow_id"]})
            txn.execute(text(
                "UPDATE users SET balance=balance+:amt WHERE id=:fid"
            ), {"amt": complaint["amount"], "fid": complaint["freelancer_id"]})
            txn.execute(text(
                "UPDATE jobs SET status='completed' WHERE id=:jid"
            ), {"jid": complaint["job_id"]})
            if complaint["submission_id"]:
                txn.execute(text(
                    "UPDATE work_submissions SET status='approved', reviewed_at=CURRENT_TIMESTAMP WHERE id=:sid"
                ), {"sid": complaint["submission_id"]})
            resolution_status = "resolved_uphold_freelancer"
        elif action == "refund":
            if complaint["escrow_status"] != "held":
                return jsonify({"error": "Escrow cannot be refunded for this complaint"}), 400
            txn.execute(text(
                "UPDATE escrow SET status='refunded', released_at=CURRENT_TIMESTAMP WHERE id=:eid"
            ), {"eid": complaint["escrow_id"]})
            txn.execute(text(
                "UPDATE users SET balance=balance+:amt WHERE id=:cid"
            ), {"amt": complaint["amount"], "cid": complaint["client_id"]})
            txn.execute(text(
                "UPDATE jobs SET status='refunded' WHERE id=:jid"
            ), {"jid": complaint["job_id"]})
            if complaint["submission_id"]:
                txn.execute(text(
                    "UPDATE work_submissions SET status='rejected', reviewed_at=CURRENT_TIMESTAMP, client_feedback=:notes WHERE id=:sid"
                ), {"sid": complaint["submission_id"], "notes": admin_notes or "Admin refunded escrow after review."})
            resolution_status = "resolved_uphold_client"
        else:
            txn.execute(text(
                "UPDATE jobs SET status='in_progress' WHERE id=:jid"
            ), {"jid": complaint["job_id"]})
            if complaint["submission_id"]:
                txn.execute(text(
                    "UPDATE work_submissions SET status='submitted', client_feedback=:notes WHERE id=:sid"
                ), {"sid": complaint["submission_id"], "notes": admin_notes})

        txn.execute(text(
            """
            UPDATE complaints
            SET status=:status,
                admin_notes=:notes,
                resolution_action=:action,
                resolved_at=CURRENT_TIMESTAMP
            WHERE id=:cid
            """
        ), {"status": resolution_status, "notes": admin_notes, "action": action, "cid": complaint_id})

    if complaint["client_id"]:
        notify_and_email(
            complaint["client_id"],
            f"Admin resolved the complaint on '{complaint['job_title']}' with action: {action}.",
            "info",
            email_subject=f"Complaint resolved for {complaint['job_title']}",
            email_body=(
                f"An admin resolved the complaint on '{complaint['job_title']}'.\n\n"
                f"Action: {action}\n"
                f"Notes: {admin_notes or 'No additional notes.'}"
            ),
            action_url=f"/jobs/{complaint['job_id']}",
        )
    if complaint["freelancer_id"]:
        notify_and_email(
            complaint["freelancer_id"],
            f"Admin resolved the complaint on '{complaint['job_title']}' with action: {action}.",
            "info",
            email_subject=f"Complaint resolved for {complaint['job_title']}",
            email_body=(
                f"An admin resolved the complaint on '{complaint['job_title']}'.\n\n"
                f"Action: {action}\n"
                f"Notes: {admin_notes or 'No additional notes.'}"
            ),
            action_url=f"/jobs/{complaint['job_id']}",
        )
    return jsonify({"message": f"Complaint resolved with action: {action}"}), 200


@app.route("/api/ai/generate-proposal", methods=["POST"])
@login_required
def api_generate_proposal():
    user = current_user()
    if user["role"] != "freelancer":
        return jsonify({"error": "Only freelancers can use the proposal generator"}), 403

    data = get_json_safe()
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"error": "job_id is required"}), 400

    job = query_db("SELECT * FROM jobs WHERE id=?", [job_id], one=True)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    style = data.get("style", "random")
    proposal_text, style_used = generate_proposal(
        job["title"],
        job["description"],
        job["skills_required"],
        user.get("full_name") or user["username"],
        user["skills"] or "",
        style=style,
    )
    return jsonify({"proposal": proposal_text, "style": style_used}), 200


@app.route("/api/ai/analyze-fraud", methods=["POST"])
@login_required
def api_analyze_fraud():
    data = get_json_safe()
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()

    if not title or not description:
        return jsonify({"error": "Title and description required"}), 400

    analysis = analyze_fraud_details(title, description)
    return jsonify(
        {
            "fraud_score": analysis["score"],
            "fraud_level": analysis["label"],
            "fraud_reasons": analysis["reasons"],
            "categories": analysis["categories"],
            "fraud_components": analysis["components"],
        }
    ), 200


@app.route("/api/profile", methods=["PUT"])
@login_required
def api_update_profile():
    user = current_user()
    data = get_json_safe()
    bio = data.get("bio", "").strip()
    skills = data.get("skills", "").strip()
    full_name = data.get("full_name", "").strip()

    mutate_db(
        "UPDATE users SET bio=?, skills=?, full_name=? WHERE id=?",
        [bio, skills, full_name or (user.get("full_name") or user["username"]), user["id"]],
    )
    session["full_name"] = full_name or user.get("full_name") or user["username"]
    return jsonify({"message": "Profile updated successfully"}), 200


@app.route("/api/notifications", methods=["GET"])
@login_required
def api_get_notifications():
    user = current_user()
    notifications = query_db(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 25",
        [user["id"]],
    )
    for notification in notifications:
        notification["created_at_iso"] = iso_datetime(notification.get("created_at"))
    unread = query_db(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0",
        [user["id"]],
        one=True,
    )["c"]
    return jsonify({"notifications": notifications, "unread": unread}), 200


@app.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def api_mark_notification_read(notification_id):
    user = current_user()
    mutate_db("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", [notification_id, user["id"]])
    return jsonify({"message": "Notification marked as read"}), 200


@app.route("/api/notifications/read", methods=["POST"])
@login_required
def api_mark_notifications_read():
    user = current_user()
    mutate_db("UPDATE notifications SET is_read=1 WHERE user_id=?", [user["id"]])
    return jsonify({"message": "All marked as read"}), 200


@app.route("/api/jobs/<int:job_id>/messages", methods=["POST"])
@login_required
def api_send_message(job_id):
    user = current_user()
    if user["role"] not in ("client", "freelancer"):
        return jsonify({"error": "Only clients and freelancers can send messages"}), 403

    job = query_db("SELECT id, title, client_id FROM jobs WHERE id=?", [job_id], one=True)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    accepted = query_db(
        "SELECT freelancer_id FROM proposals WHERE job_id=? AND status='accepted' LIMIT 1",
        [job_id],
        one=True,
    )
    if not accepted:
        return jsonify({"error": "Messaging unlocks once a proposal is accepted"}), 400

    if user["id"] not in (job["client_id"], accepted["freelancer_id"]):
        return jsonify({"error": "Not authorized to message on this job"}), 403

    data = get_json_safe()
    content = data.get("content", "").strip()
    if len(content) < 2:
        return jsonify({"error": "Message must be at least 2 characters"}), 400

    recipient_id = accepted["freelancer_id"] if user["id"] == job["client_id"] else job["client_id"]
    message_id = mutate_db(
        """
        INSERT INTO messages (job_id, sender_id, recipient_id, content)
        VALUES (?, ?, ?, ?)
        RETURNING id
        """,
        [job_id, user["id"], recipient_id, content],
    )
    notify(
        recipient_id,
        f"New message on '{job['title']}' from {user.get('full_name') or user['username']}.",
        "info",
        f"/jobs/{job_id}#project-chat",
    )
    return jsonify({"message": "Message sent successfully.", "message_id": message_id}), 201


@app.route("/api/stats", methods=["GET"])
@login_required
def api_stats():
    user = current_user()
    fresh_balance = query_db("SELECT balance FROM users WHERE id=?", [user["id"]], one=True)["balance"]

    if user["role"] == "client":
        stats = query_db(
            """
            SELECT
                (SELECT COUNT(*) FROM jobs WHERE client_id=:uid) AS total_jobs,
                (SELECT COUNT(*) FROM jobs WHERE client_id=:uid AND status='open') AS active_jobs,
                (SELECT COUNT(*) FROM proposals p JOIN jobs j ON p.job_id=j.id WHERE j.client_id=:uid) AS total_proposals,
                (SELECT COALESCE(SUM(amount),0) FROM escrow WHERE client_id=:uid AND status='held') AS escrow_held,
                (SELECT COUNT(*) FROM jobs WHERE client_id=:uid AND status='completed') AS completed_jobs
            """,
            {"uid": user["id"]},
            one=True,
        )
        return jsonify({**stats, "balance": fresh_balance}), 200

    stats = query_db(
        """
        SELECT
            (SELECT COUNT(*) FROM proposals WHERE freelancer_id=:uid) AS applied,
            (SELECT COUNT(*) FROM proposals WHERE freelancer_id=:uid AND status='accepted') AS accepted,
            (SELECT COUNT(*) FROM proposals WHERE freelancer_id=:uid AND status='pending') AS pending
        """,
        {"uid": user["id"]},
        one=True,
    )
    open_jobs = query_db(
        """
        SELECT j.*, COALESCE(u.full_name, u.username) AS client_name,
               (SELECT COUNT(*) FROM proposals WHERE job_id=j.id) AS proposal_count
        FROM jobs j
        JOIN users u ON j.client_id=u.id
        WHERE j.status='open'
        ORDER BY j.created_at DESC
        """
    )
    stats["available_jobs"] = len(match_jobs_for_freelancer(open_jobs, user))
    return jsonify({**stats, "balance": fresh_balance}), 200


@app.route("/api/ai/match-freelancers/<int:job_id>", methods=["GET"])
@login_required
def api_match_freelancers(job_id):
    """
    Returns the top skill-based matched freelancers for a job.
    Uses the existing weighted composite scorer (skill overlap + rating + experience).
    """
    user = current_user()
    if user["role"] != "client":
        return jsonify({"error": "Only clients can use freelancer matching"}), 403

    job = query_db("SELECT * FROM jobs WHERE id=? AND client_id=?", [job_id, user["id"]], one=True)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    freelancers = query_db("SELECT * FROM users WHERE role='freelancer'")
    matches = hybrid_match_freelancers(job, freelancers)
    return jsonify({"job_id": job_id, "method": "hybrid_semantic_business", "matches": matches, "total": len(matches)}), 200


@app.route("/api/ai/ml-match/<int:job_id>", methods=["GET"])
@login_required
def api_ml_match_freelancers(job_id):
    """
    TF-IDF semantic matching route.
    Scores freelancers based on full text similarity (job description vs skills+bio).
    Runs independently of the keyword-based matcher — does NOT replace it.
    Returns top 3 by ml_score.
    """
    user = current_user()
    if user["role"] != "client":
        return jsonify({"error": "Only clients can use freelancer matching"}), 403

    job = query_db("SELECT * FROM jobs WHERE id=? AND client_id=?", [job_id, user["id"]], one=True)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    freelancers = query_db("SELECT * FROM users WHERE role='freelancer'")

    try:
        ml_matches = ml_match_freelancers(dict(job), [dict(f) for f in freelancers])
    except Exception as exc:
        return jsonify({"error": f"ML matching failed: {str(exc)}"}), 500

    top3 = ml_matches[:3]
    return jsonify({
        "job_id":  job_id,
        "method":  "tfidf_cosine_similarity",
        "matches": top3,
        "total":   len(ml_matches),
    }), 200


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template("404.html", user=current_user()), 404


@app.errorhandler(500)
def server_error(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Server error"}), 500
    return render_template("500.html", user=current_user()), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)