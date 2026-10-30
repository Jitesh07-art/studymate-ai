"""StudyMate AI: a personal study workspace with account-based data isolation."""
import hashlib
import json
import os
import re
import secrets
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

import database
from ai_service import AIError, generate_flashcards, generate_quiz, summarize
from config import Config


def valid_email(value):
    if not isinstance(value, str):
        return False
    address = value.strip().lower()
    parsed = parseaddr(address)[1]
    return (
        len(address) <= 254
        and parsed == address
        and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address) is not None
    )


def password_error(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        return "Use a password between 12 and 128 characters."
    return None


def reset_token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def send_password_reset_email(config, recipient, reset_url):
    message = EmailMessage()
    message["Subject"] = "Reset your StudyMate AI password"
    message["From"] = config["MAIL_FROM"]
    message["To"] = recipient
    message.set_content(
        "We received a request to reset your StudyMate AI password.\n\n"
        f"Use this link within one hour:\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    host = config["SMTP_HOST"]
    port = config["SMTP_PORT"]
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as smtp:
            if config["SMTP_USERNAME"]:
                smtp.login(config["SMTP_USERNAME"], config["SMTP_PASSWORD"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if config["SMTP_USERNAME"]:
                smtp.login(config["SMTP_USERNAME"], config["SMTP_PASSWORD"])
            smtp.send_message(message)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config["DATABASE"].startswith(("postgres://", "postgresql://")):
        Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    database.init_db(app.config["DATABASE"])

    limiter = Limiter(key_func=get_remote_address, default_limits=[])
    limiter.init_app(app)

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

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.current_user is None:
                if request.path.startswith("/api/"):
                    return error("Please sign in to continue.", 401)
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    @app.before_request
    def load_request_user_and_check_csrf():
        g.current_user = None
        if session.get("user_id") is not None:
            user = database.get_user(app.config["DATABASE"], session["user_id"])
            if user and user["session_version"] == session.get("session_version"):
                g.current_user = user
            else:
                session.clear()

        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            if not secrets.compare_digest(session["csrf_token"], supplied):
                if request.path.startswith("/api/"):
                    return error("Your session expired. Refresh the page and try again.", 400)
                abort(400)

    @app.context_processor
    def inject_template_context():
        user = g.get("current_user")
        return {
            "current_user": {"name": user["name"], "email": user["email"]} if user else None,
            "csrf_token": session.get("csrf_token", ""),
        }

    def establish_session(user):
        session.clear()
        session.permanent = True
        session["user_id"] = user["id"]
        session["session_version"] = user["session_version"]
        session["csrf_token"] = secrets.token_urlsafe(32)

    @app.get("/login")
    @app.post("/login")
    @limiter.limit("5 per minute", methods=["POST"])
    def login():
        if g.current_user:
            return redirect(url_for("dashboard"))
        message = None
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = database.get_user_by_email(app.config["DATABASE"], email)
            if user and check_password_hash(user["password_hash"], password):
                establish_session(user)
                return redirect(url_for("dashboard"))
            message = "That email and password combination wasn’t recognized."
        if request.args.get("changed") == "1":
            message = "Your password was updated. Sign in with your new password."
        return render_template("auth_login.html", page="login", error=message)

    @app.get("/register")
    @app.post("/register")
    @limiter.limit("5 per minute", methods=["POST"])
    def register():
        if g.current_user:
            return redirect(url_for("dashboard"))
        message = None
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirmation = request.form.get("confirm_password", "")
            if not name or len(name) > 80:
                message = "Enter a name between 1 and 80 characters."
            elif not valid_email(email):
                message = "Enter a valid email address."
            elif (message := password_error(password)):
                pass
            elif password != confirmation:
                message = "Your passwords do not match."
            else:
                user = database.create_user(app.config["DATABASE"], name, email, generate_password_hash(password))
                if user:
                    establish_session(user)
                    return redirect(url_for("dashboard"))
                message = "An account with that email already exists. Try signing in instead."
        return render_template("auth_register.html", page="register", error=message)

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/forgot-password")
    @app.post("/forgot-password")
    @limiter.limit("3 per hour", methods=["POST"])
    def forgot_password():
        message = None
        status = 200
        if request.method == "POST":
            host = app.config["SMTP_HOST"]
            sender = app.config["MAIL_FROM"]
            username = app.config["SMTP_USERNAME"]
            password = app.config["SMTP_PASSWORD"]
            if not host or not sender or bool(username) != bool(password):
                message = "Password recovery email is not configured yet. Ask the site administrator for help."
                status = 503
            else:
                email = request.form.get("email", "").strip().lower()
                if valid_email(email):
                    user = database.get_user_by_email(app.config["DATABASE"], email)
                    if user:
                        token = secrets.token_urlsafe(32)
                        hashed = reset_token_hash(token)
                        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
                        database.save_password_reset(app.config["DATABASE"], user["id"], hashed, expires)
                        reset_url = url_for("reset_password", token=token, _external=True)
                        try:
                            send_password_reset_email(app.config, user["email"], reset_url)
                        except (OSError, smtplib.SMTPException):
                            database.delete_password_reset(app.config["DATABASE"], hashed)
                            app.logger.error("Password reset email delivery failed.")
                            message = "We couldn’t send the reset email. Please try again later."
                            status = 503
                if not message:
                    message = "If an account exists for that email, a password-reset link is on its way."
        return render_template("auth_forgot_password.html", page="forgot-password", message=message), status

    @app.get("/reset-password")
    @app.post("/reset-password")
    @limiter.limit("5 per hour", methods=["POST"])
    def reset_password():
        token = request.args.get("token", "") if request.method == "GET" else request.form.get("token", "")
        hashed = reset_token_hash(token) if token else ""
        valid = bool(token and database.password_reset_is_valid(app.config["DATABASE"], hashed))
        message = None
        if request.method == "POST":
            password = request.form.get("password", "")
            confirmation = request.form.get("confirm_password", "")
            if not valid:
                message = "This reset link is invalid or has expired. Request a new one."
            elif (message := password_error(password)):
                pass
            elif password != confirmation:
                message = "Your passwords do not match."
            elif database.reset_password(app.config["DATABASE"], hashed, generate_password_hash(password)):
                session.clear()
                return redirect(url_for("login", changed=1))
            else:
                message = "This reset link has already been used or has expired."
        return render_template(
            "auth_reset_password.html",
            page="reset-password",
            error=message,
            token=token,
            token_valid=valid,
        )

    @app.get("/")
    @login_required
    def dashboard():
        return render_template("index.html", page="dashboard")

    @app.get("/summarizer")
    @login_required
    def summarizer_page():
        return render_template("summarizer.html", page="summarizer")

    @app.get("/quiz")
    @login_required
    def quiz_page():
        return render_template("quiz.html", page="quiz")

    @app.get("/flashcards")
    @login_required
    def flashcards_page():
        return render_template("flashcards.html", page="flashcards")

    @app.get("/history")
    @login_required
    def history_page():
        return render_template("history.html", page="history")

    @app.get("/settings")
    @login_required
    def settings_page():
        return render_template("settings.html", page="settings")

    @app.get("/profile")
    @login_required
    def profile_page():
        return render_template("profile.html", page="profile", error=None, success=None)

    @app.post("/profile")
    @login_required
    def profile_update():
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        message = None
        success = None
        if not name or len(name) > 80:
            message = "Enter a name between 1 and 80 characters."
        elif not valid_email(email):
            message = "Enter a valid email address."
        elif not database.update_user_profile(app.config["DATABASE"], g.current_user["id"], name, email):
            message = "That email address is already in use."
        else:
            g.current_user["name"] = name
            g.current_user["email"] = email
            success = "Your profile has been updated."
        return render_template("profile.html", page="profile", error=message, success=success)

    @app.post("/profile/password")
    @login_required
    def profile_password_update():
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        message = None
        if not check_password_hash(g.current_user["password_hash"], current_password):
            message = "Your current password is incorrect."
        elif (message := password_error(new_password)):
            pass
        elif new_password != confirmation:
            message = "Your passwords do not match."
        else:
            database.update_password(
                app.config["DATABASE"],
                g.current_user["id"],
                generate_password_hash(new_password),
            )
            session.clear()
            return redirect(url_for("login", changed=1))
        return render_template("profile.html", page="profile", error=message, success=None)

    @app.post("/api/summarize")
    @login_required
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
    @login_required
    def save_summary():
        data = payload()
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return error("There is no summary to save.")
        if len(content) > 30_000:
            return error("This summary is too long to save.")
        record_id = database.save_summary(
            app.config["DATABASE"], g.current_user["id"],
            str(data.get("subject", "General study"))[:100],
            str(data.get("notes", ""))[:app.config["MAX_NOTES_CHARS"]],
            content[:30_000],
        )
        return jsonify({"id": record_id, "message": "Summary saved."}), 201

    @app.post("/api/quiz/generate")
    @login_required
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
                db.execute(
                    "INSERT INTO quiz_sessions(id,user_id,subject,topic,questions,created_at) VALUES(?,?,?,?,?,?)",
                    (quiz_id, g.current_user["id"], subject, topic, json.dumps(questions), database.utc_now()),
                )
            safe_questions = [{"question": q["question"], "options": q["options"]} for q in questions]
            return jsonify({"quiz_id": quiz_id, "questions": safe_questions, "demo": app.config["AI_DEMO_MODE"]})
        except AIError as exc:
            return error(str(exc), 503)

    @app.post("/api/quiz/submit")
    @login_required
    def api_quiz_submit():
        data = payload()
        quiz_id, answers = data.get("quiz_id"), data.get("answers")
        if not isinstance(quiz_id, str) or not isinstance(answers, list):
            return error("Quiz submission is incomplete.")
        with database.connect(app.config["DATABASE"]) as db:
            row = db.execute(
                "SELECT * FROM quiz_sessions WHERE id=? AND user_id=?",
                (quiz_id, g.current_user["id"]),
            ).fetchone()
        if not row:
            return error("This quiz is no longer available. Generate a new one.", 404)
        questions = json.loads(row["questions"])
        if len(answers) != len(questions) or any(type(a) is not int or a not in range(4) for a in answers):
            return error("Select one answer for every question before submitting.")
        correct = sum(a == q["answer_index"] for a, q in zip(answers, questions))
        with database.connect(app.config["DATABASE"]) as db:
            cur = db.execute(
                "INSERT INTO quiz_attempts(user_id,session_id,subject,topic,score,total,answers,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (g.current_user["id"], quiz_id, row["subject"], row["topic"], correct, len(questions), json.dumps(answers), database.utc_now()),
            )
            attempt_id = cur.lastrowid
        review = [{"question": q["question"], "options": q["options"], "answer_index": q["answer_index"], "selected_index": answers[i], "correct": answers[i] == q["answer_index"], "explanation": q["explanation"]} for i, q in enumerate(questions)]
        return jsonify({"attempt_id": attempt_id, "score": correct, "total": len(questions), "percentage": round(correct / len(questions) * 100), "review": review})

    @app.post("/api/flashcards/generate")
    @login_required
    def api_flashcards_generate():
        data = payload()
        notes, problem = valid_notes(data)
        if problem:
            return error(problem)
        subject, topic = str(data.get("subject", "General study"))[:100], str(data.get("topic", ""))[:100]
        try:
            cards = generate_flashcards(app.config, notes, subject, topic)
            with database.connect(app.config["DATABASE"]) as db:
                cur = db.execute(
                    "INSERT INTO flashcard_sets(user_id,subject,topic,cards,created_at) VALUES(?,?,?,?,?)",
                    (g.current_user["id"], subject, topic, json.dumps(cards), database.utc_now()),
                )
                set_id = cur.lastrowid
            return jsonify({"id": set_id, "cards": cards, "demo": app.config["AI_DEMO_MODE"]}), 201
        except AIError as exc:
            return error(str(exc), 503)

    @app.get("/api/history")
    @login_required
    def api_history():
        return jsonify({"items": database.history(app.config["DATABASE"], g.current_user["id"])})

    @app.get("/api/history/<int:record_id>")
    @login_required
    def api_history_detail(record_id):
        kind = request.args.get("type", "summary")
        record = database.get_record(app.config["DATABASE"], kind, record_id, g.current_user["id"])
        if not record:
            return error("Saved item not found.", 404)
        return jsonify(record)

    @app.delete("/api/history/<int:record_id>")
    @login_required
    def api_history_delete(record_id):
        kind = request.args.get("type", "summary")
        if not database.delete_record(app.config["DATABASE"], kind, record_id, g.current_user["id"]):
            return error("Saved item not found.", 404)
        return jsonify({"message": "Saved item deleted."})

    @app.get("/api/stats")
    @login_required
    def api_stats():
        user_id = g.current_user["id"]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat(timespec="seconds")
        with database.connect(app.config["DATABASE"]) as db:
            summary_count = db.execute(
                "SELECT COUNT(*) AS summary_count FROM summaries WHERE user_id=?", (user_id,)
            ).fetchone()["summary_count"]
            attempts = db.execute(
                "SELECT COUNT(*) AS quiz_count, "
                "COALESCE(AVG(100.0*score/total),0) AS average_score "
                "FROM quiz_attempts WHERE user_id=?",
                (user_id,),
            ).fetchone()
            card_count = db.execute(
                "SELECT COUNT(*) AS card_count FROM flashcard_sets WHERE user_id=?", (user_id,)
            ).fetchone()["card_count"]
            week = db.execute(
                "SELECT substr(created_at,1,10) day, COUNT(*) count FROM quiz_attempts "
                "WHERE user_id=? AND created_at>=? GROUP BY day",
                (user_id, cutoff),
            ).fetchall()
        return jsonify({
            "sessions": summary_count + attempts["quiz_count"] + card_count,
            "summaries": summary_count,
            "quizzes": attempts["quiz_count"],
            "average_score": round(attempts["average_score"]),
            "recent": database.history(app.config["DATABASE"], user_id)[:5],
            "weekly": [dict(row) for row in week],
        })

    @app.get("/api/health")
    def api_health():
        with database.connect(app.config["DATABASE"]) as db:
            db.execute("SELECT 1")
        configured = bool(app.config["AI_API_KEY"])
        return jsonify({"status": "ok", "database": "connected", "ai": "demo" if app.config["AI_DEMO_MODE"] else "connected" if configured else "not_configured"})

    @app.get("/api/settings")
    @login_required
    def api_settings():
        values = database.get_settings(app.config["DATABASE"], g.current_user["id"])
        return jsonify({"theme": values.get("theme", "light"), "language": values.get("language", "English"), "ai_status": "Demo mode" if app.config["AI_DEMO_MODE"] else "Connected" if app.config["AI_API_KEY"] else "Not configured", "provider": app.config["AI_PROVIDER"], "model": app.config["AI_MODEL"]})

    @app.put("/api/settings")
    @login_required
    def api_settings_update():
        data = payload()
        for key in ("theme", "language"):
            value = data.get(key)
            if key == "theme" and value not in ("light", "dark"):
                return error("Choose a valid theme.")
            if key == "language" and value not in ("English", "Spanish", "French", "Hindi"):
                return error("Choose a supported language.")
            if value:
                database.set_setting(app.config["DATABASE"], g.current_user["id"], key, value)
        return jsonify({"message": "Preferences saved."})

    @app.delete("/api/history")
    @login_required
    def api_history_clear():
        with database.connect(app.config["DATABASE"]) as db:
            for table in ("summaries", "quiz_sessions", "quiz_attempts", "flashcard_sets"):
                db.execute(f"DELETE FROM {table} WHERE user_id=?", (g.current_user["id"],))
        return jsonify({"message": "Study history cleared."})

    @app.errorhandler(429)
    def too_many_requests(_error):
        if request.path.startswith("/api/"):
            return error("Too many attempts. Please wait a moment and try again.", 429)
        return render_template(
            "auth_error.html",
            page="rate-limit",
            error="Too many attempts. Please wait a moment and try again.",
        ), 429

    return app


app = create_app()

if __name__ == "__main__":
    print("StudyMate AI is running at http://127.0.0.1:5000")
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
