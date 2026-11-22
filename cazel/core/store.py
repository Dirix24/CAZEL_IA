"""Memoria y journal de cambios que comparten Terminal y Studio."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import uuid

from .workspace import diferencia


class Store:
    def __init__(self, datos, base):
        self.datos = Path(datos).resolve()
        self.datos.mkdir(parents=True, exist_ok=True)
        self.base = Path(base).resolve()
        self.archivo = self.datos / "core2.sqlite3"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'offline');
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, session TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_session ON events(session, id);
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY, project TEXT NOT NULL, language TEXT NOT NULL, note TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS lessons_project ON lessons(project, id);
                CREATE TABLE IF NOT EXISTS changes (
                    id TEXT PRIMARY KEY, session TEXT NOT NULL, project TEXT NOT NULL, path TEXT NOT NULL,
                    before TEXT, after TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending');
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.archivo)
        try:
            with db:
                yield db
        finally:
            db.close()

    def project_key(self, root):
        if self.base in root.parents:
            return "./" + root.relative_to(self.base).as_posix()
        return str(root)

    def project_path(self, key):
        return self.base / key if key.startswith("./") else Path(key)

    def create(self, root):
        session = uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT INTO sessions(id, project) VALUES (?, ?)", (session, self.project_key(root)))
        return session

    def sessions(self):
        with self.db() as db:
            return [{"session": s, "project": p, "mode": m} for s, p, m in
                    db.execute("SELECT id, project, mode FROM sessions ORDER BY rowid DESC LIMIT 100")]

    def session(self, session):
        with self.db() as db:
            row = db.execute("SELECT project, mode FROM sessions WHERE id=?", (session,)).fetchone()
        if row is None:
            raise ValueError("Sesión desconocida.")
        return row

    def mode(self, session, mode):
        self.session(session)
        with self.db() as db:
            db.execute("UPDATE sessions SET mode=? WHERE id=?", (mode, session))

    def event(self, session, kind, **data):
        with self.db() as db:
            db.execute("INSERT INTO events(session, kind, data) VALUES (?, ?, ?)",
                       (session, kind, json.dumps(data, ensure_ascii=False)))

    def history(self, session, limit=40):
        with self.db() as db:
            rows = db.execute("SELECT kind, data FROM events WHERE session=? ORDER BY id DESC LIMIT ?",
                              (session, limit)).fetchall()
        return [{"kind": kind, **json.loads(data)} for kind, data in reversed(rows)]

    def lessons(self, project, limit=30):
        with self.db() as db:
            rows = db.execute("SELECT id, language, note FROM lessons WHERE project=? "
                              "ORDER BY id DESC LIMIT ?", (project, limit)).fetchall()
        return [{"id": i, "language": language, "note": note} for i, language, note in rows]

    def save_lesson(self, project, language, note):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id FROM lessons WHERE project=? AND language=? AND note=?",
                                  (project, language, note)).fetchone()
            if existing:
                return existing[0]
            cursor = db.execute("INSERT INTO lessons(project, language, note) VALUES (?, ?, ?)",
                                (project, language, note))
            return cursor.lastrowid

    def forget_lesson(self, project, lesson):
        with self.db() as db:
            deleted = db.execute("DELETE FROM lessons WHERE id=? AND project=?", (lesson, project))
            if not deleted.rowcount:
                raise ValueError("Lección desconocida en este proyecto.")

    def stage(self, session, ws, path, before, after):
        if before == after:
            raise ValueError("El contenido ya coincide.")
        change = uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT INTO changes VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                       (change, session, self.project_key(ws.root), path, before, after))
        return {"id": change, "path": path, "diff": diferencia(path, before, after)}

    def changes(self, session):
        with self.db() as db:
            return [{"id": i, "path": p, "state": s, "diff": diferencia(p, b, a)}
                    for i, p, b, a, s in db.execute(
                        "SELECT id, path, before, after, state FROM changes WHERE session=? "
                        "ORDER BY rowid DESC LIMIT 25", (session,))]

    def transition(self, session, ws, change, action):
        # Se confirma primero la intención. Una interrupción deja una operación recuperable.
        expected, intent, final = {
            "accept": ("pending", "applying", "applied"),
            "reject": ("pending", "rejected", "rejected"),
            "undo": ("applied", "undoing", "undone"),
        }[action]
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT path, before, after, state FROM changes "
                             "WHERE id=? AND session=? AND project=?",
                             (change, session, self.project_key(ws.root))).fetchone()
            if not row or row[3] not in (expected, intent):
                raise ValueError("El cambio no está disponible para esta operación.")
            path, before, after, state = row
            source, target = (after, before) if action == "undo" else (before, after)
            if action != "reject" and state == expected and ws.read(path, missing=True) != source:
                raise ValueError("El archivo cambió desde la previsualización.")
            db.execute("UPDATE changes SET state=? WHERE id=?", (intent, change))
        if action != "reject":
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                state = db.execute("SELECT state FROM changes WHERE id=?", (change,)).fetchone()[0]
                if state == intent:
                    if ws.read(path, missing=True) != target:
                        ws.replace(path, source, target)
                    db.execute("UPDATE changes SET state=? WHERE id=?", (final, change))
                elif state != final:
                    raise ValueError("El cambio se procesó en otra sesión.")
        return {"id": change, "path": path, "state": final}

    def change_state(self, session, change):
        with self.db() as db:
            row = db.execute("SELECT state FROM changes WHERE session=? AND id=?",
                             (session, change)).fetchone()
        return row[0] if row else None
