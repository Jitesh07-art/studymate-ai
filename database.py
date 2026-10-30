"""Small SQLite helpers for StudyMate AI."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db(path):
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS summaries (
          id INTEGER PRIMARY KEY, subject TEXT NOT NULL, input_text TEXT NOT NULL,
          content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quiz_sessions (
          id TEXT PRIMARY KEY, subject TEXT NOT NULL, topic TEXT NOT NULL,
          questions TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quiz_attempts (
          id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, subject TEXT NOT NULL,
          topic TEXT NOT NULL, score INTEGER NOT NULL, total INTEGER NOT NULL,
          answers TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flashcard_sets (
          id INTEGER PRIMARY KEY, subject TEXT NOT NULL, topic TEXT NOT NULL,
          cards TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        """)


def row_dict(row):
    return dict(row) if row else None


def save_summary(path, subject, input_text, content):
    with connect(path) as db:
        cur = db.execute("INSERT INTO summaries(subject,input_text,content,created_at) VALUES(?,?,?,?)",
                         (subject, input_text, content, utc_now()))
        return cur.lastrowid


def history(path):
    items = []
    with connect(path) as db:
        for row in db.execute("SELECT id,subject,content,created_at FROM summaries ORDER BY id DESC"):
            items.append({"id": row["id"], "type": "summary", "subject": row["subject"], "title": "Study summary", "content": row["content"], "created_at": row["created_at"]})
        for row in db.execute("SELECT * FROM quiz_attempts ORDER BY id DESC"):
            items.append({"id": row["id"], "type": "quiz", "subject": row["subject"], "title": row["topic"] or "Quiz", "score": row["score"], "total": row["total"], "created_at": row["created_at"]})
        for row in db.execute("SELECT id,subject,topic,created_at FROM flashcard_sets ORDER BY id DESC"):
            items.append({"id": row["id"], "type": "flashcards", "subject": row["subject"], "title": row["topic"] or "Flashcards", "created_at": row["created_at"]})
    return sorted(items, key=lambda item: item["created_at"], reverse=True)


def get_record(path, kind, record_id):
    tables = {"summary": ("summaries", "id"), "quiz": ("quiz_attempts", "id"), "flashcards": ("flashcard_sets", "id")}
    if kind not in tables:
        return None
    table, key = tables[kind]
    with connect(path) as db:
        row = db.execute(f"SELECT * FROM {table} WHERE {key}=?", (record_id,)).fetchone()
        result = row_dict(row)
    if result:
        result["type"] = kind
        for field in ("cards", "answers"):
            if result.get(field):
                result[field] = json.loads(result[field])
        if kind == "quiz":
            with connect(path) as db:
                session = db.execute("SELECT questions FROM quiz_sessions WHERE id=?", (result["session_id"],)).fetchone()
            questions = json.loads(session["questions"]) if session else []
            result["review"] = [
                {"question": question["question"], "options": question["options"],
                 "answer_index": question["answer_index"], "selected_index": result["answers"][index],
                 "correct": question["answer_index"] == result["answers"][index],
                 "explanation": question["explanation"]}
                for index, question in enumerate(questions) if index < len(result["answers"])
            ]
    return result


def delete_record(path, kind, record_id):
    tables = {"summary": "summaries", "quiz": "quiz_attempts", "flashcards": "flashcard_sets"}
    if kind not in tables:
        return False
    with connect(path) as db:
        cur = db.execute(f"DELETE FROM {tables[kind]} WHERE id=?", (record_id,))
        return cur.rowcount > 0


def get_settings(path):
    with connect(path) as db:
        return {r["key"]: r["value"] for r in db.execute("SELECT key,value FROM settings")}


def set_setting(path, key, value):
    with connect(path) as db:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
