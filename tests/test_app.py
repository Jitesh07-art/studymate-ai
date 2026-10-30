"""A small set of API tests using isolated temporary SQLite databases."""
import os
import tempfile
import unittest

from app import create_app


class StudyMateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.db_path, "AI_DEMO_MODE": True, "AI_API_KEY": "", "MAX_NOTES_CHARS": 20000})
        self.client = self.app.test_client()
        self.notes = "Mitosis is a process of cell division. It creates two genetically identical daughter cells."

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dashboard_and_health_open(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/health").json["status"], "ok")
        for path in ("/summarizer", "/quiz", "/flashcards", "/history", "/settings"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_empty_notes_rejected(self):
        response = self.client.post("/api/summarize", json={"notes": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertIn("notes", response.json["error"].lower())

    def test_summary_saved_and_retrieved(self):
        generated = self.client.post("/api/summarize", json={"notes": self.notes, "subject": "Biology"})
        self.assertEqual(generated.status_code, 200)
        saved = self.client.post("/api/history/summary", json={"content": generated.json["summary"], "subject": "Biology", "notes": self.notes})
        self.assertEqual(saved.status_code, 201)
        detail = self.client.get(f"/api/history/{saved.json['id']}?type=summary")
        self.assertEqual(detail.json["subject"], "Biology")
        self.assertTrue(detail.json["content"])
        restarted = create_app({"TESTING": True, "DATABASE": self.db_path, "AI_DEMO_MODE": True, "MAX_NOTES_CHARS": 20000})
        self.assertEqual(len(restarted.test_client().get("/api/history").json["items"]), 1)

    def test_quiz_keeps_key_private_and_scores_server_side(self):
        generated = self.client.post("/api/quiz/generate", json={"notes": self.notes, "count": 5, "subject": "Biology"})
        self.assertEqual(generated.status_code, 200)
        question = generated.json["questions"][0]
        self.assertNotIn("answer_index", question)
        submission = self.client.post("/api/quiz/submit", json={"quiz_id": generated.json["quiz_id"], "answers": [0] * 5})
        self.assertEqual(submission.status_code, 200)
        self.assertEqual(submission.json["score"], 5)
        self.assertEqual(submission.json["total"], 5)
        item = self.client.get("/api/history").json["items"][0]
        self.assertEqual(item["type"], "quiz")
        saved_review = self.client.get(f"/api/history/{item['id']}?type=quiz")
        self.assertEqual(len(saved_review.json["review"]), 5)

    def test_flashcards_persist_and_delete(self):
        response = self.client.post("/api/flashcards/generate", json={"notes": self.notes, "subject": "Biology", "topic": "Mitosis"})
        self.assertEqual(response.status_code, 201)
        record_id = response.json["id"]
        self.assertGreater(len(response.json["cards"]), 0)
        self.assertEqual(self.client.get(f"/api/history/{record_id}?type=flashcards").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/history/{record_id}?type=flashcards").status_code, 200)
        self.assertEqual(self.client.get(f"/api/history/{record_id}?type=flashcards").status_code, 404)

    def test_missing_ai_key_returns_setup_message(self):
        no_ai = create_app({"TESTING": True, "DATABASE": os.path.join(self.temp_dir.name, "no-ai.db"), "AI_DEMO_MODE": False, "AI_API_KEY": "", "MAX_NOTES_CHARS": 20000})
        response = no_ai.test_client().post("/api/summarize", json={"notes": self.notes})
        self.assertEqual(response.status_code, 503)
        self.assertIn("AI_API_KEY", response.json["error"])


if __name__ == "__main__":
    unittest.main()
