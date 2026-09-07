#!/usr/bin/env python3
"""BCOBA Digital Hub — 1st cut ops core.

Run:  python3 server.py
Open: http://localhost:8787
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from hub_crypto import decrypt_secret, encrypt_secret, secret_fingerprint
from publishers.social import (
    PublishError,
    publish_for_channel,
    publish_facebook,
    sync_metrics_for_channel,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "hub.sqlite"
TEMPLATES_PATH = DATA_DIR / "post_templates.json"
DIAGRAMS_PATH = DATA_DIR / "process_diagrams.json"
HOST = "0.0.0.0"
PORT = 8787


def load_process_diagrams() -> list[dict]:
    if not DIAGRAMS_PATH.is_file():
        return []
    try:
        data = json.loads(DIAGRAMS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("diagrams") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def save_process_diagrams(diagrams: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DIAGRAMS_PATH.write_text(
        json.dumps({"diagrams": diagrams}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_post_templates() -> list[dict]:
    if not TEMPLATES_PATH.is_file():
        return []
    try:
        data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("templates") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def save_post_templates(templates: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_PATH.write_text(
        json.dumps({"templates": templates}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

CHANNELS = ("facebook", "instagram", "linkedin", "whatsapp", "youtube")
ROLES = ("admin", "contributor", "editor", "approver", "channel_admin")
CONTENT_STATUSES = (
    "draft",
    "submitted",
    "in_review",
    "changes_requested",
    "approved",
    "scheduled",
    "published",
    "rejected",
)
CAMPAIGN_STATUSES = ("planned", "active", "ongoing", "completed", "archived")

SLUG_RE = re.compile(r"[^a-z0-9]+")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return secrets.compare_digest(check, digest)


def slugify(text: str) -> str:
    s = SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return s or "item"


def normalize_hashtag(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.replace(" ", "")
    if not text.startswith("#"):
        text = "#" + text
    # Keep letters/numbers/underscore only after #
    body = re.sub(r"[^\w]", "", text[1:], flags=re.UNICODE)
    return f"#{body}" if body else ""


def parse_hashtag_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r"[\s,]+", str(value))
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = normalize_hashtag(part)
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def ensure_custom_tag(conn: sqlite3.Connection, name: str) -> str | None:
    tag = normalize_hashtag(name)
    if not tag:
        return None
    row = conn.execute(
        "SELECT id FROM tags WHERE lower(name) = lower(?)", (tag,)
    ).fetchone()
    if row:
        return row["id"]
    tid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO tags (id, name, kind, category_id, campaign_id) VALUES (?,?, 'custom', NULL, NULL)",
        (tid, tag),
    )
    return tid


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def rows_to_list(rows) -> list[dict]:
    return [row_to_dict(r) for r in rows]


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              slug TEXT NOT NULL UNIQUE,
              hashtag TEXT NOT NULL DEFAULT '',
              sort_order INTEGER NOT NULL DEFAULT 0,
              active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS campaigns (
              id TEXT PRIMARY KEY,
              category_id TEXT NOT NULL REFERENCES categories(id),
              name TEXT NOT NULL,
              slug TEXT NOT NULL UNIQUE,
              owner TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'planned',
              start_date TEXT DEFAULT '',
              end_date TEXT DEFAULT '',
              hashtag TEXT NOT NULL DEFAULT '',
              landing_page TEXT NOT NULL DEFAULT '',
              description TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              kind TEXT NOT NULL,
              category_id TEXT REFERENCES categories(id),
              campaign_id TEXT REFERENCES campaigns(id)
            );

            CREATE TABLE IF NOT EXISTS content_items (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              body TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '',
              category_id TEXT NOT NULL REFERENCES categories(id),
              campaign_id TEXT REFERENCES campaigns(id),
              status TEXT NOT NULL DEFAULT 'submitted',
              submitter_id TEXT REFERENCES users(id),
              editor_id TEXT REFERENCES users(id),
              approver_id TEXT REFERENCES users(id),
              scheduled_at TEXT DEFAULT '',
              published_at TEXT DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS content_channels (
              id TEXT PRIMARY KEY,
              content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
              channel TEXT NOT NULL,
              body TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'draft',
              live_url TEXT NOT NULL DEFAULT '',
              reach INTEGER NOT NULL DEFAULT 0,
              likes INTEGER NOT NULL DEFAULT 0,
              comments INTEGER NOT NULL DEFAULT 0,
              shares INTEGER NOT NULL DEFAULT 0,
              UNIQUE(content_id, channel)
            );

            CREATE TABLE IF NOT EXISTS content_tags (
              content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
              tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
              PRIMARY KEY (content_id, tag_id)
            );

            CREATE TABLE IF NOT EXISTS media_assets (
              id TEXT PRIMARY KEY,
              filename TEXT NOT NULL,
              original_name TEXT NOT NULL,
              mime TEXT NOT NULL DEFAULT '',
              path TEXT NOT NULL,
              category_id TEXT REFERENCES categories(id),
              campaign_id TEXT REFERENCES campaigns(id),
              caption TEXT NOT NULL DEFAULT '',
              uploaded_by TEXT REFERENCES users(id),
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS content_media (
              content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
              media_id TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
              PRIMARY KEY (content_id, media_id)
            );

            CREATE TABLE IF NOT EXISTS engagement_logs (
              id TEXT PRIMARY KEY,
              content_id TEXT REFERENCES content_items(id) ON DELETE SET NULL,
              platform TEXT NOT NULL,
              note TEXT NOT NULL DEFAULT '',
              link TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'open',
              assigned_to TEXT REFERENCES users(id),
              escalated_to TEXT NOT NULL DEFAULT '',
              created_by TEXT REFERENCES users(id),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        # Lightweight migrations for WhatsApp channel metadata
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(content_channels)").fetchall()
        }
        if "wa_target" not in cols:
            conn.execute(
                "ALTER TABLE content_channels ADD COLUMN wa_target TEXT NOT NULL DEFAULT ''"
            )
        if "meta_json" not in cols:
            conn.execute(
                "ALTER TABLE content_channels ADD COLUMN meta_json TEXT NOT NULL DEFAULT ''"
            )
        if "platform_post_id" not in cols:
            conn.execute(
                "ALTER TABLE content_channels ADD COLUMN platform_post_id TEXT NOT NULL DEFAULT ''"
            )
        if "last_synced_at" not in cols:
            conn.execute(
                "ALTER TABLE content_channels ADD COLUMN last_synced_at TEXT NOT NULL DEFAULT ''"
            )
        if "publish_error" not in cols:
            conn.execute(
                "ALTER TABLE content_channels ADD COLUMN publish_error TEXT NOT NULL DEFAULT ''"
            )
        if "metrics_source" not in cols:
            conn.execute(
                "ALTER TABLE content_channels ADD COLUMN metrics_source TEXT NOT NULL DEFAULT 'manual'"
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_connections (
              id TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              label TEXT NOT NULL DEFAULT '',
              account_id TEXT NOT NULL DEFAULT '',
              access_token_enc TEXT NOT NULL DEFAULT '',
              refresh_token_enc TEXT NOT NULL DEFAULT '',
              token_hint TEXT NOT NULL DEFAULT '',
              auto_publish INTEGER NOT NULL DEFAULT 1,
              active INTEGER NOT NULL DEFAULT 1,
              meta_json TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(platform, account_id)
            );
            """
        )
        seed_if_empty(conn)


def seed_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count:
        return

    now = now_iso()
    users = [
        ("u-admin", "Hub Admin", "admin@bcoba.lk", "admin123", "admin"),
        ("u-editor", "Digital Editor", "editor@bcoba.lk", "editor123", "editor"),
        ("u-approver", "Comms Approver", "approver@bcoba.lk", "approve123", "approver"),
        ("u-contrib", "Batch Contributor", "contributor@bcoba.lk", "contrib123", "contributor"),
        ("u-channel", "Channel Admin", "channel@bcoba.lk", "channel123", "channel_admin"),
    ]
    for uid, name, email, password, role in users:
        conn.execute(
            "INSERT INTO users (id, name, email, password_hash, role, active, created_at) VALUES (?,?,?,?,?,1,?)",
            (uid, name, email, hash_password(password), role, now),
        )

    categories = [
        ("cat-official", "Official", "official", "#BCOBAOfficial", 1),
        ("cat-school", "School", "school", "#BCOBASchool", 2),
        ("cat-projects", "Projects", "projects", "#BCOBAProjects", 3),
        ("cat-fundraising", "Fundraising", "fundraising", "#BCOBAFundraising", 4),
        ("cat-alumni", "Alumni", "alumni", "#BCOBAAlumni", 5),
        ("cat-membership", "Membership", "membership", "#BCOBAMembership", 6),
        ("cat-events", "Events", "events", "#BCOBAEvents", 7),
        ("cat-sports", "Sports", "sports", "#BCOBASports", 8),
        ("cat-careers", "Careers", "careers", "#BCOBACareers", 9),
        ("cat-csr", "CSR", "csr", "#BCOBACSR", 10),
        ("cat-sponsors", "Sponsors", "sponsors", "#BCOBASponsors", 11),
        ("cat-history", "History", "history", "#BCOBAHistory", 12),
    ]
    for cid, name, slug, tag, order in categories:
        conn.execute(
            "INSERT INTO categories (id, name, slug, hashtag, sort_order, active) VALUES (?,?,?,?,?,1)",
            (cid, name, slug, tag, order),
        )
        conn.execute(
            "INSERT INTO tags (id, name, kind, category_id, campaign_id) VALUES (?,?,?,?,NULL)",
            (f"tag-{slug}", tag, "category", cid),
        )

    for tid, name in (
        ("tag-bcoba", "#BCOBA"),
        ("tag-bandaranayake", "#BandaranayakeCollege"),
    ):
        conn.execute(
            "INSERT INTO tags (id, name, kind, category_id, campaign_id) VALUES (?,?, 'master', NULL, NULL)",
            (tid, name),
        )

    conn.execute(
        """
        INSERT INTO campaigns (
          id, category_id, name, slug, owner, status, start_date, end_date,
          hashtag, landing_page, description, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "camp-main-hall",
            "cat-projects",
            "Main Hall Development",
            "main-hall-development",
            "Development Committee",
            "active",
            "2026-01-01",
            "",
            "#RestoringThePride",
            "http://localhost:8765",
            "First major campaign to validate the BCOBA Digital Hub. Not hard-coded — created via normal administration.",
            now,
        ),
    )
    conn.execute(
        "INSERT INTO tags (id, name, kind, category_id, campaign_id) VALUES (?,?, 'campaign', ?, ?)",
        ("tag-main-hall", "#RestoringThePride", "cat-projects", "camp-main-hall"),
    )

    # Sample submitted item so queue is not empty
    cid = "content-sample-1"
    conn.execute(
        """
        INSERT INTO content_items (
          id, title, body, notes, category_id, campaign_id, status,
          submitter_id, scheduled_at, published_at, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            cid,
            "Main Hall progress update — Week sample",
            "Foundation and structural works continue. Alumni support is restoring the pride of Bandaranayake College.",
            "Please adapt for Facebook and WhatsApp.",
            "cat-projects",
            "camp-main-hall",
            "submitted",
            "u-contrib",
            "",
            "",
            now,
            now,
        ),
    )
    for ch in CHANNELS:
        conn.execute(
            """
            INSERT INTO content_channels (id, content_id, channel, body, status)
            VALUES (?,?,?,?, 'draft')
            """,
            (str(uuid.uuid4()), cid, ch, ""),
        )
    attach_auto_tags(conn, cid, "cat-projects", "camp-main-hall")
    conn.commit()


def attach_auto_tags(
    conn: sqlite3.Connection,
    content_id: str,
    category_id: str | None,
    campaign_id: str | None,
    extra_tag_ids: list[str] | None = None,
    extra_tags: list[str] | None = None,
) -> None:
    conn.execute("DELETE FROM content_tags WHERE content_id = ?", (content_id,))
    tag_ids: set[str] = set()
    for row in conn.execute("SELECT id FROM tags WHERE kind = 'master'"):
        tag_ids.add(row["id"])
    if category_id:
        for row in conn.execute(
            "SELECT id FROM tags WHERE kind = 'category' AND category_id = ?",
            (category_id,),
        ):
            tag_ids.add(row["id"])
    if campaign_id:
        for row in conn.execute(
            "SELECT id FROM tags WHERE kind = 'campaign' AND campaign_id = ?",
            (campaign_id,),
        ):
            tag_ids.add(row["id"])
    for tid in extra_tag_ids or []:
        if tid:
            tag_ids.add(tid)
    for name in parse_hashtag_list(extra_tags):
        tid = ensure_custom_tag(conn, name)
        if tid:
            tag_ids.add(tid)
    for tid in tag_ids:
        conn.execute(
            "INSERT OR IGNORE INTO content_tags (content_id, tag_id) VALUES (?, ?)",
            (content_id, tid),
        )


def connection_public(row: sqlite3.Row | dict) -> dict:
    data = row_to_dict(row) if not isinstance(row, dict) else dict(row)
    data.pop("access_token_enc", None)
    data.pop("refresh_token_enc", None)
    data["has_token"] = bool(row["access_token_enc"] if not isinstance(row, dict) else row.get("access_token_enc"))
    return data


def get_active_connection(conn: sqlite3.Connection, platform: str) -> dict | None:
    row = conn.execute(
        """
        SELECT * FROM platform_connections
        WHERE platform = ? AND active = 1
        ORDER BY updated_at DESC LIMIT 1
        """,
        (platform,),
    ).fetchone()
    if not row:
        return None
    data = row_to_dict(row)
    data["access_token"] = decrypt_secret(data.get("access_token_enc") or "")
    data["refresh_token"] = decrypt_secret(data.get("refresh_token_enc") or "")
    return data


def first_media_public_url(conn: sqlite3.Connection, content_id: str, base: str) -> str:
    row = conn.execute(
        """
        SELECT m.path FROM media_assets m
        JOIN content_media cm ON cm.media_id = m.id
        WHERE cm.content_id = ?
        ORDER BY m.created_at DESC LIMIT 1
        """,
        (content_id,),
    ).fetchone()
    if not row:
        return ""
    path = row["path"] or ""
    if path.startswith("http"):
        return path
    return f"{base.rstrip('/')}{path}"


def publish_content_channels(
    conn: sqlite3.Connection,
    content_id: str,
    *,
    channels: list[str] | None = None,
    public_base: str = "http://127.0.0.1:8787",
) -> dict:
    item = content_with_relations(conn, content_id)
    if not item:
        raise PublishError("Content not found")
    if item.get("status") == "draft":
        raise PublishError("This post is still a draft. Submit/approve it before publishing.")
    results = []
    wanted = set(channels or CHANNELS)
    for ch in item.get("channels") or []:
        platform = ch["channel"]
        if platform not in wanted:
            continue
        if platform == "whatsapp":
            results.append(
                {
                    "channel": platform,
                    "ok": False,
                    "skipped": True,
                    "error": "WhatsApp stays manual (copy & send pack).",
                }
            )
            continue
        connection = get_active_connection(conn, platform)
        if not connection or not connection.get("auto_publish"):
            results.append(
                {
                    "channel": platform,
                    "ok": False,
                    "skipped": True,
                    "error": f"No active auto-publish connection for {platform}",
                }
            )
            continue
        message = (ch.get("body") or item.get("body") or item.get("title") or "").strip()
        tags = " ".join(t["name"] for t in item.get("tags") or [])
        if tags and tags not in message:
            message = f"{message}\n\n{tags}".strip()
        image_url = first_media_public_url(conn, content_id, public_base)
        try:
            published = publish_for_channel(
                platform,
                connection,
                message=message,
                image_url=image_url,
                link=ch.get("live_url") or "",
            )
            conn.execute(
                """
                UPDATE content_channels
                SET status = 'published',
                    live_url = COALESCE(NULLIF(?, ''), live_url),
                    platform_post_id = ?,
                    publish_error = '',
                    metrics_source = 'api'
                WHERE content_id = ? AND channel = ?
                """,
                (
                    published.get("live_url") or "",
                    published.get("platform_post_id") or "",
                    content_id,
                    platform,
                ),
            )
            results.append(
                {
                    "channel": platform,
                    "ok": True,
                    "platform_post_id": published.get("platform_post_id"),
                    "live_url": published.get("live_url"),
                }
            )
        except PublishError as exc:
            conn.execute(
                """
                UPDATE content_channels
                SET publish_error = ?
                WHERE content_id = ? AND channel = ?
                """,
                (str(exc)[:500], content_id, platform),
            )
            results.append({"channel": platform, "ok": False, "error": str(exc)})
    ok_any = any(r.get("ok") for r in results)
    if ok_any:
        conn.execute(
            """
            UPDATE content_items
            SET status = 'published', published_at = CASE
              WHEN published_at IS NULL OR published_at = '' THEN ? ELSE published_at END,
              updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), now_iso(), content_id),
        )
    conn.commit()
    return {"results": results, "item": content_with_relations(conn, content_id)}


def sync_content_analytics(conn: sqlite3.Connection, content_id: str) -> dict:
    item = content_with_relations(conn, content_id)
    if not item:
        raise PublishError("Content not found")
    results = []
    for ch in item.get("channels") or []:
        platform = ch["channel"]
        post_id = ch.get("platform_post_id") or ""
        if not post_id:
            results.append({"channel": platform, "ok": False, "skipped": True, "error": "No platform post id"})
            continue
        connection = get_active_connection(conn, platform)
        if not connection:
            results.append({"channel": platform, "ok": False, "error": "No connection"})
            continue
        try:
            metrics = sync_metrics_for_channel(platform, connection, post_id)
            conn.execute(
                """
                UPDATE content_channels
                SET reach = ?, likes = ?, comments = ?, shares = ?,
                    last_synced_at = ?, metrics_source = 'api', publish_error = ''
                WHERE content_id = ? AND channel = ?
                """,
                (
                    metrics["reach"],
                    metrics["likes"],
                    metrics["comments"],
                    metrics["shares"],
                    now_iso(),
                    content_id,
                    platform,
                ),
            )
            results.append({"channel": platform, "ok": True, "metrics": metrics})
        except PublishError as exc:
            results.append({"channel": platform, "ok": False, "error": str(exc)})
    conn.commit()
    return {"results": results, "item": content_with_relations(conn, content_id)}


def run_due_scheduled_publishes(public_base: str = "http://127.0.0.1:8787") -> list[dict]:
    now = now_iso()
    out = []
    with connect() as conn:
        rows = rows_to_list(
            conn.execute(
                """
                SELECT id FROM content_items
                WHERE status = 'scheduled'
                  AND scheduled_at != ''
                  AND scheduled_at <= ?
                ORDER BY scheduled_at
                LIMIT 20
                """,
                (now,),
            )
        )
        for row in rows:
            try:
                result = publish_content_channels(conn, row["id"], public_base=public_base)
                out.append({"id": row["id"], "ok": True, "result": result["results"]})
            except Exception as exc:  # noqa: BLE001
                out.append({"id": row["id"], "ok": False, "error": str(exc)})
    return out


def get_user_by_token(conn: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT u.* FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ? AND u.active = 1
        """,
        (token, now_iso()),
    ).fetchone()
    return row_to_dict(row)


def content_with_relations(conn: sqlite3.Connection, content_id: str) -> dict | None:
    item = conn.execute(
        """
        SELECT c.*,
               cat.name AS category_name,
               camp.name AS campaign_name,
               su.name AS submitter_name
        FROM content_items c
        JOIN categories cat ON cat.id = c.category_id
        LEFT JOIN campaigns camp ON camp.id = c.campaign_id
        LEFT JOIN users su ON su.id = c.submitter_id
        WHERE c.id = ?
        """,
        (content_id,),
    ).fetchone()
    if not item:
        return None
    data = row_to_dict(item)
    data["channels"] = rows_to_list(
        conn.execute(
            "SELECT * FROM content_channels WHERE content_id = ? ORDER BY channel",
            (content_id,),
        )
    )
    data["tags"] = rows_to_list(
        conn.execute(
            """
            SELECT t.* FROM tags t
            JOIN content_tags ct ON ct.tag_id = t.id
            WHERE ct.content_id = ?
            ORDER BY t.kind, t.name
            """,
            (content_id,),
        )
    )
    data["media"] = rows_to_list(
        conn.execute(
            """
            SELECT m.* FROM media_assets m
            JOIN content_media cm ON cm.media_id = m.id
            WHERE cm.content_id = ?
            ORDER BY m.created_at DESC
            """,
            (content_id,),
        )
    )
    return data


def ensure_channel_rows(conn: sqlite3.Connection, content_id: str) -> None:
    for ch in CHANNELS:
        conn.execute(
            """
            INSERT OR IGNORE INTO content_channels (id, content_id, channel, body, status)
            VALUES (?,?,?, '', 'draft')
            """,
            (str(uuid.uuid4()), content_id, ch),
        )


def can_approve(role: str) -> bool:
    return role in ("admin", "approver")


def can_edit(role: str) -> bool:
    return role in ("admin", "editor", "approver")


def can_manage(role: str) -> bool:
    return role == "admin"


class HubHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[hub] {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code: int, payload) -> None:
        body = json_dumps(payload).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def bearer_token(self) -> str | None:
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return self.headers.get("X-Hub-Token")

    def require_user(self, conn: sqlite3.Connection, roles: tuple[str, ...] | None = None):
        user = get_user_by_token(conn, self.bearer_token())
        if not user:
            self.send_json(401, {"ok": False, "error": "Unauthorized"})
            return None
        if roles and user["role"] not in roles and user["role"] != "admin":
            self.send_json(403, {"ok": False, "error": "Forbidden"})
            return None
        return user

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Hub-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)

        if path.startswith("/api/"):
            self.handle_api_get(path, qs)
            return

        if path.startswith("/uploads/"):
            self.serve_upload(path)
            return

        if path == "/":
            path = "/index.html"

        file_path = (ROOT / path.lstrip("/")).resolve()
        if str(file_path).startswith(str(ROOT)) and file_path.is_file():
            data = file_path.read_bytes()
            ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            self._send(200, data, ctype)
            return

        self.send_json(404, {"ok": False, "error": "Not found"})

    def serve_upload(self, path: str) -> None:
        name = path.split("/uploads/", 1)[-1]
        file_path = (UPLOAD_DIR / name).resolve()
        if not str(file_path).startswith(str(UPLOAD_DIR.resolve())) or not file_path.is_file():
            self.send_json(404, {"ok": False, "error": "File not found"})
            return
        data = file_path.read_bytes()
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self._send(200, data, ctype)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            self.handle_api_post(path)
            return
        self.send_json(404, {"ok": False, "error": "Not found"})

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            self.handle_api_put(path)
            return
        self.send_json(404, {"ok": False, "error": "Not found"})

    def do_PATCH(self) -> None:
        self.do_PUT()

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not path.startswith("/api/"):
            self.send_json(404, {"ok": False, "error": "Not found"})
            return
        with connect() as conn:
            user = self.require_user(conn)
            if not user:
                return
            if path.startswith("/api/templates/"):
                if user["role"] not in ("admin", "editor", "approver"):
                    self.send_json(403, {"ok": False, "error": "Editor/admin required"})
                    return
                tid = path.split("/api/templates/", 1)[1]
                templates = load_post_templates()
                target = next((t for t in templates if t.get("id") == tid), None)
                if not target:
                    self.send_json(404, {"ok": False, "error": "Template not found"})
                    return
                if target.get("builtin"):
                    self.send_json(400, {"ok": False, "error": "Cannot delete built-in template"})
                    return
                templates = [t for t in templates if t.get("id") != tid]
                save_post_templates(templates)
                self.send_json(200, {"ok": True, "templates": templates})
                return
            if path.startswith("/api/connections/"):
                if not can_manage(user["role"]) and user["role"] not in ("approver", "editor"):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                cid = path.split("/api/connections/", 1)[1]
                conn.execute("DELETE FROM platform_connections WHERE id = ?", (cid,))
                conn.commit()
                self.send_json(200, {"ok": True})
                return
            if path.startswith("/api/diagrams/"):
                if user["role"] not in ("admin", "editor", "approver"):
                    self.send_json(403, {"ok": False, "error": "Editor/admin required"})
                    return
                did = path.split("/api/diagrams/", 1)[1]
                before = load_process_diagrams()
                if not any(d.get("id") == did for d in before):
                    self.send_json(404, {"ok": False, "error": "Diagram not found"})
                    return
                diagrams = [d for d in before if d.get("id") != did]
                save_process_diagrams(diagrams)
                self.send_json(200, {"ok": True, "diagrams": diagrams})
                return
            self.send_json(404, {"ok": False, "error": "Unknown API route"})

    def handle_api_get(self, path: str, qs: dict) -> None:
        with connect() as conn:
            if path == "/api/health":
                counts = {
                    "users": conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
                    "campaigns": conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"],
                    "content": conn.execute("SELECT COUNT(*) c FROM content_items").fetchone()["c"],
                    "media": conn.execute("SELECT COUNT(*) c FROM media_assets").fetchone()["c"],
                }
                self.send_json(200, {"ok": True, "db": "sqlite", "counts": counts})
                return

            if path == "/api/me":
                user = self.require_user(conn)
                if not user:
                    return
                user.pop("password_hash", None)
                self.send_json(200, {"ok": True, "user": user})
                return

            user = self.require_user(conn)
            if not user:
                return

            if path == "/api/dashboard":
                self.send_json(200, {"ok": True, "data": self.dashboard(conn, user)})
                return

            if path == "/api/categories":
                rows = rows_to_list(
                    conn.execute(
                        "SELECT * FROM categories WHERE active = 1 ORDER BY sort_order, name"
                    )
                )
                self.send_json(200, {"ok": True, "items": rows})
                return

            if path == "/api/campaigns":
                status = (qs.get("status") or [""])[0]
                sql = """
                    SELECT camp.*, cat.name AS category_name
                    FROM campaigns camp
                    JOIN categories cat ON cat.id = camp.category_id
                """
                args: list = []
                if status:
                    sql += " WHERE camp.status = ?"
                    args.append(status)
                sql += " ORDER BY camp.created_at DESC"
                self.send_json(200, {"ok": True, "items": rows_to_list(conn.execute(sql, args))})
                return

            if path == "/api/tags":
                kind = (qs.get("kind") or [""])[0]
                sql = "SELECT * FROM tags"
                args: list = []
                if kind:
                    sql += " WHERE kind = ?"
                    args.append(kind)
                sql += " ORDER BY kind, name"
                self.send_json(
                    200,
                    {"ok": True, "items": rows_to_list(conn.execute(sql, args))},
                )
                return

            if path == "/api/content":
                self.send_json(200, {"ok": True, "items": self.list_content(conn, qs)})
                return

            if path.startswith("/api/content/"):
                cid = path.split("/api/content/", 1)[1]
                item = content_with_relations(conn, cid)
                if not item:
                    self.send_json(404, {"ok": False, "error": "Content not found"})
                    return
                self.send_json(200, {"ok": True, "item": item})
                return

            if path == "/api/calendar":
                self.send_json(200, {"ok": True, "items": self.calendar_items(conn, qs)})
                return

            if path == "/api/media":
                self.send_json(200, {"ok": True, "items": self.list_media(conn, qs)})
                return

            if path == "/api/engagement":
                self.send_json(200, {"ok": True, "items": self.list_engagement(conn, qs)})
                return

            if path == "/api/analytics":
                data = self.analytics(conn)
                data["source_note"] = (
                    "Prefer live API sync when platform credentials are saved "
                    "(Publisher → Sync analytics). Sample/demo posts may still show seeded numbers. "
                    "Manual metrics remain available as fallback."
                )
                data["is_sample"] = bool(
                    conn.execute(
                        "SELECT 1 FROM content_items WHERE id LIKE 'demo-%' LIMIT 1"
                    ).fetchone()
                )
                api_synced = conn.execute(
                    "SELECT COUNT(*) c FROM content_channels WHERE metrics_source = 'api' AND platform_post_id != ''"
                ).fetchone()["c"]
                data["api_synced_channels"] = api_synced
                connected = conn.execute(
                    "SELECT platform, COUNT(*) c FROM platform_connections WHERE active = 1 GROUP BY platform"
                ).fetchall()
                data["connections"] = {r["platform"]: r["c"] for r in connected}
                self.send_json(200, {"ok": True, "data": data})
                return

            if path == "/api/brand":
                brand_path = DATA_DIR / "brand_guidelines.json"
                if not brand_path.is_file():
                    self.send_json(404, {"ok": False, "error": "Brand guidelines missing"})
                    return
                brand = json.loads(brand_path.read_text(encoding="utf-8"))
                self.send_json(200, {"ok": True, "brand": brand})
                return

            if path == "/api/templates":
                self.send_json(200, {"ok": True, "templates": load_post_templates()})
                return

            if path == "/api/diagrams":
                self.send_json(200, {"ok": True, "diagrams": load_process_diagrams()})
                return

            if path.startswith("/api/diagrams/"):
                did = path.split("/api/diagrams/", 1)[1]
                item = next((d for d in load_process_diagrams() if d.get("id") == did), None)
                if not item:
                    self.send_json(404, {"ok": False, "error": "Diagram not found"})
                    return
                self.send_json(200, {"ok": True, "diagram": item})
                return

            if path == "/api/connections":
                rows = rows_to_list(
                    conn.execute(
                        "SELECT * FROM platform_connections ORDER BY platform, label"
                    )
                )
                self.send_json(
                    200, {"ok": True, "items": [connection_public(r) for r in rows]}
                )
                return

            if path == "/api/users":
                if not can_manage(user["role"]):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                users = rows_to_list(
                    conn.execute(
                        "SELECT id, name, email, role, active, created_at FROM users ORDER BY name"
                    )
                )
                self.send_json(200, {"ok": True, "items": users})
                return

            self.send_json(404, {"ok": False, "error": "Unknown API route"})

    def handle_api_post(self, path: str) -> None:
        with connect() as conn:
            if path == "/api/auth/login":
                body = self.read_json()
                email = (body.get("email") or "").strip().lower()
                password = body.get("password") or ""
                row = conn.execute(
                    "SELECT * FROM users WHERE lower(email) = ? AND active = 1", (email,)
                ).fetchone()
                if not row or not verify_password(password, row["password_hash"]):
                    self.send_json(401, {"ok": False, "error": "Invalid email or password"})
                    return
                token = secrets.token_urlsafe(32)
                expires = (datetime.now(timezone.utc) + timedelta(days=14)).replace(
                    microsecond=0
                ).isoformat().replace("+00:00", "Z")
                conn.execute(
                    "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                    (token, row["id"], now_iso(), expires),
                )
                conn.commit()
                user = row_to_dict(row)
                user.pop("password_hash", None)
                self.send_json(200, {"ok": True, "token": token, "user": user})
                return

            if path == "/api/auth/logout":
                token = self.bearer_token()
                if token:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                    conn.commit()
                self.send_json(200, {"ok": True})
                return

            user = self.require_user(conn)
            if not user:
                return

            if path == "/api/seed":
                if not can_manage(user["role"]):
                    self.send_json(403, {"ok": False, "error": "Admin only"})
                    return
                body = self.read_json()
                force = bool(body.get("force"))
                if str(ROOT) not in sys.path:
                    sys.path.insert(0, str(ROOT))
                from scripts.seed_sample import seed as seed_sample

                result = seed_sample(force=force)
                self.send_json(200, {"ok": True, **result})
                return

            if path == "/api/templates":
                if user["role"] not in ("admin", "editor", "approver"):
                    self.send_json(403, {"ok": False, "error": "Editor/admin required"})
                    return
                body = self.read_json()
                name = (body.get("name") or "").strip()
                if not name:
                    self.send_json(400, {"ok": False, "error": "name required"})
                    return
                accent = (body.get("accent") or "#0A1F38").strip()
                if not re.fullmatch(r"#[0-9A-Fa-f]{6}", accent):
                    self.send_json(400, {"ok": False, "error": "accent must be #RRGGBB"})
                    return
                hint = (body.get("hint") or "").strip()
                tid = slugify(body.get("id") or name)
                templates = load_post_templates()
                if any(t.get("id") == tid for t in templates):
                    tid = f"{tid}-{secrets.token_hex(2)}"
                item = {
                    "id": tid,
                    "name": name,
                    "accent": accent,
                    "hint": hint or "Custom template",
                    "builtin": False,
                    "defaults": {
                        "headline": (body.get("headline") or name).strip(),
                        "body": (body.get("body") or "").strip(),
                        "footer": (body.get("footer") or "BCOBA · Official").strip(),
                        "tags": (body.get("tags") or "#BCOBA #BandaranayakeCollege").strip(),
                    },
                }
                templates.append(item)
                save_post_templates(templates)
                self.send_json(201, {"ok": True, "item": item, "templates": templates})
                return

            if path == "/api/connections":
                if not can_manage(user["role"]) and user["role"] not in ("approver", "editor"):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                body = self.read_json()
                platform = (body.get("platform") or "").strip().lower()
                if platform not in CHANNELS:
                    self.send_json(400, {"ok": False, "error": "Invalid platform"})
                    return
                token = (body.get("access_token") or "").strip()
                if not token:
                    self.send_json(400, {"ok": False, "error": "access_token required"})
                    return
                cid = str(uuid.uuid4())
                now = now_iso()
                account_id = (body.get("account_id") or "").strip()
                conn.execute(
                    """
                    INSERT INTO platform_connections (
                      id, platform, label, account_id, access_token_enc, refresh_token_enc,
                      token_hint, auto_publish, active, meta_json, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,1,?,?,?)
                    """,
                    (
                        cid,
                        platform,
                        (body.get("label") or platform.title()).strip(),
                        account_id,
                        encrypt_secret(token),
                        encrypt_secret((body.get("refresh_token") or "").strip()),
                        secret_fingerprint(token),
                        1 if body.get("auto_publish", True) else 0,
                        json_dumps(body.get("meta") or {}),
                        now,
                        now,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM platform_connections WHERE id = ?", (cid,)
                ).fetchone()
                self.send_json(201, {"ok": True, "item": connection_public(row)})
                return

            if path == "/api/diagrams":
                if user["role"] not in ("admin", "editor", "approver"):
                    self.send_json(403, {"ok": False, "error": "Editor/admin required"})
                    return
                body = self.read_json()
                title = (body.get("title") or "").strip()
                if not title:
                    self.send_json(400, {"ok": False, "error": "title required"})
                    return
                diagrams = load_process_diagrams()
                did = slugify(body.get("id") or title)
                if any(d.get("id") == did for d in diagrams):
                    did = f"{did}-{secrets.token_hex(2)}"
                sections = body.get("sections")
                if not isinstance(sections, list) or not sections:
                    sections = [
                        {
                            "id": "s1",
                            "title": "Section 1",
                            "tone": "navy",
                            "points": ["Process point 1", "Process point 2"],
                        }
                    ]
                item = {
                    "id": did,
                    "title": title,
                    "subtitle": (body.get("subtitle") or "").strip(),
                    "direction": body.get("direction")
                    if body.get("direction") in ("vertical", "horizontal")
                    else "vertical",
                    "updated_at": now_iso(),
                    "sections": sections,
                }
                diagrams.append(item)
                save_process_diagrams(diagrams)
                self.send_json(201, {"ok": True, "diagram": item, "diagrams": diagrams})
                return

            if path.startswith("/api/content/") and path.endswith("/publish"):
                if not can_approve(user["role"]):
                    self.send_json(403, {"ok": False, "error": "Approver required"})
                    return
                cid = path[len("/api/content/") : -len("/publish")]
                body = self.read_json()
                host = self.headers.get("Host") or f"127.0.0.1:{PORT}"
                scheme = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
                public_base = body.get("public_base") or f"{scheme}://{host}"
                try:
                    result = publish_content_channels(
                        conn,
                        cid,
                        channels=body.get("channels"),
                        public_base=public_base,
                    )
                    self.send_json(200, {"ok": True, **result})
                except PublishError as exc:
                    self.send_json(400, {"ok": False, "error": str(exc)})
                return

            if path.startswith("/api/content/") and path.endswith("/sync-analytics"):
                if not can_edit(user["role"]) and user["role"] not in ("approver", "channel_admin"):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                cid = path[len("/api/content/") : -len("/sync-analytics")]
                try:
                    result = sync_content_analytics(conn, cid)
                    self.send_json(200, {"ok": True, **result})
                except PublishError as exc:
                    self.send_json(400, {"ok": False, "error": str(exc)})
                return

            if path == "/api/jobs/run-scheduled":
                if not can_approve(user["role"]):
                    self.send_json(403, {"ok": False, "error": "Approver required"})
                    return
                host = self.headers.get("Host") or f"127.0.0.1:{PORT}"
                scheme = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
                ran = run_due_scheduled_publishes(public_base=f"{scheme}://{host}")
                self.send_json(200, {"ok": True, "ran": ran})
                return

            if path == "/api/quick-post":
                if user["role"] not in (
                    "admin",
                    "approver",
                    "editor",
                    "channel_admin",
                ):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                body = self.read_json()
                platform = (body.get("platform") or "facebook").strip().lower()
                message = (body.get("message") or "").strip()
                if not message:
                    self.send_json(400, {"ok": False, "error": "message required"})
                    return
                if platform == "whatsapp":
                    self.send_json(
                        400,
                        {
                            "ok": False,
                            "error": "WhatsApp is copy/send only — use Publisher WhatsApp pack",
                        },
                    )
                    return

                account_id = (body.get("account_id") or "").strip()
                token = "".join((body.get("access_token") or "").split())
                link = (body.get("link") or "").strip()
                image_url = (body.get("image_url") or "").strip()
                save_conn = bool(body.get("save_connection"))

                # Prefer pasted credentials; else use saved connection
                if not token or not account_id:
                    saved = get_active_connection(conn, platform)
                    if not saved:
                        self.send_json(
                            400,
                            {
                                "ok": False,
                                "error": "Paste Page ID + token, or save a Connection first",
                            },
                        )
                        return
                    account_id = account_id or saved.get("account_id") or ""
                    token = token or "".join((saved.get("access_token") or "").split())

                connection = {
                    "account_id": account_id,
                    "access_token": token,
                    "auto_publish": 1,
                }

                try:
                    if platform == "facebook":
                        # Resolves user token → Page token before posting/saving
                        from publishers.social import resolve_facebook_page_token

                        page_id, page_token = resolve_facebook_page_token(
                            account_id, token
                        )
                        connection["account_id"] = page_id
                        connection["access_token"] = page_token
                        account_id, token = page_id, page_token
                        result = publish_facebook(connection, message, link=link)
                    else:
                        result = publish_for_channel(
                            platform,
                            connection,
                            message=message,
                            image_url=image_url,
                            link=link,
                        )

                    if save_conn and account_id and token:
                        now = now_iso()
                        existing = conn.execute(
                            """
                            SELECT id FROM platform_connections
                            WHERE platform = ? AND account_id = ?
                            """,
                            (platform, account_id),
                        ).fetchone()
                        if existing:
                            conn.execute(
                                """
                                UPDATE platform_connections
                                SET access_token_enc = ?, token_hint = ?, auto_publish = 1,
                                    active = 1, updated_at = ?,
                                    label = COALESCE(NULLIF(?, ''), label)
                                WHERE id = ?
                                """,
                                (
                                    encrypt_secret(token),
                                    secret_fingerprint(token),
                                    now,
                                    (body.get("label") or "").strip(),
                                    existing["id"],
                                ),
                            )
                        else:
                            conn.execute(
                                """
                                INSERT INTO platform_connections (
                                  id, platform, label, account_id, access_token_enc,
                                  refresh_token_enc, token_hint, auto_publish, active,
                                  meta_json, created_at, updated_at
                                ) VALUES (?,?,?,?,?,'',?,1,1,'{}',?,?)
                                """,
                                (
                                    str(uuid.uuid4()),
                                    platform,
                                    (body.get("label") or f"{platform} quick").strip(),
                                    account_id,
                                    encrypt_secret(token),
                                    secret_fingerprint(token),
                                    now,
                                    now,
                                ),
                            )
                        conn.commit()

                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "platform": platform,
                            "platform_post_id": result.get("platform_post_id"),
                            "live_url": result.get("live_url"),
                            "saved_connection": save_conn,
                            "page_id": account_id if platform == "facebook" else None,
                        },
                    )
                except PublishError as exc:
                    err = str(exc)
                    if "(#200)" in err or "pages_manage_posts" in err:
                        err = (
                            "Facebook rejected the post (#200). This is a Page permission "
                            "error (the 'group' text is generic and can be ignored). "
                            "Regenerate token in Graph API Explorer with "
                            "pages_show_list + pages_manage_posts + pages_read_engagement, "
                            "run me/accounts, then paste Gamata Page ID 800901136940325 "
                            "and either the user token or the Gamata page access_token."
                        )
                    self.send_json(400, {"ok": False, "error": err})
                return

            if path == "/api/tags":
                if not can_edit(user["role"]) and user["role"] not in (
                    "contributor",
                    "channel_admin",
                ):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                body = self.read_json()
                names = parse_hashtag_list(body.get("tags") or body.get("name") or "")
                if not names:
                    self.send_json(400, {"ok": False, "error": "tag name required"})
                    return
                created = []
                for name in names:
                    tid = ensure_custom_tag(conn, name)
                    if tid:
                        created.append(
                            row_to_dict(
                                conn.execute(
                                    "SELECT * FROM tags WHERE id = ?", (tid,)
                                ).fetchone()
                            )
                        )
                conn.commit()
                self.send_json(201, {"ok": True, "items": created})
                return

            if path == "/api/campaigns":
                if not can_manage(user["role"]) and user["role"] not in ("approver", "editor"):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                body = self.read_json()
                name = (body.get("name") or "").strip()
                category_id = body.get("category_id")
                if not name or not category_id:
                    self.send_json(400, {"ok": False, "error": "name and category_id required"})
                    return
                cid = str(uuid.uuid4())
                hashtag = (body.get("hashtag") or "").strip()
                if hashtag and not hashtag.startswith("#"):
                    hashtag = "#" + hashtag
                slug = slugify(name)
                base = slug
                n = 2
                while conn.execute("SELECT 1 FROM campaigns WHERE slug = ?", (slug,)).fetchone():
                    slug = f"{base}-{n}"
                    n += 1
                conn.execute(
                    """
                    INSERT INTO campaigns (
                      id, category_id, name, slug, owner, status, start_date, end_date,
                      hashtag, landing_page, description, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        cid,
                        category_id,
                        name,
                        slug,
                        (body.get("owner") or "").strip(),
                        body.get("status") or "planned",
                        body.get("start_date") or "",
                        body.get("end_date") or "",
                        hashtag,
                        (body.get("landing_page") or "").strip(),
                        (body.get("description") or "").strip(),
                        now_iso(),
                    ),
                )
                if hashtag:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tags (id, name, kind, category_id, campaign_id)
                        VALUES (?,?, 'campaign', ?, ?)
                        """,
                        (str(uuid.uuid4()), hashtag, category_id, cid),
                    )
                conn.commit()
                self.send_json(201, {"ok": True, "id": cid})
                return

            if path == "/api/content":
                body = self.read_json()
                title = (body.get("title") or "").strip()
                category_id = body.get("category_id")
                if not title or not category_id:
                    self.send_json(400, {"ok": False, "error": "title and category_id required"})
                    return
                cid = str(uuid.uuid4())
                campaign_id = body.get("campaign_id") or None
                now = now_iso()
                status = (body.get("status") or "submitted").strip().lower()
                if status not in ("draft", "submitted"):
                    self.send_json(
                        400,
                        {"ok": False, "error": "Create status must be draft or submitted"},
                    )
                    return
                conn.execute(
                    """
                    INSERT INTO content_items (
                      id, title, body, notes, category_id, campaign_id, status,
                      submitter_id, scheduled_at, published_at, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?, ?, ?, '', '', ?, ?)
                    """,
                    (
                        cid,
                        title,
                        body.get("body") or "",
                        body.get("notes") or "",
                        category_id,
                        campaign_id,
                        status,
                        user["id"],
                        now,
                        now,
                    ),
                )
                ensure_channel_rows(conn, cid)
                # optional seed channel bodies from master
                master = body.get("body") or ""
                if master:
                    for ch in CHANNELS:
                        conn.execute(
                            "UPDATE content_channels SET body = ? WHERE content_id = ? AND channel = ?",
                            (master, cid, ch),
                        )
                attach_auto_tags(
                    conn,
                    cid,
                    category_id,
                    campaign_id,
                    body.get("extra_tag_ids"),
                    body.get("extra_tags") or body.get("hashtags"),
                )
                for mid in body.get("media_ids") or []:
                    conn.execute(
                        "INSERT OR IGNORE INTO content_media (content_id, media_id) VALUES (?, ?)",
                        (cid, mid),
                    )
                conn.commit()
                self.send_json(201, {"ok": True, "id": cid, "item": content_with_relations(conn, cid)})
                return

            if path == "/api/media":
                self.handle_media_upload(conn, user)
                return

            if path == "/api/engagement":
                if user["role"] not in ("admin", "channel_admin", "approver", "editor"):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                body = self.read_json()
                platform = (body.get("platform") or "").strip().lower()
                if platform not in CHANNELS and platform != "other":
                    self.send_json(400, {"ok": False, "error": "Invalid platform"})
                    return
                eid = str(uuid.uuid4())
                now = now_iso()
                conn.execute(
                    """
                    INSERT INTO engagement_logs (
                      id, content_id, platform, note, link, status,
                      assigned_to, escalated_to, created_by, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        eid,
                        body.get("content_id") or None,
                        platform,
                        body.get("note") or "",
                        body.get("link") or "",
                        body.get("status") or "open",
                        body.get("assigned_to") or user["id"],
                        body.get("escalated_to") or "",
                        user["id"],
                        now,
                        now,
                    ),
                )
                conn.commit()
                self.send_json(201, {"ok": True, "id": eid})
                return

            self.send_json(404, {"ok": False, "error": "Unknown API route"})

    def handle_api_put(self, path: str) -> None:
        with connect() as conn:
            user = self.require_user(conn)
            if not user:
                return

            if path.startswith("/api/content/") and path.endswith("/status"):
                cid = path[len("/api/content/") : -len("/status")]
                body = self.read_json()
                status = body.get("status")
                if status not in CONTENT_STATUSES:
                    self.send_json(400, {"ok": False, "error": "Invalid status"})
                    return
                item = conn.execute(
                    "SELECT * FROM content_items WHERE id = ?", (cid,)
                ).fetchone()
                if not item:
                    self.send_json(404, {"ok": False, "error": "Not found"})
                    return
                if status in ("approved", "scheduled", "published", "rejected") and not can_approve(
                    user["role"]
                ):
                    self.send_json(403, {"ok": False, "error": "Approver required"})
                    return
                if status == "in_review" and not can_edit(user["role"]):
                    self.send_json(403, {"ok": False, "error": "Editor required"})
                    return
                if status in ("draft", "submitted") and not (
                    can_edit(user["role"])
                    or can_approve(user["role"])
                    or (
                        user["role"] == "contributor"
                        and item["submitter_id"] == user["id"]
                        and item["status"] in ("draft", "submitted", "changes_requested")
                    )
                ):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return

                fields = ["status = ?", "updated_at = ?"]
                args: list = [status, now_iso()]
                if status == "in_review":
                    fields.append("editor_id = ?")
                    args.append(user["id"])
                if status in ("approved", "scheduled", "published", "rejected"):
                    fields.append("approver_id = ?")
                    args.append(user["id"])
                if status == "scheduled":
                    fields.append("scheduled_at = ?")
                    args.append(body.get("scheduled_at") or item["scheduled_at"] or now_iso())
                if status == "published":
                    fields.append("published_at = ?")
                    args.append(body.get("published_at") or now_iso())
                    if body.get("scheduled_at"):
                        fields.append("scheduled_at = ?")
                        args.append(body["scheduled_at"])
                args.append(cid)
                conn.execute(
                    f"UPDATE content_items SET {', '.join(fields)} WHERE id = ?",
                    args,
                )
                conn.commit()
                self.send_json(200, {"ok": True, "item": content_with_relations(conn, cid)})
                return

            if path.startswith("/api/content/"):
                cid = path.split("/api/content/", 1)[1]
                if "/" in cid:
                    self.send_json(404, {"ok": False, "error": "Unknown API route"})
                    return
                item = conn.execute(
                    "SELECT * FROM content_items WHERE id = ?", (cid,)
                ).fetchone()
                if not item:
                    self.send_json(404, {"ok": False, "error": "Not found"})
                    return
                body = self.read_json()
                # contributors can only edit own submitted/changes_requested
                if user["role"] == "contributor":
                    if item["submitter_id"] != user["id"] or item["status"] not in (
                        "submitted",
                        "changes_requested",
                    ):
                        self.send_json(403, {"ok": False, "error": "Forbidden"})
                        return
                elif not can_edit(user["role"]):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return

                category_id = body.get("category_id") or item["category_id"]
                campaign_id = body.get("campaign_id")
                if campaign_id == "":
                    campaign_id = None
                elif campaign_id is None:
                    campaign_id = item["campaign_id"]

                conn.execute(
                    """
                    UPDATE content_items SET
                      title = ?, body = ?, notes = ?, category_id = ?, campaign_id = ?,
                      scheduled_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        (body.get("title") or item["title"]).strip(),
                        body.get("body") if "body" in body else item["body"],
                        body.get("notes") if "notes" in body else item["notes"],
                        category_id,
                        campaign_id,
                        body.get("scheduled_at")
                        if "scheduled_at" in body
                        else item["scheduled_at"],
                        now_iso(),
                        cid,
                    ),
                )
                ensure_channel_rows(conn, cid)
                if "channels" in body and isinstance(body["channels"], list):
                    for ch in body["channels"]:
                        channel = ch.get("channel")
                        if channel not in CHANNELS:
                            continue
                        meta_json = ch.get("meta_json")
                        if meta_json is not None and not isinstance(meta_json, str):
                            meta_json = json_dumps(meta_json)
                        conn.execute(
                            """
                            UPDATE content_channels
                            SET body = COALESCE(?, body),
                                status = COALESCE(?, status),
                                live_url = COALESCE(?, live_url),
                                reach = COALESCE(?, reach),
                                likes = COALESCE(?, likes),
                                comments = COALESCE(?, comments),
                                shares = COALESCE(?, shares),
                                wa_target = COALESCE(?, wa_target),
                                meta_json = COALESCE(?, meta_json)
                            WHERE content_id = ? AND channel = ?
                            """,
                            (
                                ch.get("body"),
                                ch.get("status"),
                                ch.get("live_url"),
                                ch.get("reach"),
                                ch.get("likes"),
                                ch.get("comments"),
                                ch.get("shares"),
                                ch.get("wa_target"),
                                meta_json,
                                cid,
                                channel,
                            ),
                        )
                if "extra_tags" in body or "hashtags" in body:
                    extra_tags = body.get("extra_tags") or body.get("hashtags")
                else:
                    extra_tags = [
                        r["name"]
                        for r in conn.execute(
                            """
                            SELECT t.name FROM tags t
                            JOIN content_tags ct ON ct.tag_id = t.id
                            WHERE ct.content_id = ? AND t.kind = 'custom'
                            """,
                            (cid,),
                        )
                    ]
                attach_auto_tags(
                    conn,
                    cid,
                    category_id,
                    campaign_id,
                    body.get("extra_tag_ids"),
                    extra_tags,
                )
                if "media_ids" in body:
                    conn.execute("DELETE FROM content_media WHERE content_id = ?", (cid,))
                    for mid in body.get("media_ids") or []:
                        conn.execute(
                            "INSERT OR IGNORE INTO content_media (content_id, media_id) VALUES (?, ?)",
                            (cid, mid),
                        )
                conn.commit()
                self.send_json(200, {"ok": True, "item": content_with_relations(conn, cid)})
                return

            if path.startswith("/api/engagement/"):
                eid = path.split("/api/engagement/", 1)[1]
                body = self.read_json()
                row = conn.execute(
                    "SELECT * FROM engagement_logs WHERE id = ?", (eid,)
                ).fetchone()
                if not row:
                    self.send_json(404, {"ok": False, "error": "Not found"})
                    return
                status = body.get("status") or row["status"]
                if status not in ("open", "replied", "escalate"):
                    self.send_json(400, {"ok": False, "error": "Invalid status"})
                    return
                conn.execute(
                    """
                    UPDATE engagement_logs
                    SET status = ?, note = ?, link = ?, escalated_to = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        body.get("note") if "note" in body else row["note"],
                        body.get("link") if "link" in body else row["link"],
                        body.get("escalated_to")
                        if "escalated_to" in body
                        else row["escalated_to"],
                        now_iso(),
                        eid,
                    ),
                )
                conn.commit()
                self.send_json(200, {"ok": True})
                return

            if path.startswith("/api/campaigns/"):
                if not can_manage(user["role"]) and user["role"] not in ("approver", "editor"):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                cid = path.split("/api/campaigns/", 1)[1]
                body = self.read_json()
                row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (cid,)).fetchone()
                if not row:
                    self.send_json(404, {"ok": False, "error": "Not found"})
                    return
                status = body.get("status") or row["status"]
                if status not in CAMPAIGN_STATUSES:
                    self.send_json(400, {"ok": False, "error": "Invalid status"})
                    return
                hashtag = body.get("hashtag") if "hashtag" in body else row["hashtag"]
                if hashtag and not str(hashtag).startswith("#"):
                    hashtag = "#" + hashtag
                conn.execute(
                    """
                    UPDATE campaigns SET
                      name = ?, owner = ?, status = ?, start_date = ?, end_date = ?,
                      hashtag = ?, landing_page = ?, description = ?
                    WHERE id = ?
                    """,
                    (
                        (body.get("name") or row["name"]).strip(),
                        body.get("owner") if "owner" in body else row["owner"],
                        status,
                        body.get("start_date") if "start_date" in body else row["start_date"],
                        body.get("end_date") if "end_date" in body else row["end_date"],
                        hashtag or "",
                        body.get("landing_page")
                        if "landing_page" in body
                        else row["landing_page"],
                        body.get("description")
                        if "description" in body
                        else row["description"],
                        cid,
                    ),
                )
                if hashtag:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tags (id, name, kind, category_id, campaign_id)
                        VALUES (?,?, 'campaign', ?, ?)
                        """,
                        (str(uuid.uuid4()), hashtag, row["category_id"], cid),
                    )
                conn.commit()
                self.send_json(200, {"ok": True})
                return

            if path.startswith("/api/connections/"):
                if not can_manage(user["role"]) and user["role"] not in ("approver", "editor"):
                    self.send_json(403, {"ok": False, "error": "Forbidden"})
                    return
                cid = path.split("/api/connections/", 1)[1]
                body = self.read_json()
                row = conn.execute(
                    "SELECT * FROM platform_connections WHERE id = ?", (cid,)
                ).fetchone()
                if not row:
                    self.send_json(404, {"ok": False, "error": "Not found"})
                    return
                token = body.get("access_token")
                fields = [
                    "label = ?",
                    "account_id = ?",
                    "auto_publish = ?",
                    "active = ?",
                    "updated_at = ?",
                ]
                args: list = [
                    (body.get("label") if "label" in body else row["label"]),
                    (body.get("account_id") if "account_id" in body else row["account_id"]),
                    1
                    if body.get("auto_publish", row["auto_publish"])
                    else 0,
                    1 if body.get("active", row["active"]) else 0,
                    now_iso(),
                ]
                if token:
                    fields.append("access_token_enc = ?")
                    args.append(encrypt_secret(token.strip()))
                    fields.append("token_hint = ?")
                    args.append(secret_fingerprint(token.strip()))
                if "refresh_token" in body:
                    fields.append("refresh_token_enc = ?")
                    args.append(encrypt_secret((body.get("refresh_token") or "").strip()))
                args.append(cid)
                conn.execute(
                    f"UPDATE platform_connections SET {', '.join(fields)} WHERE id = ?",
                    args,
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM platform_connections WHERE id = ?", (cid,)
                ).fetchone()
                self.send_json(200, {"ok": True, "item": connection_public(row)})
                return

            if path.startswith("/api/diagrams/"):
                if user["role"] not in ("admin", "editor", "approver"):
                    self.send_json(403, {"ok": False, "error": "Editor/admin required"})
                    return
                did = path.split("/api/diagrams/", 1)[1]
                body = self.read_json()
                diagrams = load_process_diagrams()
                idx = next((i for i, d in enumerate(diagrams) if d.get("id") == did), -1)
                if idx < 0:
                    self.send_json(404, {"ok": False, "error": "Diagram not found"})
                    return
                current = diagrams[idx]
                sections = (
                    body.get("sections")
                    if isinstance(body.get("sections"), list)
                    else current.get("sections")
                )
                title = (body.get("title") if "title" in body else current.get("title") or "").strip()
                subtitle = (
                    body.get("subtitle") if "subtitle" in body else current.get("subtitle") or ""
                )
                if isinstance(subtitle, str):
                    subtitle = subtitle.strip()
                else:
                    subtitle = ""
                direction = body.get("direction") or current.get("direction") or "vertical"
                if direction not in ("vertical", "horizontal"):
                    direction = "vertical"
                if not title:
                    self.send_json(400, {"ok": False, "error": "title required"})
                    return
                updated = {
                    "id": did,
                    "title": title,
                    "subtitle": subtitle,
                    "direction": direction,
                    "updated_at": now_iso(),
                    "sections": sections or [],
                }
                diagrams[idx] = updated
                save_process_diagrams(diagrams)
                self.send_json(200, {"ok": True, "diagram": updated, "diagrams": diagrams})
                return

            self.send_json(404, {"ok": False, "error": "Unknown API route"})

    def handle_media_upload(self, conn: sqlite3.Connection, user: dict) -> None:
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in ctype:
            # JSON metadata-only fallback not supported for binary; accept JSON with no file for demo captions? No.
            self.send_json(400, {"ok": False, "error": "multipart/form-data required"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        boundary_match = re.search(r"boundary=(.+)", ctype)
        if not boundary_match:
            self.send_json(400, {"ok": False, "error": "Missing boundary"})
            return
        boundary = boundary_match.group(1).strip()
        if boundary.startswith('"') and boundary.endswith('"'):
            boundary = boundary[1:-1]
        parts = body.split(f"--{boundary}".encode())
        fields: dict[str, str] = {}
        file_bytes: bytes | None = None
        filename = "upload.bin"
        file_mime = "application/octet-stream"

        for part in parts:
            if b"Content-Disposition" not in part:
                continue
            header_blob, _, content = part.partition(b"\r\n\r\n")
            if content.endswith(b"\r\n"):
                content = content[:-2]
            if content.endswith(b"--"):
                content = content[:-2]
            headers = header_blob.decode("utf-8", errors="ignore")
            name_m = re.search(r'name="([^"]+)"', headers)
            if not name_m:
                continue
            name = name_m.group(1)
            file_m = re.search(r'filename="([^"]*)"', headers)
            if file_m:
                filename = Path(file_m.group(1) or "upload.bin").name
                mime_m = re.search(r"Content-Type:\s*(.+)", headers, re.I)
                file_mime = (mime_m.group(1).strip() if mime_m else "") or (
                    mimetypes.guess_type(filename)[0] or "application/octet-stream"
                )
                file_bytes = content
            else:
                fields[name] = content.decode("utf-8", errors="ignore").strip()

        if not file_bytes:
            self.send_json(400, {"ok": False, "error": "file required"})
            return

        mid = str(uuid.uuid4())
        ext = Path(filename).suffix[:12]
        stored = f"{mid}{ext}"
        dest = UPLOAD_DIR / stored
        dest.write_bytes(file_bytes)
        conn.execute(
            """
            INSERT INTO media_assets (
              id, filename, original_name, mime, path, category_id, campaign_id,
              caption, uploaded_by, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                mid,
                stored,
                filename,
                file_mime,
                f"/uploads/{stored}",
                fields.get("category_id") or None,
                fields.get("campaign_id") or None,
                fields.get("caption") or "",
                user["id"],
                now_iso(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM media_assets WHERE id = ?", (mid,)).fetchone()
        self.send_json(201, {"ok": True, "item": row_to_dict(row)})

    def list_content(self, conn: sqlite3.Connection, qs: dict) -> list[dict]:
        status = (qs.get("status") or [""])[0]
        category_id = (qs.get("category_id") or [""])[0]
        campaign_id = (qs.get("campaign_id") or [""])[0]
        tag = (qs.get("tag") or [""])[0]
        sql = """
            SELECT DISTINCT c.*, cat.name AS category_name, camp.name AS campaign_name,
                   su.name AS submitter_name
            FROM content_items c
            JOIN categories cat ON cat.id = c.category_id
            LEFT JOIN campaigns camp ON camp.id = c.campaign_id
            LEFT JOIN users su ON su.id = c.submitter_id
            LEFT JOIN content_tags ct ON ct.content_id = c.id
            LEFT JOIN tags t ON t.id = ct.tag_id
            WHERE 1=1
        """
        args: list = []
        if status:
            sql += " AND c.status = ?"
            args.append(status)
        if category_id:
            sql += " AND c.category_id = ?"
            args.append(category_id)
        if campaign_id:
            sql += " AND c.campaign_id = ?"
            args.append(campaign_id)
        if tag:
            sql += " AND lower(t.name) = lower(?)"
            args.append(normalize_hashtag(tag) or tag)
        sql += " ORDER BY c.updated_at DESC"
        return rows_to_list(conn.execute(sql, args))

    def calendar_items(self, conn: sqlite3.Connection, qs: dict) -> list[dict]:
        category_id = (qs.get("category_id") or [""])[0]
        campaign_id = (qs.get("campaign_id") or [""])[0]
        sql = """
            SELECT c.id, c.title, c.status, c.scheduled_at, c.published_at,
                   c.category_id, c.campaign_id,
                   cat.name AS category_name, camp.name AS campaign_name
            FROM content_items c
            JOIN categories cat ON cat.id = c.category_id
            LEFT JOIN campaigns camp ON camp.id = c.campaign_id
            WHERE c.status IN ('approved', 'scheduled', 'published')
              AND (c.scheduled_at != '' OR c.published_at != '')
        """
        args: list = []
        if category_id:
            sql += " AND c.category_id = ?"
            args.append(category_id)
        if campaign_id:
            sql += " AND c.campaign_id = ?"
            args.append(campaign_id)
        sql += " ORDER BY COALESCE(NULLIF(c.scheduled_at,''), c.published_at)"
        return rows_to_list(conn.execute(sql, args))

    def list_media(self, conn: sqlite3.Connection, qs: dict) -> list[dict]:
        category_id = (qs.get("category_id") or [""])[0]
        campaign_id = (qs.get("campaign_id") or [""])[0]
        sql = """
            SELECT m.*, cat.name AS category_name, camp.name AS campaign_name
            FROM media_assets m
            LEFT JOIN categories cat ON cat.id = m.category_id
            LEFT JOIN campaigns camp ON camp.id = m.campaign_id
            WHERE 1=1
        """
        args: list = []
        if category_id:
            sql += " AND m.category_id = ?"
            args.append(category_id)
        if campaign_id:
            sql += " AND m.campaign_id = ?"
            args.append(campaign_id)
        sql += " ORDER BY m.created_at DESC"
        return rows_to_list(conn.execute(sql, args))

    def list_engagement(self, conn: sqlite3.Connection, qs: dict) -> list[dict]:
        status = (qs.get("status") or [""])[0]
        sql = """
            SELECT e.*, u.name AS created_by_name, c.title AS content_title
            FROM engagement_logs e
            LEFT JOIN users u ON u.id = e.created_by
            LEFT JOIN content_items c ON c.id = e.content_id
            WHERE 1=1
        """
        args: list = []
        if status:
            sql += " AND e.status = ?"
            args.append(status)
        sql += " ORDER BY e.updated_at DESC"
        return rows_to_list(conn.execute(sql, args))

    def dashboard(self, conn: sqlite3.Connection, user: dict) -> dict:
        by_status = {
            r["status"]: r["c"]
            for r in conn.execute(
                "SELECT status, COUNT(*) c FROM content_items GROUP BY status"
            )
        }
        campaigns = rows_to_list(
            conn.execute(
                """
                SELECT camp.id, camp.name, camp.status, cat.name AS category_name
                FROM campaigns camp
                JOIN categories cat ON cat.id = camp.category_id
                WHERE camp.status IN ('active', 'ongoing', 'planned')
                ORDER BY camp.status, camp.name
                LIMIT 12
                """
            )
        )
        queue = rows_to_list(
            conn.execute(
                """
                SELECT c.id, c.title, c.status, c.updated_at, cat.name AS category_name,
                       camp.name AS campaign_name
                FROM content_items c
                JOIN categories cat ON cat.id = c.category_id
                LEFT JOIN campaigns camp ON camp.id = c.campaign_id
                WHERE c.status IN ('submitted', 'in_review', 'changes_requested', 'approved')
                ORDER BY c.updated_at DESC
                LIMIT 10
                """
            )
        )
        mine = rows_to_list(
            conn.execute(
                """
                SELECT id, title, status, updated_at FROM content_items
                WHERE submitter_id = ?
                ORDER BY updated_at DESC LIMIT 8
                """,
                (user["id"],),
            )
        )
        escalations = conn.execute(
            "SELECT COUNT(*) c FROM engagement_logs WHERE status = 'escalate'"
        ).fetchone()["c"]
        return {
            "by_status": by_status,
            "campaigns": campaigns,
            "queue": queue,
            "mine": mine,
            "escalations": escalations,
            "user": {"id": user["id"], "name": user["name"], "role": user["role"]},
        }

    def analytics(self, conn: sqlite3.Connection) -> dict:
        ops = {
            r["status"]: r["c"]
            for r in conn.execute(
                "SELECT status, COUNT(*) c FROM content_items GROUP BY status"
            )
        }
        by_category = rows_to_list(
            conn.execute(
                """
                SELECT cat.name,
                       COUNT(DISTINCT c.id) AS content_count,
                       COALESCE((
                         SELECT SUM(ch.reach) FROM content_channels ch
                         JOIN content_items c2 ON c2.id = ch.content_id
                         WHERE c2.category_id = cat.id
                       ),0) AS reach,
                       COALESCE((
                         SELECT SUM(ch.likes) FROM content_channels ch
                         JOIN content_items c2 ON c2.id = ch.content_id
                         WHERE c2.category_id = cat.id
                       ),0) AS likes,
                       COALESCE((
                         SELECT SUM(ch.comments) FROM content_channels ch
                         JOIN content_items c2 ON c2.id = ch.content_id
                         WHERE c2.category_id = cat.id
                       ),0) AS comments,
                       COALESCE((
                         SELECT SUM(ch.shares) FROM content_channels ch
                         JOIN content_items c2 ON c2.id = ch.content_id
                         WHERE c2.category_id = cat.id
                       ),0) AS shares
                FROM categories cat
                JOIN content_items c ON c.category_id = cat.id
                GROUP BY cat.id
                ORDER BY content_count DESC
                """
            )
        )
        by_campaign = rows_to_list(
            conn.execute(
                """
                SELECT camp.name, cat.name AS category_name,
                       COUNT(DISTINCT c.id) AS content_count,
                       COALESCE((
                         SELECT SUM(ch.reach) FROM content_channels ch
                         JOIN content_items c2 ON c2.id = ch.content_id
                         WHERE c2.campaign_id = camp.id
                       ),0) AS reach,
                       COALESCE((
                         SELECT SUM(ch.likes) FROM content_channels ch
                         JOIN content_items c2 ON c2.id = ch.content_id
                         WHERE c2.campaign_id = camp.id
                       ),0) AS likes,
                       COALESCE((
                         SELECT SUM(ch.comments) FROM content_channels ch
                         JOIN content_items c2 ON c2.id = ch.content_id
                         WHERE c2.campaign_id = camp.id
                       ),0) AS comments,
                       COALESCE((
                         SELECT SUM(ch.shares) FROM content_channels ch
                         JOIN content_items c2 ON c2.id = ch.content_id
                         WHERE c2.campaign_id = camp.id
                       ),0) AS shares
                FROM campaigns camp
                JOIN categories cat ON cat.id = camp.category_id
                JOIN content_items c ON c.campaign_id = camp.id
                GROUP BY camp.id
                ORDER BY content_count DESC
                """
            )
        )
        by_platform = rows_to_list(
            conn.execute(
                """
                SELECT channel AS platform,
                       COUNT(*) AS versions,
                       COALESCE(SUM(reach),0) AS reach,
                       COALESCE(SUM(likes),0) AS likes,
                       COALESCE(SUM(comments),0) AS comments,
                       COALESCE(SUM(shares),0) AS shares
                FROM content_channels
                GROUP BY channel
                ORDER BY reach DESC, platform
                """
            )
        )
        tags = rows_to_list(
            conn.execute(
                """
                SELECT
                  t.id,
                  t.name,
                  t.kind,
                  COUNT(DISTINCT ct.content_id) AS uses,
                  COUNT(DISTINCT CASE WHEN c.status = 'published' THEN c.id END) AS published_count,
                  COALESCE(SUM(ch.reach), 0) AS reach,
                  COALESCE(SUM(ch.likes), 0) AS likes,
                  COALESCE(SUM(ch.comments), 0) AS comments,
                  COALESCE(SUM(ch.shares), 0) AS shares,
                  COALESCE(SUM(ch.likes + ch.comments + ch.shares), 0) AS engagement
                FROM tags t
                LEFT JOIN content_tags ct ON ct.tag_id = t.id
                LEFT JOIN content_items c ON c.id = ct.content_id
                LEFT JOIN content_channels ch ON ch.content_id = c.id
                GROUP BY t.id
                ORDER BY engagement DESC, reach DESC, uses DESC, t.name
                """
            )
        )
        top_tags = [t for t in tags if (t.get("uses") or 0) > 0][:8]
        return {
            "ops": ops,
            "by_category": by_category,
            "by_campaign": by_campaign,
            "by_platform": by_platform,
            "tags": tags,
            "top_tags": top_tags,
        }


def main() -> None:
    init_db()

    def scheduler_loop() -> None:
        while True:
            try:
                run_due_scheduled_publishes(public_base=f"http://127.0.0.1:{PORT}")
            except Exception as exc:  # noqa: BLE001
                print(f"[hub] scheduler error: {exc}")
            time.sleep(60)

    threading.Thread(target=scheduler_loop, name="hub-scheduler", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), HubHandler)
    print(f"BCOBA Digital Hub → http://localhost:{PORT}")
    print(f"SQLite: {DB_PATH}")
    print("Demo login: admin@bcoba.lk / admin123")
    print("Auto-publish scheduler: every 60s for due scheduled posts")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
