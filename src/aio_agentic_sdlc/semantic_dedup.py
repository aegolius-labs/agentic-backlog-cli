import glob
import os
import sqlite3
import threading
from typing import Any, Dict, List

import sqlite_vec
from filelock import FileLock

from .workspace import SPECS_DIR, WORKSPACE_DIR, workspace_file_path

# Lazy load sentence_transformers to speed up CLI for other commands
_model = None
_model_lock = threading.RLock()


def _cache_lock(project_path: str) -> FileLock:
    return FileLock(
        workspace_file_path(
            project_path,
            f"{WORKSPACE_DIR}/semantic-cache.lock",
        ),
        timeout=30,
        preserve_lock_file=True,
    )


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            # all-MiniLM-L6-v2 is small and fast, output dim = 384
            _model = SentenceTransformer("all-MiniLM-L6-v2")
        return _model


def _encode(model, texts):
    with _model_lock:
        return model.encode(texts)


def _get_db_unlocked(project_path: str) -> sqlite3.Connection:
    db_path = workspace_file_path(
        project_path,
        f"{WORKSPACE_DIR}/semantic-cache.db",
    )
    db = sqlite3.connect(db_path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    # Initialize schema
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS prd_embeddings USING vec0(
            embedding float[384]
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS prd_metadata (
            rowid INTEGER PRIMARY KEY,
            filepath TEXT UNIQUE,
            last_modified REAL
        )
    """)
    db.commit()
    return db


def get_db(project_path: str) -> sqlite3.Connection:
    with _cache_lock(project_path):
        return _get_db_unlocked(project_path)


def _sync_documents_unlocked(project_path: str, db: sqlite3.Connection, *, model=None):
    """Scan canonical specs and update embeddings for changed Markdown files."""
    specs_path = os.path.join(project_path, SPECS_DIR, "**", "*.md")

    files = glob.glob(specs_path, recursive=True)

    cursor = db.cursor()
    # Get existing metadata
    cursor.execute("SELECT rowid, filepath, last_modified FROM prd_metadata")
    existing = {
        row[1]: {"rowid": row[0], "last_modified": row[2]} for row in cursor.fetchall()
    }

    to_insert = []
    to_update = []
    to_delete = []
    current_files = set()

    for filepath in files:
        stat = os.stat(filepath)
        mtime = stat.st_mtime

        rel_path = os.path.relpath(filepath, project_path)
        current_files.add(rel_path)

        # Check if file needs embedding
        if rel_path not in existing:
            to_insert.append((rel_path, filepath, mtime))
        elif mtime > existing[rel_path]["last_modified"]:
            to_update.append((existing[rel_path]["rowid"], rel_path, filepath, mtime))

    # Check for deleted files
    for rel_path, data in existing.items():
        if rel_path not in current_files:
            to_delete.append(data["rowid"])

    if not to_insert and not to_update and not to_delete:
        return

    model = model or get_model()

    # Process deletions
    for rowid in to_delete:
        cursor.execute("DELETE FROM prd_metadata WHERE rowid = ?", (rowid,))
        cursor.execute("DELETE FROM prd_embeddings WHERE rowid = ?", (rowid,))

    # Process insertions
    for rel_path, filepath, mtime in to_insert:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            continue

        embedding = _encode(model, [content])[0]

        # Insert metadata to get rowid
        cursor.execute(
            "INSERT INTO prd_metadata (filepath, last_modified) VALUES (?, ?)",
            (rel_path, mtime),
        )
        rowid = cursor.lastrowid
        # Insert embedding
        cursor.execute(
            "INSERT INTO prd_embeddings (rowid, embedding) VALUES (?, ?)",
            (rowid, embedding.tobytes()),
        )

    # Process updates
    for rowid, rel_path, filepath, mtime in to_update:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            continue

        embedding = _encode(model, [content])[0]

        cursor.execute(
            "UPDATE prd_metadata SET last_modified = ? WHERE rowid = ?", (mtime, rowid)
        )
        # sqlite-vec virtual table update (delete and re-insert is safer for virtual tables)
        cursor.execute("DELETE FROM prd_embeddings WHERE rowid = ?", (rowid,))
        cursor.execute(
            "INSERT INTO prd_embeddings (rowid, embedding) VALUES (?, ?)",
            (rowid, embedding.tobytes()),
        )

    db.commit()


def sync_documents(project_path: str, db: sqlite3.Connection, *, model=None):
    """Serialize cache reconciliation for callers that manage the connection."""

    with _cache_lock(project_path):
        return _sync_documents_unlocked(project_path, db, model=model)


def find_duplicate_prds(
    proposed_text: str,
    project_path: str = ".",
    threshold: float = 0.2,
    *,
    model=None,
) -> List[Dict[str, Any]]:
    """
    Search for similar PRDs.
    Returns a list of matching documents.
    Note: threshold is cosine distance (0 to 2). Smaller is more similar.
    Distance of 0.2 means 0.8 cosine similarity.
    """
    with _cache_lock(project_path):
        db = _get_db_unlocked(project_path)
        try:
            model = model or get_model()
            _sync_documents_unlocked(project_path, db, model=model)
            query_embedding = _encode(model, [proposed_text])[0]

            cursor = db.cursor()
            cursor.execute(
                """
                SELECT m.filepath, e.distance
                FROM prd_embeddings e
                JOIN prd_metadata m ON m.rowid = e.rowid
                WHERE e.embedding MATCH ? AND k = 3
                ORDER BY e.distance ASC
            """,
                (query_embedding.tobytes(),),
            )

            results = []
            for row in cursor.fetchall():
                filepath, distance = row
                if distance <= threshold:
                    results.append(
                        {
                            "filepath": filepath,
                            "distance": distance,
                            "similarity_score": 1.0 - distance,
                        }
                    )
            return results
        finally:
            db.close()
