"""Сховище документів: SQLite + FTS5 (trigram — працює з відмінками)."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    author_name TEXT,
    author_tg_id INTEGER,
    source TEXT NOT NULL,              -- 'archive' | 'user'
    source_key TEXT UNIQUE,            -- ім'я файлу для архіву
    text TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    replaced_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_docs_active ON documents(is_active, scope, doc_type);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, text, content='documents', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
    INSERT INTO docs_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, text) VALUES ('delete', old.id, old.title, old.text);
END;
"""


@dataclass
class Doc:
    id: int
    title: str
    doc_type: str
    scope: str
    author_name: str | None
    author_tg_id: int | None
    source: str
    text: str
    uploaded_at: str
    is_active: int


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    @staticmethod
    def _doc(row: sqlite3.Row) -> Doc:
        keys = Doc.__dataclass_fields__.keys()
        return Doc(**{k: row[k] for k in keys})

    # --- користувачі ---
    def get_user_name(self, tg_id: int) -> str | None:
        row = self.db.execute("SELECT name FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return row["name"] if row else None

    def set_user_name(self, tg_id: int, name: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO users(tg_id, name) VALUES (?, ?) "
                "ON CONFLICT(tg_id) DO UPDATE SET name=excluded.name",
                (tg_id, name),
            )

    # --- документи ---
    def add_document(
        self,
        *,
        title: str,
        doc_type: str,
        scope: str,
        text: str,
        source: str,
        author_name: str | None = None,
        author_tg_id: int | None = None,
        source_key: str | None = None,
        uploaded_at: str | None = None,
        replace_ids: tuple[int, ...] | list[int] = (),
    ) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO documents(title, doc_type, scope, author_name, author_tg_id, "
                "source, source_key, text, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (title, doc_type, scope, author_name, author_tg_id, source, source_key,
                 text, uploaded_at or now_iso()),
            )
            new_id = cur.lastrowid
            for old_id in replace_ids:
                self.db.execute(
                    "UPDATE documents SET is_active=0, replaced_by=? WHERE id=?", (new_id, old_id)
                )
        return new_id

    def has_source_key(self, key: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM documents WHERE source_key=?", (key,)
        ).fetchone() is not None

    def get(self, doc_id: int) -> Doc | None:
        row = self.db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return self._doc(row) if row else None

    def all_active(self) -> list[Doc]:
        rows = self.db.execute("SELECT * FROM documents WHERE is_active=1").fetchall()
        return [self._doc(r) for r in rows]

    def active_in_scopes(self, scopes) -> list[Doc]:
        scopes = sorted(scopes)
        if not scopes:
            return []
        q = ",".join("?" * len(scopes))
        rows = self.db.execute(
            f"SELECT * FROM documents WHERE is_active=1 AND scope IN ({q})", scopes
        ).fetchall()
        return [self._doc(r) for r in rows]

    def user_docs(self, tg_id: int) -> list[Doc]:
        rows = self.db.execute(
            "SELECT * FROM documents WHERE is_active=1 AND author_tg_id=? ORDER BY id DESC",
            (tg_id,),
        ).fetchall()
        return [self._doc(r) for r in rows]

    def deactivate(self, doc_id: int, tg_id: int) -> bool:
        """Автор може прибрати лише власний документ."""
        with self.db:
            cur = self.db.execute(
                "UPDATE documents SET is_active=0 WHERE id=? AND author_tg_id=? AND is_active=1",
                (doc_id, tg_id),
            )
        return cur.rowcount > 0

    def search(self, terms: list[str], scopes=None, limit: int = 16) -> list[Doc]:
        if not terms:
            return []
        match = " OR ".join('"%s"' % t.replace('"', "") for t in terms)
        sql = (
            "SELECT d.* FROM docs_fts JOIN documents d ON d.id = docs_fts.rowid "
            "WHERE docs_fts MATCH ? AND d.is_active=1"
        )
        params: list = [match]
        if scopes:
            scopes = sorted(scopes)
            sql += f" AND d.scope IN ({','.join('?' * len(scopes))})"
            params += scopes
        sql += " ORDER BY bm25(docs_fts, 3.0, 1.0) LIMIT ?"
        params.append(limit)
        return [self._doc(r) for r in self.db.execute(sql, params).fetchall()]

    def count(self, source: str | None = None) -> int:
        if source:
            return self.db.execute(
                "SELECT COUNT(*) FROM documents WHERE source=?", (source,)
            ).fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
