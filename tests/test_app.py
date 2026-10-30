"""Account, privacy, and study API tests using isolated SQLite databases."""
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app import create_app


PASSWORD = "correct horse battery staple"
NOTES = "Mitosis is a process of cell division. It creates two genetically identical daughter cells."


class StudyMateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.app = create_app(self.app_config(self.db_path))
        self.client = self.app.test_client()
        self.register(self.client)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def app_config(path, **overrides):
        return {
            "TESTING": True,
            "DATABASE": path,
            "AI_DEMO_MODE": True,
            "AI_API_KEY": "",
            "MAX_NOTES_CHARS": 20000,
            **overrides,
        }

    @staticmethod
    def csrf_token(client):
        with client.session_transaction() as state:
            return state["csrf_token"]

    def register(self, client, name="Avery Student", email="avery@example.com"):
        client.get("/register")
        return client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(client),
                "name": name,
                "email": email,
                "password": PASSWORD,
                "confirm_password": PASSWORD,
            },
        )

    def api_post(self, client, path, body=None, include_csrf=True):
        headers = {}
        if include_csrf:
            headers["X-CSRF-Token"] = self.csrf_token(client)
        return client.post(path, json=body or {}, headers=headers)

    def api_put(self, client, path, body):
        return client.put(
            path,
            json=body,
            headers={"X-CSRF-Token": self.csrf_token(client)},
        )

    def test_account_pages_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/profile").status_code, 200)
        self.assertEqual(self.client.get("/api/health").json["status"], "ok")
        for path in ("/summarizer", "/quiz", "/flashcards", "/history", "/settings"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_private_pages_and_apis_require_sign_in(self):
        client = self.app.test_client()
        self.assertEqual(client.get("/").status_code, 302)
        client.get("/login")
        response = self.api_post(client, "/api/summarize", {"notes": NOTES})
        self.assertEqual(response.status_code, 401)
        response = client.get("/api/history")
        self.assertEqual(response.status_code, 401)

    def test_registration_login_and_logout(self):
        client = self.app.test_client()
        response = self.register(client, "New Student", "new-student@example.com")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get("/").status_code, 200)
        client.post("/logout", data={"csrf_token": self.csrf_token(client)})
        self.assertEqual(client.get("/").status_code, 302)
        client.get("/login")
        response = client.post(
            "/login",
            data={
                "csrf_token": self.csrf_token(client),
                "email": "NEW-STUDENT@example.com",
                "password": PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get("/").status_code, 200)

    def test_csrf_required_for_forms_and_json_mutations(self):
        client = self.app.test_client()
        client.get("/login")
        without_token = client.post("/login", data={"email": "nobody@example.com", "password": PASSWORD})
        self.assertEqual(without_token.status_code, 400)
        no_header = client.post("/api/summarize", json={"notes": NOTES})
        self.assertEqual(no_header.status_code, 400)
        with_header = self.api_post(client, "/api/summarize", {"notes": NOTES})
        self.assertEqual(with_header.status_code, 401)

    def test_empty_notes_are_rejected_after_sign_in(self):
        response = self.api_post(self.client, "/api/summarize", {"notes": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertIn("notes", response.json["error"].lower())

    def test_summary_history_is_persistent_and_user_scoped(self):
        generated = self.api_post(
            self.client, "/api/summarize", {"notes": NOTES, "subject": "Biology"}
        )
        self.assertEqual(generated.status_code, 200)
        saved = self.api_post(
            self.client,
            "/api/history/summary",
            {"content": generated.json["summary"], "subject": "Biology", "notes": NOTES},
        )
        self.assertEqual(saved.status_code, 201)
        detail = self.client.get(f"/api/history/{saved.json['id']}?type=summary")
        self.assertEqual(detail.json["subject"], "Biology")
        self.assertTrue(detail.json["content"])

        second_client = self.app.test_client()
        self.register(second_client, "Second Student", "second@example.com")
        self.assertEqual(second_client.get("/api/history").json["items"], [])
        self.assertEqual(
            second_client.get(f"/api/history/{saved.json['id']}?type=summary").status_code,
            404,
        )
        self.assertEqual(
            second_client.delete(
                f"/api/history/{saved.json['id']}?type=summary",
                headers={"X-CSRF-Token": self.csrf_token(second_client)},
            ).status_code,
            404,
        )

        restarted = create_app(self.app_config(self.db_path))
        restarted_client = restarted.test_client()
        restarted_client.get("/login")
        restarted_client.post(
            "/login",
            data={
                "csrf_token": self.csrf_token(restarted_client),
                "email": "avery@example.com",
                "password": PASSWORD,
            },
        )
        self.assertEqual(len(restarted_client.get("/api/history").json["items"]), 1)

    def test_quiz_keeps_key_private_and_scores_server_side(self):
        generated = self.api_post(
            self.client,
            "/api/quiz/generate",
            {"notes": NOTES, "count": 5, "subject": "Biology"},
        )
        self.assertEqual(generated.status_code, 200)
        self.assertNotIn("answer_index", generated.json["questions"][0])
        submission = self.api_post(
            self.client,
            "/api/quiz/submit",
            {"quiz_id": generated.json["quiz_id"], "answers": [0] * 5},
        )
        self.assertEqual(submission.status_code, 200)
        self.assertEqual(submission.json["score"], 5)
        self.assertEqual(submission.json["total"], 5)
        item = self.client.get("/api/history").json["items"][0]
        self.assertEqual(item["type"], "quiz")
        saved_review = self.client.get(f"/api/history/{item['id']}?type=quiz")
        self.assertEqual(len(saved_review.json["review"]), 5)

        second_client = self.app.test_client()
        self.register(second_client, "Second Student", "second@example.com")
        foreign_submit = self.api_post(
            second_client,
            "/api/quiz/submit",
            {"quiz_id": generated.json["quiz_id"], "answers": [0] * 5},
        )
        self.assertEqual(foreign_submit.status_code, 404)

    def test_flashcards_persist_and_delete(self):
        response = self.api_post(
            self.client,
            "/api/flashcards/generate",
            {"notes": NOTES, "subject": "Biology", "topic": "Mitosis"},
        )
        self.assertEqual(response.status_code, 201)
        record_id = response.json["id"]
        self.assertGreater(len(response.json["cards"]), 0)
        self.assertEqual(self.client.get(f"/api/history/{record_id}?type=flashcards").status_code, 200)
        deleted = self.client.delete(
            f"/api/history/{record_id}?type=flashcards",
            headers={"X-CSRF-Token": self.csrf_token(self.client)},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/history/{record_id}?type=flashcards").status_code,
            404,
        )

    def test_stats_and_settings_are_scoped_to_the_signed_in_user(self):
        self.api_put(self.client, "/api/settings", {"theme": "dark", "language": "Hindi"})
        self.assertEqual(
            self.client.get("/api/settings").json["theme"],
            "dark",
        )
        self.assertEqual(self.client.get("/api/stats").status_code, 200)

        second_client = self.app.test_client()
        self.register(second_client, "Second Student", "second@example.com")
        self.assertEqual(second_client.get("/api/settings").json["theme"], "light")
        self.assertEqual(second_client.get("/api/stats").json["sessions"], 0)

    def test_profile_update_and_password_change(self):
        response = self.client.post(
            "/profile",
            data={
                "csrf_token": self.csrf_token(self.client),
                "name": "Avery Learner",
                "email": "avery.learner@example.com",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Avery Learner", response.data)

        response = self.client.post(
            "/profile/password",
            data={
                "csrf_token": self.csrf_token(self.client),
                "current_password": PASSWORD,
                "password": "a much safer replacement password",
                "confirm_password": "a much safer replacement password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)
        self.client.get("/login")
        login = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf_token(self.client),
                "email": "avery.learner@example.com",
                "password": "a much safer replacement password",
            },
        )
        self.assertEqual(login.status_code, 302)

    def test_password_reset_link_is_one_use(self):
        self.app.config.update(
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=587,
            MAIL_FROM="noreply@example.com",
        )
        with patch("app.send_password_reset_email") as send_email:
            response = self.client.post(
                "/forgot-password",
                data={
                    "csrf_token": self.csrf_token(self.client),
                    "email": "avery@example.com",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(send_email.call_count, 1)
        reset_url = send_email.call_args.args[2]
        token = parse_qs(urlparse(reset_url).query)["token"][0]
        response = self.client.post(
            f"/reset-password?token={token}",
            data={
                "csrf_token": self.csrf_token(self.client),
                "token": token,
                "password": "a reset password with enough length",
                "confirm_password": "a reset password with enough length",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(f"/reset-password?token={token}").status_code, 200)
        self.assertIn(
            b"invalid or has expired",
            self.client.post(
                "/reset-password",
                data={
                    "csrf_token": self.csrf_token(self.client),
                    "token": token,
                    "password": "another reset password",
                    "confirm_password": "another reset password",
                },
            ).data,
        )

    def test_missing_ai_key_returns_setup_message(self):
        no_ai = create_app(
            self.app_config(
                os.path.join(self.temp_dir.name, "no-ai.db"),
                AI_DEMO_MODE=False,
                AI_API_KEY="",
            )
        )
        client = no_ai.test_client()
        self.register(client, "No AI", "no-ai@example.com")
        response = self.api_post(client, "/api/summarize", {"notes": NOTES})
        self.assertEqual(response.status_code, 503)
        self.assertIn("AI_API_KEY", response.json["error"])


if __name__ == "__main__":
    unittest.main()
