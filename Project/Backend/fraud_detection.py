from __future__ import annotations

import os
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


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

FRAUD_EXEMPLARS = [
    "Urgent task, act now, payment in bitcoin after you message me on Telegram.",
    "Quick freelance job with crypto payment and external signup link to start immediately.",
    "Easy money side hustle, no experience needed, double your earnings fast.",
    "Simple task today only, trust me, no contract required, just send your details.",
    "Need someone ASAP, payment through wire transfer, move conversation off-platform.",
    "Short remote job, click external link, register, then get paid in USDT.",
    "Fast profit opportunity for freelancers, guaranteed income, limited time only.",
    "Looking for assistant right now, send bank account info to receive payment.",
    "Tiny project, informal arrangement, no NDA, no platform fees, start now.",
    "Data entry task with instant crypto payout and urgent turnaround tonight.",
    "Freelancer needed immediately, external website onboarding, payment after verification.",
    "Act now for a simple online job, passive income potential, no interview.",
    "Need help today only, payout by Zelle, continue on WhatsApp after reply.",
    "Quick admin task, no paperwork, easy cash, respond immediately for access.",
    "Urgent support role, click here to join, earnings increase with every referral.",
    "Small freelance task, make money fast, payment via Ethereum wallet.",
    "No formal process, just trust me and complete this quick assignment.",
    "Remote opportunity with guaranteed returns and direct transfer after signup.",
    "Immediate hire for a simple job, external portal required before instructions.",
    "Freelance assistant wanted now, send SSN and routing number for payroll setup.",
    "Limited-time contract, no experience needed, big reward for small effort.",
    "Need worker today, continue privately by DM, payment handled outside platform.",
    "Easy online project, crypto bonus included, start immediately with provided link.",
    "Fast turnaround task, no contract, unrealistic upside, respond right now.",
    "Urgent micro job with external redirect and suspicious payment promises.",
    "Very easy role, instant approval, click external site and begin earning today.",
    "Simple remote work with money order payment and no verification process.",
    "Freelancer gig offering guaranteed 10x returns after quick completion.",
    "Immediate remote assignment, off-platform chat required, no formal scope document.",
    "Quick task with cryptocurrency settlement and pressure to start within minutes.",
]

LEGIT_EXEMPLARS = [
    "Build a Flask dashboard with PostgreSQL, authentication, reporting filters, and weekly check-ins.",
    "Need a React developer to implement a responsive admin panel with clear deliverables and documented components.",
    "Looking for a Python engineer to build REST APIs, integrate PostgreSQL, and write deployment notes.",
    "Create a mobile-friendly landing page with approved Figma design, SEO basics, and realistic timeline.",
    "Seeking backend developer for invoice workflow automation, unit tests, and API documentation.",
    "Need data analyst to clean CSV files, produce dashboards, and summarize findings in a report.",
    "Freelancer required for WordPress site updates, plugin review, and staging deployment process.",
    "Build internal support tool with role-based access, audit logs, and admin reporting screens.",
    "Need UI designer to refine onboarding flow, supply component specs, and support one revision round.",
    "Implement Django booking system with email notifications, calendar sync, and acceptance testing.",
    "Looking for DevOps help setting up CI pipeline, environment variables, and deployment checklist.",
    "Create product recommendation feature with clear acceptance criteria, budget, and milestone delivery.",
    "Need copywriter for website rewrite with brand tone guide, page list, and review timeline.",
    "Freelance video editor needed for short marketing clips with references, schedule, and revision scope.",
    "Build e-commerce checkout improvements with Stripe integration, QA pass, and rollback plan.",
    "Seeking researcher to compare competitors, summarize insights, and deliver presentation slides.",
    "Need full-stack developer for bug fixes, admin tools, and structured handoff documentation.",
    "Implement search filters, pagination, and export support for an internal analytics module.",
    "Looking for machine learning engineer to improve ranking quality with evaluation metrics and logs.",
    "Design and build a chatbot dashboard with message history, tags, and moderation tools.",
    "Need QA specialist to test user flows, document issues, and verify release candidate fixes.",
    "Build portfolio website with CMS editing, contact form, and browser compatibility checks.",
    "Seeking Shopify expert for theme updates, product page tuning, and launch support.",
    "Create marketing automation scripts with clear scope, staging validation, and production checklist.",
    "Need freelancer to migrate data from legacy system into PostgreSQL with field mapping document.",
    "Build reporting API with authentication, pagination, rate limits, and integration notes.",
    "Looking for technical writer to document setup steps, architecture, and support procedures.",
    "Implement semantic matching feature with measurable ranking goals and realistic delivery timeline.",
    "Need contractor for customer portal enhancements with backlog items and milestone reviews.",
    "Develop admin workflow for dispute handling, audit history, and final QA verification.",
]

# Lazy-loaded — nothing runs at import time. First call to analyze_fraud_ai() triggers the fit.
_VECTORIZER = None
_FRAUD_VECTORS = None
_LEGIT_VECTORS = None


def _ensure_model():
    """Fit the TF-IDF vectorizer on first use instead of at import time."""
    global _VECTORIZER, _FRAUD_VECTORS, _LEGIT_VECTORS
    if _VECTORIZER is not None:
        return
    corpus = FRAUD_EXEMPLARS + LEGIT_EXEMPLARS
    _VECTORIZER = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    matrix = _VECTORIZER.fit_transform(corpus)
    _FRAUD_VECTORS = matrix[: len(FRAUD_EXEMPLARS)]
    _LEGIT_VECTORS = matrix[len(FRAUD_EXEMPLARS):]


def fraud_level_from_score(score):
    if score <= 2:
        return "Low"
    if score <= 5:
        return "Medium"
    return "High"


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
        "model": "rules_v1",
    }


def analyze_fraud_ai(title, description):
    _ensure_model()

    job_text = f"{title} {description}".strip()
    if not job_text:
        return {
            "score": 0,
            "label": "Low",
            "reasons": [],
            "confidence": 0,
            "model": "semantic_fraud_v1",
        }

    job_vector = _VECTORIZER.transform([job_text])
    fraud_similarity = cosine_similarity(job_vector, _FRAUD_VECTORS)[0]
    legit_similarity = cosine_similarity(job_vector, _LEGIT_VECTORS)[0]

    fraud_score_raw = max(fraud_similarity) if len(fraud_similarity) else 0.0
    legit_score_raw = max(legit_similarity) if len(legit_similarity) else 0.0

    normalized = fraud_score_raw / max(fraud_score_raw + legit_score_raw, 1e-6)
    score = round(normalized * 10)
    confidence = round(abs(fraud_score_raw - legit_score_raw) * 100)

    reasons = []
    if fraud_score_raw > legit_score_raw:
        reasons.append(
            {
                "flag": "High similarity to scam-like job patterns (e.g., urgency, external links)",
                "category": "AI Similarity",
                "weight": score,
                "source": "ai",
            }
        )
    elif score <= 2:
        reasons.append(
            {
                "flag": "Closer match to structured legitimate job descriptions",
                "category": "AI Similarity",
                "weight": 1,
                "source": "ai",
            }
        )

    return {
        "score": min(score, 10),
        "label": fraud_level_from_score(min(score, 10)),
        "reasons": reasons,
        "confidence": confidence,
        "fraud_similarity": round(fraud_score_raw * 100),
        "legit_similarity": round(legit_score_raw * 100),
        "model": "semantic_fraud_v1",
    }


def fraud_ai_mode():
    return os.environ.get("AI_MODE", "hybrid").strip().lower() or "hybrid"


def fraud_fallback_enabled():
    return os.environ.get("AI_FALLBACK_ENABLED", "true").strip().lower() == "true"


def analyze_fraud_hybrid(title, description):
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