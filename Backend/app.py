import os
import sqlite3
import secrets
import json
import re
import random
from datetime import datetime
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, g)
from werkzeug.security import generate_password_hash, check_password_hash

# ── FIX #1: Always resolve paths relative to THIS file, not the working directory.
# This means the app works no matter which folder you run it from.
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'Frontend', 'templates')
STATIC_DIR   = os.path.join(PROJECT_ROOT, 'Frontend', 'static')
DATABASE     = os.path.join(BASE_DIR, 'freelance.db')

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# ── FIX #2: Stable secret key so sessions survive server restarts during dev.
app.secret_key = os.environ.get('SECRET_KEY', 'freelancer-pro-dev-secret-2025-xK9mP')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ──────────────────────────────────────────────
# DATABASE HELPERS
# ──────────────────────────────────────────────
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
    return db

@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv  = cur.fetchall()
    return (rv[0] if rv else None) if one else rv

def mutate_db(query, args=()):
    db  = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur.lastrowid

def init_db():
    """Create all tables. Safe to call multiple times (IF NOT EXISTS)."""
    db = sqlite3.connect(DATABASE)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password      TEXT    NOT NULL,
            role          TEXT    NOT NULL CHECK(role IN ('client','freelancer')),
            skills        TEXT    DEFAULT '',
            bio           TEXT    DEFAULT '',
            rating        REAL    DEFAULT 0.0,
            total_reviews INTEGER DEFAULT 0,
            balance       REAL    DEFAULT 1000.0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id       INTEGER NOT NULL,
            title           TEXT    NOT NULL,
            description     TEXT    NOT NULL,
            skills_required TEXT    NOT NULL,
            budget          REAL    NOT NULL,
            deadline        TEXT    NOT NULL,
            status          TEXT    DEFAULT 'open',
            fraud_score     INTEGER DEFAULT 0,
            fraud_level     TEXT    DEFAULT 'Low',
            fraud_reasons   TEXT    DEFAULT '[]',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(client_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id        INTEGER NOT NULL,
            freelancer_id INTEGER NOT NULL,
            cover_letter  TEXT    NOT NULL,
            bid_amount    REAL    NOT NULL,
            timeline      TEXT    NOT NULL,
            status        TEXT    DEFAULT 'pending',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, freelancer_id),
            FOREIGN KEY(job_id)        REFERENCES jobs(id),
            FOREIGN KEY(freelancer_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS escrow (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id        INTEGER NOT NULL,
            client_id     INTEGER NOT NULL,
            freelancer_id INTEGER,
            amount        REAL    NOT NULL,
            status        TEXT    DEFAULT 'held',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            released_at   TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            message    TEXT    NOT NULL,
            type       TEXT    DEFAULT 'info',
            is_read    INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    db.commit()
    db.close()

# ══════════════════════════════════════════════════════════════
#  AI ENGINE — EscrowIQ Intelligence Module
#  Three AI features as specified in the project proposal:
#    1. Fraud Detection   — analyzes job postings for risk signals
#    2. Smart Matching    — weighted skill + rating scoring
#    3. Proposal Generator — context-aware cover letter builder
# ══════════════════════════════════════════════════════════════

# ── FEATURE 1: FRAUD DETECTION ──────────────────────────────
# Each rule: (regex_pattern, risk_weight, category, description)
FRAUD_RULES = [
    # Payment & financial red flags (highest weight)
    (r'\b(bitcoin|crypto|cryptocurrency|ethereum|usdt)\b',      5, "💰 Payment",    "Cryptocurrency payment method requested"),
    (r'\b(western union|wire transfer|money order|zelle)\b',    4, "💰 Payment",    "Untraceable payment method mentioned"),
    (r'\b(bank account|routing number|ssn|social security)\b',  5, "🔐 Personal",   "Sensitive financial information requested"),
    # Urgency & pressure tactics
    (r'\b(urgent|asap|immediately|right now|today only)\b',     2, "⚡ Urgency",    "Artificial urgency / pressure language"),
    (r'\b(limited time|expires soon|act now|last chance)\b',    2, "⚡ Urgency",    "Scarcity manipulation tactics"),
    # Unrealistic promises
    (r'\b(guaranteed|100%|risk.?free|no experience needed)\b',  2, "🎭 False Claims","Unrealistic or misleading guarantees"),
    (r'\b(get rich|easy money|passive income|make money fast)\b',3,"🎭 False Claims","Get-rich-quick language detected"),
    (r'\b(double your|triple your|10x your)\b',                 3, "🎭 False Claims","Unrealistic financial multiplier claims"),
    # Suspicious links / external redirection
    (r'\b(click here|visit link|go to|external site|dm me)\b',  3, "🔗 External",   "Suspicious redirection away from platform"),
    (r'https?://(?!escrow)',                                     2, "🔗 External",   "External URL embedded in posting"),
    # Spam / low-effort signals
    (r'(.)\1{4,}',                                              1, "📊 Quality",    "Repetitive characters (spam pattern)"),
    (r'[A-Z]{8,}',                                              1, "📊 Quality",    "Excessive use of capital letters"),
    # Vague or deceptive scope
    (r'\b(simple task|easy job|just need|only takes)\b',        1, "📝 Scope",      "Vague or minimised job scope"),
    (r'\b(no contract|no nda|trust me|informal)\b',             2, "📝 Scope",      "Attempts to bypass formal agreements"),
]

def analyze_fraud(title, description):
    """
    Analyzes a job posting for fraud indicators.
    Returns: (score 0-10, level str, detailed_reasons list, category_breakdown dict)
    """
    text       = (title + ' ' + description).lower()
    raw_score  = 0
    reasons    = []
    categories = {}

    for pattern, weight, category, reason in FRAUD_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            raw_score += weight
            reasons.append({'flag': reason, 'category': category, 'weight': weight})
            categories[category] = categories.get(category, 0) + weight

    # Content quality checks
    word_count = len(description.split())
    if word_count < 15:
        raw_score += 3
        reasons.append({'flag': 'Extremely short description (under 15 words)', 'category': '📊 Quality', 'weight': 3})
    elif word_count < 30:
        raw_score += 1
        reasons.append({'flag': 'Short description — limited job detail provided', 'category': '📊 Quality', 'weight': 1})

    # Title quality check
    if len(title.split()) < 3:
        raw_score += 1
        reasons.append({'flag': 'Very short job title', 'category': '📊 Quality', 'weight': 1})

    # Normalise score to 0-10
    score = min(raw_score, 10)
    if score <= 2:
        level = "Low"
    elif score <= 5:
        level = "Medium"
    else:
        level = "High"

    return score, level, reasons, categories

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

def match_freelancers(job_skills_str, all_freelancers):
    """
    Weighted matching algorithm:
      - Skill match score: % of job skills covered (with synonym expansion)
      - Rating boost: +10% for each star above 3.0
      - Experience boost: log-scaled from review count
      - Final composite score = 0.65 * skill_match + 0.25 * rating_norm + 0.10 * exp_norm
    Returns top 5 with full scoring breakdown.
    """
    job_skills = {normalise_skill(s) for s in job_skills_str.split(',') if s.strip()}
    if not job_skills:
        return []

    results = []
    for fl in all_freelancers:
        raw_fl_skills = [s for s in (fl.get('skills') or '').split(',') if s.strip()]
        if not raw_fl_skills:
            continue
        fl_skills = {normalise_skill(s) for s in raw_fl_skills}

        # Direct + synonym-expanded skill overlap
        matched   = job_skills & fl_skills
        # Also check partial substring matches for tech stacks
        partial   = set()
        for js in job_skills:
            for fs in fl_skills:
                if js in fs or fs in js:
                    matched.add(js)
                    partial.add(js)

        if not matched:
            continue

        skill_pct   = round(len(matched) / max(len(job_skills), 1) * 100)

        # Rating component: normalised 0-100, baseline at 3.0 stars
        rating      = float(fl.get('rating') or 0)
        rating_norm = max(0, min(100, (rating / 5.0) * 100))

        # Experience component: logarithmic scale (0 reviews = 0, 50 reviews ≈ 100)
        reviews     = int(fl.get('total_reviews') or 0)
        import math
        exp_norm    = min(100, math.log1p(reviews) / math.log1p(50) * 100)

        # Composite weighted score
        composite   = round(0.65 * skill_pct + 0.25 * rating_norm + 0.10 * exp_norm)

        results.append({
            'id':             fl['id'],
            'username':       fl['username'],
            'skills':         fl['skills'],
            'rating':         rating,
            'total_reviews':  reviews,
            'bio':            fl['bio'] or '',
            'matched_skills': sorted(list(matched)),
            'partial_matches':sorted(list(partial)),
            'missing_skills': sorted(list(job_skills - matched)),
            'skill_pct':      skill_pct,
            'rating_norm':    round(rating_norm),
            'exp_norm':       round(exp_norm),
            'composite':      composite,
            # Keep match_pct as alias for backward compat
            'match_pct':      composite,
        })

    results.sort(key=lambda x: (-x['composite'], -x['rating']))
    return results[:5]

# ── FEATURE 3: PROPOSAL GENERATOR ────────────────────────────
PROPOSAL_TEMPLATES = [
    {
        'style': 'Professional',
        'text': """Dear Hiring Manager,

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
        'style': 'Direct',
        'text': """Hello,

Your "{title}" project is exactly the type of work I specialise in. My background in {fl_skills} gives me the foundation needed to deliver this effectively.

Here is my understanding of what you need: {summary}. I have handled similar projects before and know the common challenges — I will navigate them proactively so you do not have to.

My approach: start fast, communicate clearly, and deliver exactly what was agreed. I do not over-promise. I use {skills} regularly in my work and can hit the ground running from day one.

Ready to start. Let us talk.

{name}""",
    },
    {
        'style': 'Detailed',
        'text': """Dear Client,

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

def generate_proposal(job_title, job_description, job_skills, freelancer_name, freelancer_skills, style='random'):
    """
    Generates a professional, context-aware proposal cover letter.
    style: 'random', 'Professional', 'Direct', or 'Detailed'
    Returns: (proposal_text, style_used)
    """
    if style == 'random' or style not in [t['style'] for t in PROPOSAL_TEMPLATES]:
        chosen = random.choice(PROPOSAL_TEMPLATES)
    else:
        chosen = next(t for t in PROPOSAL_TEMPLATES if t['style'] == style)

    skill_list = ', '.join(s.strip() for s in job_skills.split(',')[:4] if s.strip()) \
                 or 'the required technologies'
    fl_list    = ', '.join(s.strip() for s in freelancer_skills.split(',')[:4] if s.strip()) \
                 or 'relevant technologies'
    words      = job_description.split()
    summary    = ' '.join(words[:20]) + ('...' if len(words) > 20 else '')

    text = chosen['text'].format(
        title    = job_title,
        skills   = skill_list,
        fl_skills= fl_list,
        summary  = summary,
        name     = freelancer_name,
    )
    return text, chosen['style']

# ──────────────────────────────────────────────
# AUTH HELPERS
# ──────────────────────────────────────────────
def current_user():
    uid = session.get('user_id')
    if uid:
        return query_db("SELECT * FROM users WHERE id=?", [uid], one=True)
    return None

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return wrapper

def notify(user_id, message, ntype='info'):
    mutate_db("INSERT INTO notifications (user_id, message, type) VALUES (?,?,?)",
              [user_id, message, ntype])

# ──────────────────────────────────────────────
# ERROR HANDLERS  (FIX #3 — were missing entirely)
# ──────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Endpoint not found'}), 404
    try:
        return render_template('404.html', user=current_user()), 404
    except Exception:
        return "<h1>404 — Page Not Found</h1><a href='/'>Go home</a>", 404

@app.errorhandler(500)
def server_error(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    try:
        return render_template('500.html', user=current_user()), 500
    except Exception:
        return "<h1>500 — Server Error</h1><a href='/'>Go home</a>", 500

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({'error': 'Method not allowed'}), 405

# ──────────────────────────────────────────────
# PAGE ROUTES
# ──────────────────────────────────────────────
@app.route('/')
def index():
    # FIX #4: index route computes its own stats — no missing variables
    total_jobs   = query_db("SELECT COUNT(*) AS c FROM jobs", one=True)['c']
    total_users  = query_db("SELECT COUNT(*) AS c FROM users", one=True)['c']
    open_jobs_count = query_db("SELECT COUNT(*) AS c FROM jobs WHERE status='open'", one=True)['c']
    open_jobs = query_db("""
        SELECT j.id, j.title, j.budget, j.deadline, j.fraud_level, u.username AS client_name
        FROM jobs j
        JOIN users u ON u.id = j.client_id
        WHERE j.status = 'open'
        ORDER BY j.created_at DESC, j.id DESC
        LIMIT 4
    """)
    total_escrow = query_db(
        "SELECT COALESCE(SUM(amount),0) AS s FROM escrow WHERE status='held'", one=True)['s']
    return render_template('index.html', user=current_user(),
                           total_jobs=total_jobs, total_users=total_users,
                           open_jobs=open_jobs, open_jobs_count=open_jobs_count,
                           total_escrow=total_escrow)

@app.route('/register')
def register_page():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/login')
def login_page():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    if user['role'] == 'client':
        jobs = query_db(
            "SELECT * FROM jobs WHERE client_id=? ORDER BY created_at DESC", [user['id']])
        return render_template('dashboard_client.html', user=user, jobs=jobs)
    else:
        jobs = query_db("""
            SELECT j.*, u.username AS client_name
            FROM   jobs j JOIN users u ON j.client_id = u.id
            WHERE  j.status = 'open'
            ORDER  BY j.created_at DESC
        """)
        my_proposals = query_db("""
            SELECT p.*, j.title AS job_title, j.budget AS job_budget,
                   u.username AS client_name
            FROM   proposals p
            JOIN   jobs  j ON p.job_id    = j.id
            JOIN   users u ON j.client_id = u.id
            WHERE  p.freelancer_id = ?
            ORDER  BY p.created_at DESC
        """, [user['id']])
        return render_template('dashboard_freelancer.html', user=user,
                               jobs=jobs, my_proposals=my_proposals)

@app.route('/jobs')
@login_required
def jobs_page():
    user = current_user()
    jobs = query_db("""
        SELECT j.*, u.username AS client_name
        FROM   jobs j JOIN users u ON j.client_id = u.id
        WHERE  j.status = 'open'
        ORDER  BY j.created_at DESC
    """)
    return render_template('jobs.html', user=user, jobs=jobs)

@app.route('/jobs/<int:job_id>')
@login_required
def job_detail(job_id):
    user = current_user()
    job  = query_db("""
        SELECT j.*, u.username AS client_name, u.rating AS client_rating
        FROM   jobs j JOIN users u ON j.client_id = u.id
        WHERE  j.id = ?
    """, [job_id], one=True)
    if not job:
        return redirect(url_for('jobs_page'))

    proposals     = []
    escrow_info   = None
    user_proposal = None
    matched       = []

    if user['role'] == 'client' and job['client_id'] == user['id']:
        proposals = query_db("""
            SELECT p.*, u.username AS freelancer_name, u.skills AS freelancer_skills,
                   u.rating AS freelancer_rating, u.total_reviews, u.id AS freelancer_id
            FROM   proposals p JOIN users u ON p.freelancer_id = u.id
            WHERE  p.job_id = ?
            ORDER  BY p.created_at DESC
        """, [job_id])
        escrow_info = query_db("SELECT * FROM escrow WHERE job_id=?", [job_id], one=True)
        freelancers = query_db("SELECT * FROM users WHERE role='freelancer'")
        matched     = match_freelancers(job['skills_required'], [dict(f) for f in freelancers])

    if user['role'] == 'freelancer':
        user_proposal = query_db(
            "SELECT * FROM proposals WHERE job_id=? AND freelancer_id=?",
            [job_id, user['id']], one=True)

    # FIX #5: guard NULL / malformed fraud_reasons
    try:
        fraud_reasons = json.loads(job['fraud_reasons'] or '[]')
    except (json.JSONDecodeError, TypeError):
        fraud_reasons = []

    return render_template('job_detail.html', user=user, job=job,
                           proposals=proposals, escrow_info=escrow_info,
                           user_proposal=user_proposal, matched=matched,
                           fraud_reasons=fraud_reasons)

@app.route('/profile')
@login_required
def profile_page():
    return render_template('profile.html', user=current_user())

@app.route('/escrow')
@login_required
def escrow_page():
    user = current_user()
    if user['role'] == 'client':
        escrows = query_db("""
            SELECT e.*, j.title AS job_title, u.username AS freelancer_name
            FROM   escrow e
            JOIN   jobs  j ON e.job_id       = j.id
            LEFT JOIN users u ON e.freelancer_id = u.id
            WHERE  e.client_id = ?
            ORDER  BY e.created_at DESC
        """, [user['id']])
    else:
        escrows = query_db("""
            SELECT e.*, j.title AS job_title, u.username AS client_name
            FROM   escrow e
            JOIN   jobs  j ON e.job_id    = j.id
            JOIN   users u ON e.client_id = u.id
            WHERE  e.freelancer_id = ?
            ORDER  BY e.created_at DESC
        """, [user['id']])
    return render_template('escrow.html', user=user, escrows=escrows)

# ──────────────────────────────────────────────
# API — AUTH
# ──────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def api_register():
    d        = request.get_json(silent=True) or {}
    username = d.get('username', '').strip()
    email    = d.get('email',    '').strip().lower()
    password = d.get('password', '')
    role     = d.get('role',     '')
    skills   = d.get('skills',   '').strip()
    bio      = d.get('bio',      '').strip()

    if not all([username, email, password, role]):
        return jsonify({'error': 'All fields are required'}), 400
    if role not in ('client', 'freelancer'):
        return jsonify({'error': 'Invalid role selected'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400
    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify({'error': 'Enter a valid email address'}), 400

    if query_db("SELECT id FROM users WHERE username=?", [username], one=True):
        return jsonify({'error': 'Username already taken'}), 409
    if query_db("SELECT id FROM users WHERE email=?", [email], one=True):
        return jsonify({'error': 'Email already registered'}), 409

    hashed = generate_password_hash(password)
    uid    = mutate_db(
        "INSERT INTO users (username,email,password,role,skills,bio) VALUES (?,?,?,?,?,?)",
        [username, email, hashed, role, skills, bio])
    notify(uid, f"Welcome to FreeLancer Pro, {username}! Your account is ready.", 'success')
    return jsonify({'message': 'Account created successfully', 'redirect': '/login'}), 201

@app.route('/api/login', methods=['POST'])
def api_login():
    d        = request.get_json(silent=True) or {}
    email    = d.get('email',    '').strip().lower()
    password = d.get('password', '')
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    user = query_db("SELECT * FROM users WHERE email=?", [email], one=True)
    if not user or not check_password_hash(user['password'], password):
        return jsonify({'error': 'Invalid email or password'}), 401
    session['user_id'] = user['id']
    return jsonify({'message': 'Login successful',
                    'redirect': '/dashboard',
                    'role':     user['role']}), 200

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'redirect': '/'}), 200

# ──────────────────────────────────────────────
# API — JOBS
# ──────────────────────────────────────────────
@app.route('/api/jobs', methods=['POST'])
@login_required
def api_post_job():
    user = current_user()
    if user['role'] != 'client':
        return jsonify({'error': 'Only clients can post jobs'}), 403

    d           = request.get_json(silent=True) or {}
    title       = d.get('title',           '').strip()
    description = d.get('description',     '').strip()
    skills      = d.get('skills_required', '').strip()
    deadline    = d.get('deadline',        '').strip()

    try:
        budget = float(d.get('budget', 0))
        if budget <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'error': 'Budget must be a positive number'}), 400

    if not all([title, description, skills, deadline]):
        return jsonify({'error': 'All fields are required'}), 400

    fraud_score, fraud_level, fraud_reasons, fraud_cats = analyze_fraud(title, description)
    fraud_flags = [r['flag'] for r in fraud_reasons]
    jid = mutate_db("""
        INSERT INTO jobs
            (client_id,title,description,skills_required,budget,deadline,
             fraud_score,fraud_level,fraud_reasons)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, [user['id'], title, description, skills, budget, deadline,
          fraud_score, fraud_level, json.dumps(fraud_flags)])

    if fraud_level == 'High':
        notify(user['id'],
               f"Your job '{title}' was flagged HIGH risk. Consider revising the description.",
               'warning')
    return jsonify({'message': 'Job posted successfully', 'job_id': jid,
                    'fraud_level': fraud_level, 'fraud_score': fraud_score,
                    'fraud_reasons': fraud_flags,
                    'fraud_details': fraud_reasons}), 201

@app.route('/api/jobs/<int:job_id>', methods=['DELETE'])
@login_required
def api_delete_job(job_id):
    user = current_user()
    job  = query_db("SELECT * FROM jobs WHERE id=?", [job_id], one=True)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if job['client_id'] != user['id']:
        return jsonify({'error': 'Not authorised'}), 403
    mutate_db("DELETE FROM jobs WHERE id=?", [job_id])
    return jsonify({'message': 'Job deleted'}), 200

# ──────────────────────────────────────────────
# API — PROPOSALS
# ──────────────────────────────────────────────
@app.route('/api/proposals', methods=['POST'])
@login_required
def api_submit_proposal():
    user = current_user()
    if user['role'] != 'freelancer':
        return jsonify({'error': 'Only freelancers can submit proposals'}), 403

    d            = request.get_json(silent=True) or {}
    job_id       = d.get('job_id')
    cover_letter = d.get('cover_letter', '').strip()
    timeline     = d.get('timeline',     '').strip()

    try:
        bid_amount = float(d.get('bid_amount', 0))
        if bid_amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'error': 'Bid amount must be a positive number'}), 400

    if not all([job_id, cover_letter, timeline]):
        return jsonify({'error': 'All fields are required'}), 400

    job = query_db("SELECT * FROM jobs WHERE id=? AND status='open'", [job_id], one=True)
    if not job:
        return jsonify({'error': 'Job not found or no longer accepting proposals'}), 404

    if query_db("SELECT id FROM proposals WHERE job_id=? AND freelancer_id=?",
                [job_id, user['id']], one=True):
        return jsonify({'error': 'You have already applied to this job'}), 409

    pid = mutate_db(
        "INSERT INTO proposals (job_id,freelancer_id,cover_letter,bid_amount,timeline) VALUES (?,?,?,?,?)",
        [job_id, user['id'], cover_letter, bid_amount, timeline])
    notify(job['client_id'],
           f"New proposal from {user['username']} for '{job['title']}'", 'info')
    return jsonify({'message': 'Proposal submitted successfully', 'proposal_id': pid}), 201

@app.route('/api/proposals/<int:proposal_id>/accept', methods=['POST'])
@login_required
def api_accept_proposal(proposal_id):
    user     = current_user()
    proposal = query_db("""
        SELECT p.*, j.title AS job_title, j.client_id
        FROM   proposals p JOIN jobs j ON p.job_id = j.id
        WHERE  p.id = ?
    """, [proposal_id], one=True)
    if not proposal:
        return jsonify({'error': 'Proposal not found'}), 404
    if proposal['client_id'] != user['id']:
        return jsonify({'error': 'Not authorised'}), 403
    mutate_db("UPDATE proposals SET status='accepted' WHERE id=?", [proposal_id])
    mutate_db("UPDATE proposals SET status='rejected' WHERE job_id=? AND id!=?",
              [proposal['job_id'], proposal_id])
    mutate_db("UPDATE jobs SET status='in_progress' WHERE id=?", [proposal['job_id']])
    notify(proposal['freelancer_id'],
           f"Your proposal for '{proposal['job_title']}' was accepted!", 'success')
    return jsonify({'message': 'Proposal accepted'}), 200

@app.route('/api/proposals/<int:proposal_id>/reject', methods=['POST'])
@login_required
def api_reject_proposal(proposal_id):
    user     = current_user()
    proposal = query_db("""
        SELECT p.*, j.client_id, j.title AS job_title
        FROM   proposals p JOIN jobs j ON p.job_id = j.id
        WHERE  p.id = ?
    """, [proposal_id], one=True)
    if not proposal:
        return jsonify({'error': 'Proposal not found'}), 404
    if proposal['client_id'] != user['id']:
        return jsonify({'error': 'Not authorised'}), 403
    mutate_db("UPDATE proposals SET status='rejected' WHERE id=?", [proposal_id])
    notify(proposal['freelancer_id'],
           f"Your proposal for '{proposal['job_title']}' was not selected this time.", 'info')
    return jsonify({'message': 'Proposal rejected'}), 200

# ──────────────────────────────────────────────
# API — ESCROW
# ──────────────────────────────────────────────
@app.route('/api/escrow/deposit', methods=['POST'])
@login_required
def api_escrow_deposit():
    user = current_user()
    if user['role'] != 'client':
        return jsonify({'error': 'Only clients can deposit into escrow'}), 403

    d             = request.get_json(silent=True) or {}
    job_id        = d.get('job_id')
    freelancer_id = d.get('freelancer_id')

    try:
        amount = float(d.get('amount', 0))
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'error': 'Amount must be a positive number'}), 400

    job = query_db("SELECT * FROM jobs WHERE id=? AND client_id=?",
                   [job_id, user['id']], one=True)
    if not job:
        return jsonify({'error': 'Job not found or not yours'}), 404

    if query_db("SELECT id FROM escrow WHERE job_id=? AND status='held'", [job_id], one=True):
        return jsonify({'error': 'An active escrow already exists for this job'}), 409

    fresh = query_db("SELECT balance FROM users WHERE id=?", [user['id']], one=True)
    if fresh['balance'] < amount:
        return jsonify({'error': f"Insufficient balance. Available: ${fresh['balance']:.2f}"}), 400

    mutate_db("UPDATE users SET balance = balance - ? WHERE id=?", [amount, user['id']])
    eid = mutate_db(
        "INSERT INTO escrow (job_id,client_id,freelancer_id,amount) VALUES (?,?,?,?)",
        [job_id, user['id'], freelancer_id, amount])

    if freelancer_id:
        notify(freelancer_id,
               f"${amount:.2f} has been placed in escrow for '{job['title']}'", 'success')
    return jsonify({'message': f'${amount:.2f} deposited into escrow', 'escrow_id': eid}), 201

@app.route('/api/escrow/<int:escrow_id>/release', methods=['POST'])
@login_required
def api_escrow_release(escrow_id):
    user   = current_user()
    escrow = query_db("""
        SELECT e.*, j.title AS job_title
        FROM   escrow e JOIN jobs j ON e.job_id = j.id
        WHERE  e.id = ?
    """, [escrow_id], one=True)
    if not escrow:
        return jsonify({'error': 'Escrow not found'}), 404
    if escrow['client_id'] != user['id']:
        return jsonify({'error': 'Not authorised'}), 403
    if escrow['status'] != 'held':
        return jsonify({'error': 'Escrow is not in held status'}), 400

    mutate_db("UPDATE escrow SET status='released', released_at=CURRENT_TIMESTAMP WHERE id=?",
              [escrow_id])
    if escrow['freelancer_id']:
        mutate_db("UPDATE users SET balance = balance + ? WHERE id=?",
                  [escrow['amount'], escrow['freelancer_id']])
        notify(escrow['freelancer_id'],
               f"${escrow['amount']:.2f} released to your account for '{escrow['job_title']}'!",
               'success')
    mutate_db("UPDATE jobs SET status='completed' WHERE id=?", [escrow['job_id']])
    return jsonify({'message': f"${escrow['amount']:.2f} released to freelancer"}), 200

@app.route('/api/escrow/<int:escrow_id>/refund', methods=['POST'])
@login_required
def api_escrow_refund(escrow_id):
    user   = current_user()
    escrow = query_db("SELECT * FROM escrow WHERE id=?", [escrow_id], one=True)
    if not escrow:
        return jsonify({'error': 'Escrow not found'}), 404
    if escrow['client_id'] != user['id']:
        return jsonify({'error': 'Not authorised'}), 403
    if escrow['status'] != 'held':
        return jsonify({'error': 'Escrow is not in held status'}), 400

    mutate_db("UPDATE escrow SET status='refunded', released_at=CURRENT_TIMESTAMP WHERE id=?",
              [escrow_id])
    mutate_db("UPDATE users SET balance = balance + ? WHERE id=?",
              [escrow['amount'], user['id']])
    return jsonify({'message': f"${escrow['amount']:.2f} refunded to your account"}), 200

# ──────────────────────────────────────────────
# PAGE ROUTE — AI FEATURES
# ──────────────────────────────────────────────
@app.route('/ai')
@login_required
def ai_page():
    user = current_user()
    return render_template('ai_features.html', user=user,
                           proposal_styles=[t['style'] for t in PROPOSAL_TEMPLATES])

# ──────────────────────────────────────────────
# API — AI FEATURES
# ──────────────────────────────────────────────

# ── 1. FRAUD DETECTION — live real-time analyzer
@app.route('/api/ai/analyze-fraud', methods=['POST'])
@login_required
def api_analyze_fraud_live():
    d           = request.get_json(silent=True) or {}
    title       = d.get('title',       '').strip()
    description = d.get('description', '').strip()
    if not title and not description:
        return jsonify({'error': 'Provide title or description to analyze'}), 400
    score, level, reasons, categories = analyze_fraud(title or 'Untitled', description or title)
    tips = {
        'Low':    ['Your posting looks clean. Add more detail to attract better applicants.'],
        'Medium': ['Clarify your payment method (platform payments only).',
                   'Expand your description to at least 50 words.',
                   'Remove urgency language — it reduces freelancer trust.'],
        'High':   ['Remove any cryptocurrency or untraceable payment references.',
                   'Remove urgency/pressure language entirely.',
                   'Never request sensitive personal or financial information.',
                   'Write a clear, detailed description of the actual work required.'],
    }.get(level, [])
    return jsonify({'score': score, 'level': level,
                    'reasons': reasons, 'categories': categories,
                    'tips': tips}), 200

# ── 2. SMART MATCHING — on-demand skill matcher
@app.route('/api/ai/match', methods=['POST'])
@login_required
def api_match_by_skills():
    d          = request.get_json(silent=True) or {}
    skills_str = d.get('skills', '').strip()
    if not skills_str:
        return jsonify({'error': 'Provide at least one skill'}), 400
    freelancers = query_db("SELECT * FROM users WHERE role='freelancer'")
    matches     = match_freelancers(skills_str, [dict(f) for f in freelancers])
    return jsonify({
        'matches':       matches,
        'total_pool':    len(freelancers),
        'matched_count': len(matches),
        'job_skills':    [s.strip() for s in skills_str.split(',') if s.strip()],
    }), 200

# ── 2b. SMART MATCHING — per job (client job detail page)
@app.route('/api/ai/match-freelancers/<int:job_id>', methods=['GET'])
@login_required
def api_match_freelancers(job_id):
    user = current_user()
    job  = query_db("SELECT * FROM jobs WHERE id=? AND client_id=?",
                    [job_id, user['id']], one=True)
    if not job:
        return jsonify({'error': 'Job not found or not yours'}), 404
    freelancers = query_db("SELECT * FROM users WHERE role='freelancer'")
    matched     = match_freelancers(job['skills_required'], [dict(f) for f in freelancers])
    return jsonify({'matches': matched, 'job_skills': job['skills_required']}), 200

# ── 3. PROPOSAL GENERATOR — per job (job detail page)
@app.route('/api/ai/generate-proposal', methods=['POST'])
@login_required
def api_generate_proposal():
    user = current_user()
    if user['role'] != 'freelancer':
        return jsonify({'error': 'Only freelancers can use this feature'}), 403
    d      = request.get_json(silent=True) or {}
    job_id = d.get('job_id')
    style  = d.get('style', 'random')
    if not job_id:
        return jsonify({'error': 'job_id is required'}), 400
    job = query_db("SELECT * FROM jobs WHERE id=?", [job_id], one=True)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    text, style_used = generate_proposal(
        job['title'], job['description'], job['skills_required'],
        user['username'], user['skills'] or '', style=style)
    return jsonify({'proposal': text, 'style': style_used}), 200

# ── 3b. PROPOSAL GENERATOR — custom inputs (AI features demo page)
@app.route('/api/ai/generate-proposal-custom', methods=['POST'])
@login_required
def api_generate_proposal_custom():
    user = current_user()
    d = request.get_json(silent=True) or {}
    job_title       = d.get('job_title',       '').strip() or 'This Project'
    job_description = d.get('job_description', '').strip() or 'the described work'
    job_skills      = d.get('job_skills',      '').strip() or 'the required skills'
    style           = d.get('style', 'random')
    text, style_used = generate_proposal(
        job_title, job_description, job_skills,
        user['username'], user['skills'] or 'relevant technologies', style=style)
    return jsonify({'proposal': text, 'style': style_used}), 200

# ──────────────────────────────────────────────
# API — PROFILE / NOTIFICATIONS / STATS
# ──────────────────────────────────────────────
@app.route('/api/profile', methods=['PUT'])
@login_required
def api_update_profile():
    user   = current_user()
    d      = request.get_json(silent=True) or {}
    bio    = d.get('bio',    '').strip()
    skills = d.get('skills', '').strip()
    mutate_db("UPDATE users SET bio=?, skills=? WHERE id=?", [bio, skills, user['id']])
    return jsonify({'message': 'Profile updated successfully'}), 200

@app.route('/api/notifications', methods=['GET'])
@login_required
def api_get_notifications():
    user   = current_user()
    notifs = query_db("""
        SELECT * FROM notifications
        WHERE  user_id = ?
        ORDER  BY created_at DESC
        LIMIT  20
    """, [user['id']])
    return jsonify({'notifications': [dict(n) for n in notifs]}), 200

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_mark_notifications_read():
    user = current_user()
    mutate_db("UPDATE notifications SET is_read=1 WHERE user_id=?", [user['id']])
    return jsonify({'message': 'All marked as read'}), 200

@app.route('/api/stats', methods=['GET'])
@login_required
def api_stats():
    user    = current_user()
    balance = query_db("SELECT balance FROM users WHERE id=?", [user['id']], one=True)['balance']
    if user['role'] == 'client':
        total_jobs      = query_db("SELECT COUNT(*) AS c FROM jobs WHERE client_id=?",
                                   [user['id']], one=True)['c']
        active_jobs     = query_db("SELECT COUNT(*) AS c FROM jobs WHERE client_id=? AND status='open'",
                                   [user['id']], one=True)['c']
        total_proposals = query_db("""
            SELECT COUNT(*) AS c FROM proposals p
            JOIN   jobs j ON p.job_id = j.id WHERE j.client_id = ?
        """, [user['id']], one=True)['c']
        escrow_held     = query_db("""
            SELECT COALESCE(SUM(amount),0) AS s FROM escrow
            WHERE  client_id=? AND status='held'
        """, [user['id']], one=True)['s']
        return jsonify({'total_jobs': total_jobs, 'active_jobs': active_jobs,
                        'total_proposals': total_proposals, 'escrow_held': escrow_held,
                        'balance': balance})
    else:
        applied   = query_db("SELECT COUNT(*) AS c FROM proposals WHERE freelancer_id=?",
                             [user['id']], one=True)['c']
        accepted  = query_db("SELECT COUNT(*) AS c FROM proposals WHERE freelancer_id=? AND status='accepted'",
                             [user['id']], one=True)['c']
        available = query_db("SELECT COUNT(*) AS c FROM jobs WHERE status='open'", one=True)['c']
        return jsonify({'applied': applied, 'accepted': accepted,
                        'available_jobs': available, 'balance': balance})

# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    print(f"\n  Database : {DATABASE}")
    print(f"  Templates: {TEMPLATE_DIR}")
    print(f"  Static   : {STATIC_DIR}\n")
    app.run(debug=True, port=5000, host='0.0.0.0')
