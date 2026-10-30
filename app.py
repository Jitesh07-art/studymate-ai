"""StudyMate AI: a beginner-friendly Flask study assistant."""
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

import database
from ai_service import AIError, generate_flashcards, generate_quiz, summarize
from config import Config


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    database.init_db(app.config["DATABASE"])

    def error(message, status=400):
        return jsonify({"error": message}), status

    def payload():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def valid_notes(data):
        notes = data.get("notes")
        if not isinstance(notes, str) or not notes.strip():
            return None, "Add some notes before continuing."
        if len(notes) > app.config["MAX_NOTES_CHARS"]:
            return None, f"Notes must be {app.config['MAX_NOTES_CHARS']:,} characters or fewer."
        return notes.strip(), None

    @app.get("/")
    def dashboard():
        return render_template("index.html", page="dashboard")

    @app.get("/summarizer")
    def summarizer_page():
        return render_template("summarizer.html", page="summarizer")

    @app.get("/quiz")
    def quiz_page():
        return render_template("quiz.html", page="quiz")

    @app.get("/flashcards")
    def flashcards_page():
        return render_template("flashcards.html", page="flashcards")

    @app.get("/history")
    def history_page():
        return render_template("history.html", page="history")

    @app.get("/settings")
    def settings_page():
        return render_template("settings.html", page="settings")

    @app.post("/api/summarize")
    def api_summarize():
        data = payload()
        notes, problem = valid_notes(data)
        if problem:
            return error(problem)
        length = data.get("length", "Medium")
        if length not in ("Short", "Medium", "Detailed"):
            return error("Choose Short, Medium, or Detailed for summary length.")
        try:
            content = summarize(app.config, notes, str(data.get("subject", ""))[:100], length, str(data.get("language", "English"))[:40])
            return jsonify({"summary": content, "demo": app.config["AI_DEMO_MODE"]})
        except AIError as exc:
            return error(str(exc), 503)

    @app.post("/api/history/summary")
    def save_summary():
        data = payload()
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return error("There is no summary to save.")
        if len(content) > 30_000:
            return error("This summary is too long to save.")
        record_id = database.save_summary(app.config["DATABASE"], str(data.get("subject", "General study"))[:100], str(data.get("notes", ""))[:app.config["MAX_NOTES_CHARS"]], content[:30_000])
        return jsonify({"id": record_id, "message": "Summary saved."}), 201

    @app.post("/api/quiz/generate")
    def api_quiz_generate():
        data = payload()
        notes, problem = valid_notes(data)
        if problem:
            return error(problem)
        count = data.get("count", 5)
        if type(count) is not int or count not in (5, 10, 15):
            return error("Choose 5, 10, or 15 questions.")
        difficulty = data.get("difficulty", "Medium")
        if difficulty not in ("Easy", "Medium", "Hard"):
            return error("Choose a valid difficulty.")
        subject, topic = str(data.get("subject", "General study"))[:100], str(data.get("topic", ""))[:100]
        try:
            questions = generate_quiz(app.config, notes, subject, topic, count, difficulty)
            quiz_id = str(uuid.uuid4())
            with database.connect(app.config["DATABASE"]) as db:
                db.execute("INSERT INTO quiz_sessions(id,subject,topic,questions,created_at) VALUES(?,?,?,?,?)", (quiz_id, subject, topic, json.dumps(questions), database.utc_now()))
            safe_questions = [{"question": q["question"], "options": q["options"]} for q in questions]
            return jsonify({"quiz_id": quiz_id, "questions": safe_questions, "demo": app.config["AI_DEMO_MODE"]})
        except AIError as exc:
            return error(str(exc), 503)

    @app.post("/api/quiz/submit")
    def api_quiz_submit():
        data = payload()
        quiz_id, answers = data.get("quiz_id"), data.get("answers")
        if not isinstance(quiz_id, str) or not isinstance(answers, list):
            return error("Quiz submission is incomplete.")
        with database.connect(app.config["DATABASE"]) as db:
            row = db.execute("SELECT * FROM quiz_sessions WHERE id=?", (quiz_id,)).fetchone()
        if not row:
            return error("This quiz is no longer available. Generate a new one.", 404)
        questions = json.loads(row["questions"])
        if len(answers) != len(questions) or any(type(a) is not int or a not in range(4) for a in answers):
            return error("Select one answer for every question before submitting.")
        correct = sum(a == q["answer_index"] for a, q in zip(answers, questions))
        with database.connect(app.config["DATABASE"]) as db:
            cur = db.execute("INSERT INTO quiz_attempts(session_id,subject,topic,score,total,answers,created_at) VALUES(?,?,?,?,?,?,?)", (quiz_id, row["subject"], row["topic"], correct, len(questions), json.dumps(answers), database.utc_now()))
            attempt_id = cur.lastrowid
        review = [{"question": q["question"], "options": q["options"], "answer_index": q["answer_index"], "selected_index": answers[i], "correct": answers[i] == q["answer_index"], "explanation": q["explanation"]} for i, q in enumerate(questions)]
        return jsonify({"attempt_id": attempt_id, "score": correct, "total": len(questions), "percentage": round(correct / len(questions) * 100), "review": review})

    @app.post("/api/flashcards/generate")
    def api_flashcards_generate():
        data = payload()
        notes, problem = valid_notes(data)
        if problem:
            return error(problem)
        subject, topic = str(data.get("subject", "General study"))[:100], str(data.get("topic", ""))[:100]
        try:
            cards = generate_flashcards(app.config, notes, subject, topic)
            with database.connect(app.config["DATABASE"]) as db:
                cur = db.execute("INSERT INTO flashcard_sets(subject,topic,cards,created_at) VALUES(?,?,?,?)", (subject, topic, json.dumps(cards), database.utc_now()))
                set_id = cur.lastrowid
            return jsonify({"id": set_id, "cards": cards, "demo": app.config["AI_DEMO_MODE"]}), 201
        except AIError as exc:
            return error(str(exc), 503)

    @app.get("/api/history")
    def api_history():
        return jsonify({"items": database.history(app.config["DATABASE"])})

    @app.get("/api/history/<int:record_id>")
    def api_history_detail(record_id):
        kind = request.args.get("type", "summary")
        record = database.get_record(app.config["DATABASE"], kind, record_id)
        if not record:
            return error("Saved item not found.", 404)
        return jsonify(record)

    @app.delete("/api/history/<int:record_id>")
    def api_history_delete(record_id):
        kind = request.args.get("type", "summary")
        if not database.delete_record(app.config["DATABASE"], kind, record_id):
            return error("Saved item not found.", 404)
        return jsonify({"message": "Saved item deleted."})

    @app.get("/api/stats")
    def api_stats():
        with database.connect(app.config["DATABASE"]) as db:
            summary_count = db.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
            attempts = db.execute("SELECT COUNT(*), COALESCE(AVG(100.0*score/total),0) FROM quiz_attempts").fetchone()
            card_count = db.execute("SELECT COUNT(*) FROM flashcard_sets").fetchone()[0]
            week = db.execute("SELECT substr(created_at,1,10) day, COUNT(*) count FROM quiz_attempts WHERE created_at >= datetime('now','-6 days') GROUP BY day").fetchall()
        return jsonify({"sessions": summary_count + attempts[0] + card_count, "summaries": summary_count, "quizzes": attempts[0], "average_score": round(attempts[1]), "recent": database.history(app.config["DATABASE"])[:5], "weekly": [dict(r) for r in week]})

    @app.get("/api/health")
    def api_health():
        configured = bool(app.config["AI_API_KEY"])
        return jsonify({"status": "ok", "database": "connected", "ai": "demo" if app.config["AI_DEMO_MODE"] else "connected" if configured else "not_configured"})

    @app.get("/api/settings")
    def api_settings():
        values = database.get_settings(app.config["DATABASE"])
        return jsonify({"theme": values.get("theme", "light"), "language": values.get("language", "English"), "ai_status": "Demo mode" if app.config["AI_DEMO_MODE"] else "Connected" if app.config["AI_API_KEY"] else "Not configured", "provider": app.config["AI_PROVIDER"], "model": app.config["AI_MODEL"]})

    @app.put("/api/settings")
    def api_settings_update():
        data = payload()
        for key in ("theme", "language"):
            value = data.get(key)
            if key == "theme" and value not in ("light", "dark"):
                return error("Choose a valid theme.")
            if key == "language" and value not in ("English", "Spanish", "French", "Hindi"):
                return error("Choose a supported language.")
            if value:
                database.set_setting(app.config["DATABASE"], key, value)
        return jsonify({"message": "Preferences saved."})

    @app.delete("/api/history")
    def api_history_clear():
        with database.connect(app.config["DATABASE"]) as db:
            for table in ("summaries", "quiz_sessions", "quiz_attempts", "flashcard_sets"):
                db.execute(f"DELETE FROM {table}")
        return jsonify({"message": "Study history cleared."})

    return app


app = create_app()

if __name__ == "__main__":
    print("StudyMate AI is running at http://127.0.0.1:5000")
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
