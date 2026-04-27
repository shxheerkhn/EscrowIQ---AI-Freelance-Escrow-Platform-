from __future__ import annotations

import importlib
import os
import secrets
import sys
import unittest
from io import BytesIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "Backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def load_database_url():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DATABASE_URL":
            return value.strip().strip('"').strip("'")
    return None


DATABASE_URL = load_database_url()


@unittest.skipUnless(DATABASE_URL and "postgres" in DATABASE_URL, "PostgreSQL DATABASE_URL is required for integration tests.")
class EscrowIQFlowTests(unittest.TestCase):
    def setUp(self):
        self.run_id = secrets.token_hex(4)
        os.environ["SECRET_KEY"] = "test-secret-key"
        os.environ["DATABASE_URL"] = DATABASE_URL
        os.environ["ADMIN_EMAIL"] = "admin@example.com"
        os.environ["ADMIN_PASSWORD"] = "admin-secret"

        if "app" in sys.modules:
            self.app_module = importlib.reload(sys.modules["app"])
        else:
            self.app_module = importlib.import_module("app")

        self.app_module._engine = None
        self.app_module._schema_ready = False
        self.app_module.app.config["TESTING"] = True
        self.client = self.app_module.app.test_client()
        self.ctx = self.app_module.app.app_context()
        self.ctx.push()
        self.app_module.init_db()

        self.test_emails = []
        self.test_job_ids = []
        self.sent_emails = []
        self._original_deliver_email = self.app_module.deliver_email

        def fake_deliver_email(recipient, subject, text_body):
            self.sent_emails.append(
                {"recipient": recipient, "subject": subject, "body": text_body}
            )

        self.app_module.deliver_email = fake_deliver_email

    def tearDown(self):
        for job_id in self.test_job_ids:
            uploads = self.app_module.query_db(
                "SELECT upload_archive_path FROM work_submissions WHERE job_id=? AND upload_archive_path <> ''",
                [job_id],
            )
            for upload in uploads:
                archive_path = self.app_module.os.path.join(
                    self.app_module.SUBMISSIONS_DIR,
                    upload["upload_archive_path"],
                )
                if self.app_module.os.path.exists(archive_path):
                    self.app_module.os.remove(archive_path)
            self.app_module.mutate_db("DELETE FROM complaints WHERE job_id=?", [job_id])
            self.app_module.mutate_db("DELETE FROM work_submissions WHERE job_id=?", [job_id])
            self.app_module.mutate_db("DELETE FROM escrow WHERE job_id=?", [job_id])
            self.app_module.mutate_db("DELETE FROM proposals WHERE job_id=?", [job_id])
            self.app_module.mutate_db("DELETE FROM jobs WHERE id=?", [job_id])
        for email in self.test_emails:
            self.app_module.mutate_db("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE email=?)", [email])
            self.app_module.mutate_db("DELETE FROM email_codes WHERE email=?", [email])
            self.app_module.mutate_db("DELETE FROM users WHERE email=?", [email])
        self.app_module.deliver_email = self._original_deliver_email
        self.ctx.pop()
        if self.app_module._engine is not None:
            self.app_module._engine.dispose()

    def csrf_headers(self):
        with self.client.session_transaction() as sess:
            sess.setdefault("csrf_token", secrets.token_hex(16))
            return {"X-CSRF-Token": sess["csrf_token"]}

    def email(self, prefix):
        address = f"{prefix}_{self.run_id}@example.com"
        self.test_emails.append(address)
        return address

    def register_user(self, username, email, role, full_name=None, skills="", bio=""):
        response = self.client.post(
            "/api/register",
            json={
                "username": username,
                "full_name": full_name or username.title(),
                "email": email,
                "password": "secret123",
                "role": role,
                "skills": skills,
                "bio": bio,
            },
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        code_row = self.app_module.query_db(
            "SELECT code FROM email_codes WHERE email=? AND purpose='verify_email' ORDER BY created_at DESC LIMIT 1",
            [email],
            one=True,
        )
        self.assertIsNotNone(code_row)
        verify_response = self.client.post(
            "/api/auth/verify-email",
            json={"email": email, "code": code_row["code"]},
            headers=self.csrf_headers(),
        )
        self.assertEqual(verify_response.status_code, 200, verify_response.get_json())
        return response

    def notifications_for(self, email):
        return self.app_module.query_db(
            """
            SELECT n.message, n.type
            FROM notifications n
            JOIN users u ON n.user_id=u.id
            WHERE u.email=?
            ORDER BY n.created_at ASC, n.id ASC
            """,
            [email],
        )

    def login_user(self, email, password="secret123"):
        response = self.client.post(
            "/api/login",
            json={"email": email, "password": password},
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response

    def logout_user(self):
        response = self.client.post("/api/logout", headers=self.csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())

    def login_admin(self):
        response = self.client.post(
            "/api/login",
            json={"email": "admin@example.com", "password": "admin-secret"},
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response

    def post_job(self, title="Build dashboard", skills="Python, Flask", budget=800):
        response = self.client.post(
            "/api/jobs",
            json={
                "title": title,
                "description": "Build a production-ready analytics dashboard with auth, reporting, and polished UX.",
                "skills_required": skills,
                "budget": budget,
                "deadline": "2030-01-01",
            },
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        job_id = response.get_json()["job_id"]
        self.test_job_ids.append(job_id)
        return job_id

    def submit_proposal(self, job_id, bid_amount=750, timeline="2 weeks"):
        response = self.client.post(
            "/api/proposals",
            json={
                "job_id": job_id,
                "cover_letter": (
                    "I have shipped similar work before, can own the implementation end to end, "
                    "and will keep communication clean throughout delivery."
                ),
                "bid_amount": bid_amount,
                "timeline": timeline,
            },
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["proposal_id"]

    def submit_work(self, job_id, delivery_message="Work is ready for review.", delivery_url="https://example.com/demo"):
        response = self.client.post(
            f"/api/jobs/{job_id}/submit-work",
            json={"delivery_message": delivery_message, "delivery_url": delivery_url},
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["submission_id"]

    def submit_work_with_zip(self, job_id, filename="delivery.zip", content=b"zip-content"):
        response = self.client.post(
            f"/api/jobs/{job_id}/submit-work",
            data={
                "delivery_message": "Uploaded archive for review.",
                "delivery_url": "",
                "work_zip": (BytesIO(content), filename),
            },
            headers={"X-CSRF-Token": self.csrf_headers()["X-CSRF-Token"]},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["submission_id"]

    def bootstrap_accepted_proposal(self):
        client_email = self.email("client")
        freelancer_email = self.email("freelancer")
        self.register_user("client_" + self.run_id, client_email, "client", full_name="Client One")
        self.register_user(
            "freelancer_" + self.run_id,
            freelancer_email,
            "freelancer",
            full_name="Freelancer One",
            skills="Python, Flask, SQL",
        )

        self.login_user(client_email)
        job_id = self.post_job()
        self.logout_user()

        self.login_user(freelancer_email)
        proposal_id = self.submit_proposal(job_id)
        self.logout_user()

        self.login_user(client_email)
        accept_response = self.client.post(
            f"/api/proposals/{proposal_id}/accept",
            headers=self.csrf_headers(),
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.get_json())

        freelancer = self.app_module.query_db(
            "SELECT id, balance FROM users WHERE email=?",
            [freelancer_email],
            one=True,
        )
        client = self.app_module.query_db(
            "SELECT id, balance FROM users WHERE email=?",
            [client_email],
            one=True,
        )
        return {
            "job_id": job_id,
            "proposal_id": proposal_id,
            "freelancer_id": freelancer["id"],
            "client_balance": client["balance"],
            "freelancer_balance": freelancer["balance"],
            "client_email": client_email,
            "freelancer_email": freelancer_email,
        }

    def test_register_verify_and_login_flow(self):
        email = self.email("alice")
        register_response = self.register_user("alice_" + self.run_id, email, "client", full_name="Alice")
        self.assertIn("/verify-email", register_response.get_json()["redirect"])

        login_response = self.login_user(email)
        payload = login_response.get_json()
        self.assertEqual(payload["redirect"], "/dashboard")
        self.assertEqual(payload["role"], "client")
        notifications = self.notifications_for(email)
        self.assertTrue(any("Welcome to EscrowIQ" in item["message"] for item in notifications))
        self.assertTrue(any("Email verified" in item["message"] for item in notifications))

    def test_password_reset_flow(self):
        email = self.email("reset")
        self.register_user("reset_" + self.run_id, email, "client", full_name="Reset User")

        request_response = self.client.post(
            "/api/auth/request-password-reset",
            json={"email": email},
            headers=self.csrf_headers(),
        )
        self.assertEqual(request_response.status_code, 200, request_response.get_json())

        code_row = self.app_module.query_db(
            "SELECT code FROM email_codes WHERE email=? AND purpose='reset_password' ORDER BY created_at DESC LIMIT 1",
            [email],
            one=True,
        )
        self.assertIsNotNone(code_row)

        reset_response = self.client.post(
            "/api/auth/reset-password",
            json={"email": email, "code": code_row["code"], "password": "newsecret123"},
            headers=self.csrf_headers(),
        )
        self.assertEqual(reset_response.status_code, 200, reset_response.get_json())

        login_response = self.client.post(
            "/api/login",
            json={"email": email, "password": "newsecret123"},
            headers=self.csrf_headers(),
        )
        self.assertEqual(login_response.status_code, 200, login_response.get_json())

    def test_escrow_requires_the_accepted_freelancer(self):
        client_email = self.email("clienta")
        freelancer_a_email = self.email("freelancera")
        freelancer_b_email = self.email("freelancerb")
        self.register_user("clienta_" + self.run_id, client_email, "client", full_name="Client A")
        self.register_user(
            "freelancera_" + self.run_id,
            freelancer_a_email,
            "freelancer",
            full_name="Freelancer A",
            skills="Python, Flask",
        )
        self.register_user(
            "freelancerb_" + self.run_id,
            freelancer_b_email,
            "freelancer",
            full_name="Freelancer B",
            skills="Python, Flask",
        )

        self.login_user(client_email)
        job_id = self.post_job(title="Escrow test build")
        self.logout_user()

        self.login_user(freelancer_a_email)
        proposal_a = self.submit_proposal(job_id, bid_amount=700)
        self.logout_user()

        self.login_user(freelancer_b_email)
        self.submit_proposal(job_id, bid_amount=720)
        self.logout_user()

        self.login_user(client_email)
        accept_response = self.client.post(
            f"/api/proposals/{proposal_a}/accept",
            headers=self.csrf_headers(),
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.get_json())

        wrong_freelancer = self.app_module.query_db(
            "SELECT id FROM users WHERE email=?",
            [freelancer_b_email],
            one=True,
        )["id"]
        accepted_freelancer = self.app_module.query_db(
            "SELECT id FROM users WHERE email=?",
            [freelancer_a_email],
            one=True,
        )["id"]

        invalid_deposit = self.client.post(
            "/api/escrow/deposit",
            json={"job_id": job_id, "amount": 700, "freelancer_id": wrong_freelancer},
            headers=self.csrf_headers(),
        )
        self.assertEqual(invalid_deposit.status_code, 400, invalid_deposit.get_json())

        valid_deposit = self.client.post(
            "/api/escrow/deposit",
            json={"job_id": job_id, "amount": 700, "freelancer_id": accepted_freelancer},
            headers=self.csrf_headers(),
        )
        self.assertEqual(valid_deposit.status_code, 201, valid_deposit.get_json())

    def test_releasing_escrow_updates_balances_and_job_status(self):
        context = self.bootstrap_accepted_proposal()

        deposit_response = self.client.post(
            "/api/escrow/deposit",
            json={
                "job_id": context["job_id"],
                "amount": 750,
                "freelancer_id": context["freelancer_id"],
            },
            headers=self.csrf_headers(),
        )
        self.assertEqual(deposit_response.status_code, 201, deposit_response.get_json())
        escrow_id = deposit_response.get_json()["escrow_id"]

        self.logout_user()
        self.login_user(context["freelancer_email"])
        self.submit_work(
            context["job_id"],
            delivery_message="Implemented the requested dashboard, auth, and reporting flow.",
            delivery_url="https://example.com/submission",
        )
        self.logout_user()
        self.login_user(context["client_email"])

        release_response = self.client.post(
            f"/api/escrow/{escrow_id}/release",
            headers=self.csrf_headers(),
        )
        self.assertEqual(release_response.status_code, 200, release_response.get_json())

        job = self.app_module.query_db("SELECT status FROM jobs WHERE id=?", [context["job_id"]], one=True)
        freelancer = self.app_module.query_db(
            "SELECT balance FROM users WHERE id=?",
            [context["freelancer_id"]],
            one=True,
        )
        self.assertEqual(job["status"], "completed")
        self.assertEqual(freelancer["balance"], context["freelancer_balance"] + 750)

    def test_proposal_and_payment_events_create_notifications_and_emails(self):
        client_email = self.email("notifyclient")
        freelancer_email = self.email("notifyfreelancer")
        self.register_user("notifyclient_" + self.run_id, client_email, "client", full_name="Notify Client")
        self.register_user(
            "notifyfreelancer_" + self.run_id,
            freelancer_email,
            "freelancer",
            full_name="Notify Freelancer",
            skills="Python, Flask, PostgreSQL",
            bio="Backend engineer",
        )

        self.login_user(client_email)
        job_id = self.post_job(title="Notification test build")
        self.logout_user()

        self.login_user(freelancer_email)
        proposal_id = self.submit_proposal(job_id, bid_amount=680)
        self.logout_user()

        client_notifications = self.notifications_for(client_email)
        self.assertTrue(any("New proposal from" in item["message"] for item in client_notifications))
        self.assertTrue(any(msg["recipient"] == client_email and "New proposal for" in msg["subject"] for msg in self.sent_emails))

        self.login_user(client_email)
        accept_response = self.client.post(
            f"/api/proposals/{proposal_id}/accept",
            headers=self.csrf_headers(),
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.get_json())

        freelancer = self.app_module.query_db(
            "SELECT id FROM users WHERE email=?",
            [freelancer_email],
            one=True,
        )
        deposit_response = self.client.post(
            "/api/escrow/deposit",
            json={"job_id": job_id, "amount": 680, "freelancer_id": freelancer["id"]},
            headers=self.csrf_headers(),
        )
        self.assertEqual(deposit_response.status_code, 201, deposit_response.get_json())
        escrow_id = deposit_response.get_json()["escrow_id"]
        self.logout_user()

        self.login_user(freelancer_email)
        self.submit_work(
            job_id,
            delivery_message="Dashboard, auth, and deployment notes are ready for review.",
            delivery_url="https://example.com/final-work",
        )
        self.logout_user()

        self.login_user(client_email)

        release_response = self.client.post(
            f"/api/escrow/{escrow_id}/release",
            headers=self.csrf_headers(),
        )
        self.assertEqual(release_response.status_code, 200, release_response.get_json())

        freelancer_notifications = self.notifications_for(freelancer_email)
        self.assertTrue(any("was accepted" in item["message"] for item in freelancer_notifications))
        self.assertTrue(any("locked in escrow" in item["message"] for item in freelancer_notifications))
        self.assertTrue(any("was released" in item["message"] for item in freelancer_notifications))

        client_notifications = self.notifications_for(client_email)
        self.assertTrue(any("You funded escrow" in item["message"] for item in client_notifications))
        self.assertTrue(any("You released" in item["message"] for item in client_notifications))

        expected_subjects = {
            (client_email, "New proposal for"),
            (freelancer_email, "Proposal accepted for"),
            (client_email, "Escrow funded for"),
            (freelancer_email, "Escrow funded for"),
            (client_email, "Payment released for"),
            (freelancer_email, "Payment released for"),
        }
        for recipient, subject_prefix in expected_subjects:
            self.assertTrue(
                any(msg["recipient"] == recipient and msg["subject"].startswith(subject_prefix) for msg in self.sent_emails),
                f"Missing email {subject_prefix} for {recipient}",
            )

    def test_reject_and_refund_send_notifications_emails_and_update_job(self):
        client_email = self.email("refundclient")
        freelancer_a_email = self.email("refundfreelancer")
        freelancer_b_email = self.email("rejectfreelancer")
        self.register_user("refundclient_" + self.run_id, client_email, "client", full_name="Refund Client")
        self.register_user(
            "refundfreelancer_" + self.run_id,
            freelancer_a_email,
            "freelancer",
            full_name="Refund Freelancer",
            skills="Python, Flask",
            bio="Backend dev",
        )
        self.register_user(
            "rejectfreelancer_" + self.run_id,
            freelancer_b_email,
            "freelancer",
            full_name="Reject Freelancer",
            skills="Python, Flask",
            bio="Backend dev",
        )

        self.login_user(client_email)
        job_id = self.post_job(title="Refund flow build")
        self.logout_user()

        self.login_user(freelancer_a_email)
        proposal_a = self.submit_proposal(job_id, bid_amount=600)
        self.logout_user()

        self.login_user(freelancer_b_email)
        proposal_b = self.submit_proposal(job_id, bid_amount=620)
        self.logout_user()

        self.login_user(client_email)
        accept_response = self.client.post(
            f"/api/proposals/{proposal_a}/accept",
            headers=self.csrf_headers(),
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.get_json())

        freelancer_a = self.app_module.query_db("SELECT id FROM users WHERE email=?", [freelancer_a_email], one=True)
        deposit_response = self.client.post(
            "/api/escrow/deposit",
            json={"job_id": job_id, "amount": 600, "freelancer_id": freelancer_a["id"]},
            headers=self.csrf_headers(),
        )
        self.assertEqual(deposit_response.status_code, 201, deposit_response.get_json())
        escrow_id = deposit_response.get_json()["escrow_id"]

        refund_response = self.client.post(
            f"/api/escrow/{escrow_id}/refund",
            headers=self.csrf_headers(),
        )
        self.assertEqual(refund_response.status_code, 200, refund_response.get_json())

        job = self.app_module.query_db("SELECT status FROM jobs WHERE id=?", [job_id], one=True)
        escrow = self.app_module.query_db("SELECT status FROM escrow WHERE id=?", [escrow_id], one=True)
        self.assertEqual(job["status"], "refunded")
        self.assertEqual(escrow["status"], "refunded")

        freelancer_a_notifications = self.notifications_for(freelancer_a_email)
        freelancer_b_notifications = self.notifications_for(freelancer_b_email)
        client_notifications = self.notifications_for(client_email)
        self.assertTrue(any("was refunded by the client" in item["message"] for item in freelancer_a_notifications))
        self.assertTrue(any("was not selected" in item["message"] for item in freelancer_b_notifications))
        self.assertTrue(any("You refunded" in item["message"] for item in client_notifications))

        self.assertTrue(any(msg["recipient"] == freelancer_b_email and msg["subject"].startswith("Proposal update for") for msg in self.sent_emails))
        self.assertTrue(any(msg["recipient"] == client_email and msg["subject"] == "Escrow refunded" for msg in self.sent_emails))
        self.assertTrue(any(msg["recipient"] == freelancer_a_email and msg["subject"] == "Escrow refunded" for msg in self.sent_emails))

    def test_submit_work_and_admin_resolve_complaint(self):
        client_email = self.email("disputeclient")
        freelancer_email = self.email("disputefreelancer")
        self.register_user("disputeclient_" + self.run_id, client_email, "client", full_name="Dispute Client")
        self.register_user(
            "disputefreelancer_" + self.run_id,
            freelancer_email,
            "freelancer",
            full_name="Dispute Freelancer",
            skills="Python, Flask",
            bio="Ships dashboards",
        )

        self.login_user(client_email)
        job_id = self.post_job(title="Admin complaint test")
        self.logout_user()

        self.login_user(freelancer_email)
        proposal_id = self.submit_proposal(job_id, bid_amount=640)
        self.logout_user()

        self.login_user(client_email)
        accept_response = self.client.post(
            f"/api/proposals/{proposal_id}/accept",
            headers=self.csrf_headers(),
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.get_json())
        freelancer = self.app_module.query_db("SELECT id, balance FROM users WHERE email=?", [freelancer_email], one=True)
        client_before = self.app_module.query_db("SELECT balance FROM users WHERE email=?", [client_email], one=True)["balance"]
        deposit_response = self.client.post(
            "/api/escrow/deposit",
            json={"job_id": job_id, "amount": 640, "freelancer_id": freelancer["id"]},
            headers=self.csrf_headers(),
        )
        self.assertEqual(deposit_response.status_code, 201, deposit_response.get_json())
        self.logout_user()

        self.login_user(freelancer_email)
        submission_id = self.submit_work(
            job_id,
            delivery_message="Repository, live demo, and test credentials are all included.",
            delivery_url="https://example.com/repo",
        )
        self.logout_user()

        self.login_user(client_email)
        complaint_response = self.client.post(
            f"/api/jobs/{job_id}/complaints",
            json={"message": "The submission does not match the required reporting filters and auth flow."},
            headers=self.csrf_headers(),
        )
        self.assertEqual(complaint_response.status_code, 201, complaint_response.get_json())
        complaint_id = complaint_response.get_json()["complaint_id"]
        self.logout_user()

        self.login_admin()
        resolve_response = self.client.post(
            f"/api/admin/complaints/{complaint_id}/resolve",
            json={"action": "release", "admin_notes": "Freelancer delivered the requested scope after review."},
            headers=self.csrf_headers(),
        )
        self.assertEqual(resolve_response.status_code, 200, resolve_response.get_json())

        complaint = self.app_module.query_db("SELECT status, resolution_action FROM complaints WHERE id=?", [complaint_id], one=True)
        job = self.app_module.query_db("SELECT status FROM jobs WHERE id=?", [job_id], one=True)
        submission = self.app_module.query_db("SELECT status FROM work_submissions WHERE id=?", [submission_id], one=True)
        escrow = self.app_module.query_db("SELECT status FROM escrow WHERE job_id=?", [job_id], one=True)
        freelancer_after = self.app_module.query_db("SELECT balance FROM users WHERE email=?", [freelancer_email], one=True)["balance"]

        self.assertEqual(complaint["status"], "resolved_uphold_freelancer")
        self.assertEqual(complaint["resolution_action"], "release")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(submission["status"], "approved")
        self.assertEqual(escrow["status"], "released")
        self.assertEqual(freelancer_after, freelancer["balance"] + 640)

        client_notifications = self.notifications_for(client_email)
        freelancer_notifications = self.notifications_for(freelancer_email)
        self.assertTrue(any("submitted work" in item["message"] for item in client_notifications))
        self.assertTrue(any("complaint" in item["message"].lower() for item in freelancer_notifications))
        self.assertTrue(any("Admin resolved the complaint" in item["message"] for item in client_notifications))
        self.assertTrue(any("Admin resolved the complaint" in item["message"] for item in freelancer_notifications))

        self.assertTrue(any(msg["recipient"] == "admin@example.com" and msg["subject"].startswith("Complaint opened for") for msg in self.sent_emails))
        self.assertTrue(any(msg["recipient"] == client_email and msg["subject"].startswith("Complaint resolved for") for msg in self.sent_emails))
        self.assertTrue(any(msg["recipient"] == freelancer_email and msg["subject"].startswith("Complaint resolved for") for msg in self.sent_emails))

    def test_submit_work_accepts_zip_upload(self):
        context = self.bootstrap_accepted_proposal()

        deposit_response = self.client.post(
            "/api/escrow/deposit",
            json={
                "job_id": context["job_id"],
                "amount": 700,
                "freelancer_id": context["freelancer_id"],
            },
            headers=self.csrf_headers(),
        )
        self.assertEqual(deposit_response.status_code, 201, deposit_response.get_json())
        self.logout_user()

        self.login_user(context["freelancer_email"])
        submission_id = self.submit_work_with_zip(context["job_id"])

        submission = self.app_module.query_db(
            "SELECT upload_archive_name, upload_archive_path, status FROM work_submissions WHERE id=?",
            [submission_id],
            one=True,
        )
        self.assertEqual(submission["status"], "submitted")
        self.assertTrue(submission["upload_archive_name"].endswith(".zip"))
        archive_path = self.app_module.os.path.join(
            self.app_module.SUBMISSIONS_DIR,
            submission["upload_archive_path"],
        )
        self.assertTrue(self.app_module.os.path.exists(archive_path))


if __name__ == "__main__":
    unittest.main()
