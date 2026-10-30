"""SQLite and PostgreSQL helpers for StudyMate AI."""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


AUTO_ID_TABLES = {"users", "summaries", "quiz_attempts", "flashcard_sets"}
USER_DATA_TABLES = ("summaries", "quiz_sessions", "quiz_attempts", "flashcard_sets")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CursorAdapter:
    def __init__(self, cursor, returning_id=False):
        self.cursor = cursor
        self.returning_id = returning_id
        self.cached_row = None
        self.inserted_id = None

    @property
    def rowcount(self):
        return self.cursor.rowcount

    @property
    def lastrowid(self):
        if self.returning_id and self.inserted_id is None:
            row = self.fetchone()
            self.inserted_id = row["id"] if row else None
        return self.inserted_id

    def fetchone(self):
        if self.cached_row is not None:
            row, self.cached_row = self.cached_row, None
            return row
        return self.cursor.fetchone()

    def fetchall(self):
        rows = self.cursor.fetchall()
        if self.cached_row is not None:
            rows.insert(0, self.cached_row)
            self.cached_row = None
        return rows


class Connection:
    def __init__(self, path):
        self.is_postgres = path.startswith(("postgres://", "postgresql://"))
        if self.is_postgres:
            import psycopg
            from psycopg.rows import dict_row

            if path.startswith("postgres://"):
                path = "postgresql://" + path[len("postgres://"):]
            self.db = psycopg.connect(path, row_factory=dict_row)
        else:
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row

    def execute(self, query, parameters=()):
        if not self.is_postgres:
            return self.db.execute(query, parameters)

        statement = query.replace("?", "%s")
        match = re.match(r"\s*INSERT\s+INTO\s+([a-z_]+)", statement, re.IGNORECASE)
        returning_id = bool(match and match.group(1).lower() in AUTO_ID_TABLES)
        if returning_id:
            statement = statement.rstrip().rstrip(";") + " RETURNING id"
        return CursorAdapter(self.db.execute(statement, parameters), returning_id)

    def executescript(self, script):
        if not self.is_postgres:
            return self.db.executescript(script)
        for statement in script.split(";"):
            if statement.strip():
                self.db.execute(statement)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        self.db.close()


@contextmanager
def connect(path):
    db = Connection(path)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db(path):
    auto_id = "SERIAL PRIMARY KEY" if path.startswith(("postgres://", "postgresql://")) else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with connect(path) as db:
        db.executescript(f"""
        CREATE TABLE IF NOT EXISTS users (
          id {auto_id}, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL, session_version INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS summaries (
          id {auto_id}, user_id INTEGER, subject TEXT NOT NULL, input_text TEXT NOT NULL,
          content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quiz_sessions (
          id TEXT PRIMARY KEY, user_id INTEGER, subject TEXT NOT NULL, topic TEXT NOT NULL,
          questions TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quiz_attempts (
          id {auto_id}, user_id INTEGER, session_id TEXT NOT NULL, subject TEXT NOT NULL,
          topic TEXT NOT NULL, score INTEGER NOT NULL, total INTEGER NOT NULL,
          answers TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flashcard_sets (
          id {auto_id}, user_id INTEGER, subject TEXT NOT NULL, topic TEXT NOT NULL,
          cards TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
          user_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
          PRIMARY KEY (user_id, key)
        );
        """)
        if db.is_postgres:
            columns = {
                row["column_name"]
                for row in db.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='settings'"
                )
            }
        else:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(settings)")}
        if "user_id" not in columns:
            db.execute("ALTER TABLE settings RENAME TO settings_legacy")
            db.execute(
                "CREATE TABLE settings (user_id INTEGER NOT NULL, key TEXT NOT NULL, "
                "value TEXT NOT NULL, PRIMARY KEY (user_id,key))"
            )
            db.execute("DROP TABLE settings_legacy")
        for table in USER_DATA_TABLES:
            if db.is_postgres:
                db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id INTEGER")
            else:
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if "user_id" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")
        db.execute("CREATE INDEX IF NOT EXISTS summaries_user_id_idx ON summaries(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS quiz_sessions_user_id_idx ON quiz_sessions(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS quiz_attempts_user_id_idx ON quiz_attempts(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS flashcard_sets_user_id_idx ON flashcard_sets(user_id)")


def create_user(path, name, email, password_hash):
    try:
        with connect(path) as db:
            cursor = db.execute(
                "INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                (name, email, password_hash, utc_now()),
            )
            row = db.execute(
                "SELECT id,name,email,password_hash,session_version,created_at FROM users WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            return dict(row)
    except sqlite3.IntegrityError:
        return None
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            return None
        raise


def get_user(path, user_id):
    with connect(path) as db:
        row = db.execute(
            "SELECT id,name,email,password_hash,session_version,created_at FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_email(path, email):
    with connect(path) as db:
        row = db.execute(
            "SELECT id,name,email,password_hash,session_version,created_at FROM users WHERE email=?",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def update_user_profile(path, user_id, name, email):
    try:
        with connect(path) as db:
            db.execute("UPDATE users SET name=?,email=? WHERE id=?", (name, email, user_id))
    except sqlite3.IntegrityError:
        return False
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            return False
        raise
    return True


def update_password(path, user_id, password_hash):
    with connect(path) as db:
        db.execute(
            "UPDATE users SET password_hash=?,session_version=session_version+1 WHERE id=?",
            (password_hash, user_id),
        )


def save_password_reset(path, user_id, token_hash, expires_at):
    with connect(path) as db:
        db.execute("DELETE FROM password_reset_tokens WHERE user_id=?", (user_id,))
        db.execute(
            "INSERT INTO password_reset_tokens(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
            (token_hash, user_id, expires_at, utc_now()),
        )


def delete_password_reset(path, token_hash):
    with connect(path) as db:
        db.execute("DELETE FROM password_reset_tokens WHERE token_hash=?", (token_hash,))


def password_reset_is_valid(path, token_hash):
    with connect(path) as db:
        token = db.execute(
            "SELECT expires_at FROM password_reset_tokens WHERE token_hash=?",
            (token_hash,),
        ).fetchone()
    return bool(token and token["expires_at"] >= utc_now())


def reset_password(path, token_hash, password_hash):
    now = utc_now()
    with connect(path) as db:
        lock = " FOR UPDATE" if db.is_postgres else ""
        token = db.execute(
            "SELECT user_id,expires_at FROM password_reset_tokens WHERE token_hash=?" + lock,
            (token_hash,),
        ).fetchone()
        if not token or token["expires_at"] < now:
            return False
        db.execute(
            "UPDATE users SET password_hash=?,session_version=session_version+1 WHERE id=?",
            (password_hash, token["user_id"]),
        )
        db.execute("DELETE FROM password_reset_tokens WHERE user_id=?", (token["user_id"],))
    return True


def save_summary(path, user_id, subject, input_text, content):
    with connect(path) as db:
        cur = db.execute(
            "INSERT INTO summaries(user_id,subject,input_text,content,created_at) VALUES(?,?,?,?,?)",
            (user_id, subject, input_text, content, utc_now()),
        )
        return cur.lastrowid


def history(path, user_id):
    items = []
    with connect(path) as db:
        for row in db.execute(
            "SELECT id,subject,content,created_at FROM summaries WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        ):
            items.append({"id": row["id"], "type": "summary", "subject": row["subject"], "title": "Study summary", "content": row["content"], "created_at": row["created_at"]})
        for row in db.execute("SELECT * FROM quiz_attempts WHERE user_id=? ORDER BY id DESC", (user_id,)):
            items.append({"id": row["id"], "type": "quiz", "subject": row["subject"], "title": row["topic"] or "Quiz", "score": row["score"], "total": row["total"], "created_at": row["created_at"]})
        for row in db.execute(
            "SELECT id,subject,topic,created_at FROM flashcard_sets WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        ):
            items.append({"id": row["id"], "type": "flashcards", "subject": row["subject"], "title": row["topic"] or "Flashcards", "created_at": row["created_at"]})
    return sorted(items, key=lambda item: item["created_at"], reverse=True)


def get_record(path, kind, record_id, user_id):
    tables = {"summary": ("summaries", "id"), "quiz": ("quiz_attempts", "id"), "flashcards": ("flashcard_sets", "id")}
    if kind not in tables:
        return None
    table, key = tables[kind]
    with connect(path) as db:
        row = db.execute(
            f"SELECT * FROM {table} WHERE {key}=? AND user_id=?",
            (record_id, user_id),
        ).fetchone()
        result = dict(row) if row else None
        if result and kind == "quiz":
            session = db.execute(
                "SELECT questions FROM quiz_sessions WHERE id=? AND user_id=?",
                (result["session_id"], user_id),
            ).fetchone()
        else:
            session = None
    if result:
        result["type"] = kind
        for field in ("cards", "answers"):
            if result.get(field):
                result[field] = json.loads(result[field])
        if kind == "quiz":
            questions = json.loads(session["questions"]) if session else []
            result["review"] = [
                {"question": question["question"], "options": question["options"],
                 "answer_index": question["answer_index"], "selected_index": result["answers"][index],
                 "correct": question["answer_index"] == result["answers"][index],
                 "explanation": question["explanation"]}
                for index, question in enumerate(questions) if index < len(result["answers"])
            ]
    return result


def delete_record(path, kind, record_id, user_id):
    tables = {"summary": "summaries", "quiz": "quiz_attempts", "flashcards": "flashcard_sets"}
    if kind not in tables:
        return False
    with connect(path) as db:
        cur = db.execute(
            f"DELETE FROM {tables[kind]} WHERE id=? AND user_id=?",
            (record_id, user_id),
        )
        return cur.rowcount > 0


def get_settings(path, user_id):
    with connect(path) as db:
        return {
            row["key"]: row["value"]
            for row in db.execute("SELECT key,value FROM settings WHERE user_id=?", (user_id,))
        }


def set_setting(path, user_id, key, value):
    with connect(path) as db:
        db.execute(
            "INSERT INTO settings(user_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
            (user_id, key, value),
        )
