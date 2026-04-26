#!/usr/bin/env python3
"""
FreeLancer Pro — AI-Powered Freelance Escrow Platform
Web Programming Course Project

Run this file to start the server:
    python3 run.py

Then open: http://localhost:5000
"""
import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'freelance.db')

def seed_demo_data():
    """Seed realistic demo data so the platform feels alive on first run."""
    from werkzeug.security import generate_password_hash
    import json

    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row

    # Check if already seeded
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        db.close()
        return

    print("  Seeding demo data...")

    users = [
        ('sarah_client', 'sarah@demo.com', generate_password_hash('demo123'), 'client', '', 'Startup founder looking for talented developers.', 4.8, 15, 5000.0),
        ('ahmed_client', 'ahmed@demo.com', generate_password_hash('demo123'), 'client', '', 'Digital agency owner with regular projects.', 4.6, 22, 3500.0),
        ('alex_dev', 'alex@demo.com', generate_password_hash('demo123'), 'freelancer', 'Python, Django, Flask, REST API, PostgreSQL', 'Full-stack Python developer with 4 years experience.', 4.9, 28, 2200.0),
        ('priya_design', 'priya@demo.com', generate_password_hash('demo123'), 'freelancer', 'React, JavaScript, CSS, Tailwind, Figma, UI/UX', 'Frontend engineer & UI designer. I build beautiful, fast web apps.', 4.7, 19, 1800.0),
        ('omar_fullstack', 'omar@demo.com', generate_password_hash('demo123'), 'freelancer', 'Node.js, React, MongoDB, Express, Python, AWS', 'Senior full-stack developer. Delivered 50+ projects on time.', 4.8, 34, 3100.0),
        ('lena_mobile', 'lena@demo.com', generate_password_hash('demo123'), 'freelancer', 'Flutter, React Native, Firebase, Swift, Kotlin', 'Mobile developer specializing in cross-platform apps.', 4.5, 12, 900.0),
    ]
    db.executemany(
        "INSERT INTO users (username,email,password,role,skills,bio,rating,total_reviews,balance) VALUES (?,?,?,?,?,?,?,?,?)",
        users
    )

    # Get client IDs
    sarah_id = db.execute("SELECT id FROM users WHERE username='sarah_client'").fetchone()[0]
    ahmed_id = db.execute("SELECT id FROM users WHERE username='ahmed_client'").fetchone()[0]

    jobs = [
        (sarah_id, 'Full Stack E-Commerce Platform', 'We are building a modern e-commerce platform for a fashion brand. Need a developer to implement product catalog, cart, checkout with Stripe integration, order tracking, and admin dashboard. The platform should be responsive and SEO-friendly.', 'Python, Django, React, PostgreSQL, Stripe API', 1500.0, '2025-09-30', 'open', 0, 'Low', '[]'),
        (sarah_id, 'REST API for Mobile App', 'Our mobile team needs a well-documented REST API with JWT authentication, user management, push notifications, and real-time updates via WebSockets. Must include proper error handling and rate limiting.', 'Python, Flask, PostgreSQL, JWT, WebSockets', 900.0, '2025-08-20', 'open', 0, 'Low', '[]'),
        (ahmed_id, 'React Dashboard for Analytics', 'Build an internal analytics dashboard with interactive charts, date range filters, CSV/PDF export, role-based access, and live data updates. Dark mode required. Must be fast and handle large datasets.', 'React, JavaScript, Chart.js, CSS, REST API', 700.0, '2025-08-15', 'open', 1, 'Low', '[]'),
        (ahmed_id, 'WordPress to Next.js Migration', 'Migrate our company website from WordPress to Next.js with improved performance, custom CMS integration, SEO optimization, and blog functionality. Site has ~50 pages.', 'Next.js, React, TypeScript, Node.js, CMS', 1200.0, '2025-10-01', 'open', 0, 'Low', '[]'),
        (sarah_id, 'Mobile App UI/UX Design + Frontend', 'Design and implement the frontend of a fitness tracking mobile app. Need Figma mockups + React Native implementation with animations, onboarding flow, and workout logging screens.', 'React Native, Figma, JavaScript, UI/UX', 1100.0, '2025-09-15', 'open', 0, 'Low', '[]'),
    ]
    db.executemany(
        "INSERT INTO jobs (client_id,title,description,skills_required,budget,deadline,status,fraud_score,fraud_level,fraud_reasons) VALUES (?,?,?,?,?,?,?,?,?,?)",
        jobs
    )

    # Notifications
    db.execute("INSERT INTO notifications (user_id,message,type) VALUES (?,?,?)",
               [sarah_id, "Welcome to FreeLancer Pro, sarah_client! Your account is ready.", "success"])
    db.execute("INSERT INTO notifications (user_id,message,type) VALUES (?,?,?)",
               [ahmed_id, "Welcome to FreeLancer Pro, ahmed_client! Your account is ready.", "success"])

    db.commit()
    db.close()
    print("  Demo data seeded successfully!")
    print()
    print("  ─── DEMO ACCOUNTS ─────────────────────────────────────")
    print("  CLIENT 1:     sarah@demo.com     / demo123")
    print("  CLIENT 2:     ahmed@demo.com     / demo123")
    print("  FREELANCER 1: alex@demo.com      / demo123  (Python/Backend)")
    print("  FREELANCER 2: priya@demo.com     / demo123  (React/Design)")
    print("  FREELANCER 3: omar@demo.com      / demo123  (Full-Stack)")
    print("  FREELANCER 4: lena@demo.com      / demo123  (Mobile)")
    print("  ────────────────────────────────────────────────────────")

if __name__ == '__main__':
    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║     FreeLancer Pro — AI-Powered Escrow Platform      ║")
    print("  ║         Web Programming Course Project               ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()

    # Add current directory to path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from app import app, init_db

    print("  Initializing database...")
    init_db()
    print("  Database ready.")

    seed_demo_data()

    port = int(os.environ.get('PORT', 5000))
    print(f"  Starting server at: http://localhost:{port}")
    print("  Press CTRL+C to stop.")
    print()

    app.run(debug=False, port=port, host='0.0.0.0')
