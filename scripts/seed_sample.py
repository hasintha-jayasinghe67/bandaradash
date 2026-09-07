#!/usr/bin/env python3
"""Seed demo content, hashtags, metrics for Hub analytics."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import (  # noqa: E402
    CHANNELS,
    attach_auto_tags,
    connect,
    init_db,
    now_iso,
)


SAMPLES = [
    {
        "id": "demo-main-hall-1",
        "title": "Main Hall progress — structural works underway",
        "body": "Foundation and structural strengthening continue this week. Alumni support is Restoring the Pride.",
        "category_id": "cat-projects",
        "campaign_id": "camp-main-hall",
        "status": "published",
        "extra_tags": ["#Guardians", "#SiteUpdate"],
        "scheduled_at": "2026-08-04T10:00:00Z",
        "published_at": "2026-08-04T10:05:00Z",
        "metrics": {
            "facebook": (8200, 410, 48, 62),
            "instagram": (6100, 520, 35, 90),
            "linkedin": (2400, 120, 18, 22),
            "whatsapp": (1800, 90, 40, 120),
            "youtube": (900, 40, 6, 8),
        },
    },
    {
        "id": "demo-alumni-1",
        "title": "Alumni story — engineer gives back",
        "body": "Old Boy from the 1998 batch shares how Bandaranayake shaped his career and why he supports the Hall.",
        "category_id": "cat-alumni",
        "campaign_id": None,
        "status": "published",
        "extra_tags": ["#AlumniStory", "#ProudLion"],
        "scheduled_at": "2026-08-05T11:00:00Z",
        "published_at": "2026-08-05T11:10:00Z",
        "metrics": {
            "facebook": (12400, 780, 96, 140),
            "instagram": (9800, 910, 70, 210),
            "linkedin": (4300, 260, 40, 55),
            "whatsapp": (2600, 120, 55, 180),
            "youtube": (0, 0, 0, 0),
        },
    },
    {
        "id": "demo-sports-1",
        "title": "Cricket win — Under 17 victory",
        "body": "A hard-fought win for the college side. Congratulations to players, coaches and supporters.",
        "category_id": "cat-sports",
        "campaign_id": None,
        "status": "published",
        "extra_tags": ["#BigMatch", "#SchoolSports"],
        "scheduled_at": "2026-08-06T16:30:00Z",
        "published_at": "2026-08-06T16:40:00Z",
        "metrics": {
            "facebook": (15200, 980, 130, 220),
            "instagram": (14100, 1200, 95, 310),
            "linkedin": (900, 45, 8, 10),
            "whatsapp": (4200, 200, 90, 260),
            "youtube": (2100, 120, 18, 25),
        },
    },
    {
        "id": "demo-membership-1",
        "title": "Membership Drive 2026 — renew this month",
        "body": "Stay connected with BCOBA. Renew membership and help power alumni programmes.",
        "category_id": "cat-membership",
        "campaign_id": None,  # filled if campaign exists
        "campaign_name": "Membership Drive 2026",
        "status": "scheduled",
        "extra_tags": ["#JoinBCOBA", "#MembershipDrive2026"],
        "scheduled_at": "2026-08-12T09:00:00Z",
        "published_at": "",
        "metrics": {
            "facebook": (0, 0, 0, 0),
            "instagram": (0, 0, 0, 0),
            "linkedin": (0, 0, 0, 0),
            "whatsapp": (0, 0, 0, 0),
            "youtube": (0, 0, 0, 0),
        },
    },
    {
        "id": "demo-history-1",
        "title": "From the archives — Hall photograph, 1960s",
        "body": "A reminder of why we restore: heritage, assembly, and shared memory.",
        "category_id": "cat-history",
        "campaign_id": "camp-main-hall",
        "status": "published",
        "extra_tags": ["#Throwback", "#Heritage"],
        "scheduled_at": "2026-08-07T08:00:00Z",
        "published_at": "2026-08-07T08:05:00Z",
        "metrics": {
            "facebook": (7600, 540, 70, 95),
            "instagram": (8800, 720, 60, 150),
            "linkedin": (1100, 70, 12, 15),
            "whatsapp": (1900, 80, 35, 110),
            "youtube": (0, 0, 0, 0),
        },
    },
    {
        "id": "demo-events-1",
        "title": "AGM notice — save the date",
        "body": "Official notice: Annual General Meeting details will follow. Members are requested to attend.",
        "category_id": "cat-official",
        "campaign_id": None,
        "status": "in_review",
        "extra_tags": ["#AGM2026"],
        "scheduled_at": "",
        "published_at": "",
        "metrics": {
            "facebook": (0, 0, 0, 0),
            "instagram": (0, 0, 0, 0),
            "linkedin": (0, 0, 0, 0),
            "whatsapp": (0, 0, 0, 0),
            "youtube": (0, 0, 0, 0),
        },
    },
]


def ensure_membership_campaign(conn) -> str | None:
    row = conn.execute(
        "SELECT id FROM campaigns WHERE slug = 'membership-drive-2026'"
    ).fetchone()
    if row:
        return row["id"]
    # created earlier via API maybe under random id
    row = conn.execute(
        "SELECT id FROM campaigns WHERE name = 'Membership Drive 2026'"
    ).fetchone()
    if row:
        return row["id"]
    return None


def seed(force: bool = False) -> dict:
    init_db()
    now = now_iso()
    created = 0
    updated = 0
    with connect() as conn:
        mem_id = ensure_membership_campaign(conn)
        for sample in SAMPLES:
            campaign_id = sample.get("campaign_id")
            if sample.get("campaign_name") and mem_id:
                campaign_id = mem_id
            exists = conn.execute(
                "SELECT id FROM content_items WHERE id = ?", (sample["id"],)
            ).fetchone()
            if exists and not force:
                continue
            if exists and force:
                conn.execute("DELETE FROM content_items WHERE id = ?", (sample["id"],))
                updated += 1
            else:
                created += 1
            conn.execute(
                """
                INSERT INTO content_items (
                  id, title, body, notes, category_id, campaign_id, status,
                  submitter_id, editor_id, approver_id, scheduled_at, published_at,
                  created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sample["id"],
                    sample["title"],
                    sample["body"],
                    "Demo seed content for analytics",
                    sample["category_id"],
                    campaign_id,
                    sample["status"],
                    "u-contrib",
                    "u-editor",
                    "u-approver",
                    sample.get("scheduled_at") or "",
                    sample.get("published_at") or "",
                    now,
                    now,
                ),
            )
            for ch in CHANNELS:
                reach, likes, comments, shares = sample["metrics"].get(
                    ch, (0, 0, 0, 0)
                )
                body = sample["body"]
                status = "published" if sample["status"] == "published" else "ready"
                conn.execute(
                    """
                    INSERT INTO content_channels (
                      id, content_id, channel, body, status, live_url,
                      reach, likes, comments, shares, wa_target, meta_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(uuid.uuid4()),
                        sample["id"],
                        ch,
                        body,
                        status,
                        "",
                        reach,
                        likes,
                        comments,
                        shares,
                        "community" if ch == "whatsapp" else "",
                        "",
                    ),
                )
            attach_auto_tags(
                conn,
                sample["id"],
                sample["category_id"],
                campaign_id,
                extra_tags=sample.get("extra_tags"),
            )

            # engagement samples
            if sample["status"] == "published":
                conn.execute(
                    """
                    INSERT OR IGNORE INTO engagement_logs (
                      id, content_id, platform, note, link, status,
                      assigned_to, escalated_to, created_by, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"eng-{sample['id']}",
                        sample["id"],
                        "facebook",
                        "Routine praise from alumni — replied with thanks.",
                        "",
                        "replied",
                        "u-channel",
                        "",
                        "u-channel",
                        now,
                        now,
                    ),
                )
        conn.commit()
        counts = {
            "content": conn.execute("SELECT COUNT(*) c FROM content_items").fetchone()[
                "c"
            ],
            "tags": conn.execute("SELECT COUNT(*) c FROM tags").fetchone()["c"],
            "campaigns": conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()[
                "c"
            ],
        }
    return {"created": created, "updated": updated, "counts": counts}


if __name__ == "__main__":
    force = "--force" in sys.argv
    result = seed(force=force)
    print(result)
