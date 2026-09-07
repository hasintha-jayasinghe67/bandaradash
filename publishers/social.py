#!/usr/bin/env python3
"""Social publish + analytics adapters (Metricool-style when credentials saved)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class PublishError(Exception):
    pass


def _request(
    url: str,
    *,
    method: str = "GET",
    data: dict | None = None,
    headers: dict | None = None,
    form: bool = True,
) -> dict:
    hdrs = {"User-Agent": "BCOBA-Digital-Hub/1.0", **(headers or {})}
    body = None
    if data is not None:
        if method.upper() == "GET":
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urllib.parse.urlencode(data)}"
        elif form:
            body = urllib.parse.urlencode(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = json.dumps(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(err_body)
            msg = parsed.get("error", {}).get("message") or parsed.get("message") or err_body
        except json.JSONDecodeError:
            msg = err_body or str(exc)
        raise PublishError(msg) from exc
    except urllib.error.URLError as exc:
        raise PublishError(str(exc.reason or exc)) from exc


GRAPH_VERSION = "v26.0"


def resolve_facebook_page_token(page_id: str, token: str) -> tuple[str, str]:
    """Return (page_id, page_access_token).

    Accepts either a Page token or a User token. If a User token is pasted,
    fetch the matching Page token from /me/accounts (this avoids FB error #200).
    """
    page_id = (page_id or "").strip()
    token = "".join((token or "").split())
    if not page_id or not token:
        raise PublishError("Facebook connection needs Page ID and access token")

    # If this is a user token, me/accounts returns Pages + Page tokens.
    # If this is already a Page token, me/accounts usually fails — then use token as-is.
    try:
        accounts = _request(
            f"https://graph.facebook.com/{GRAPH_VERSION}/me/accounts",
            method="GET",
            data={
                "access_token": token,
                "fields": "id,name,access_token,tasks",
                "limit": "100",
            },
        )
    except PublishError:
        return page_id, token

    pages = accounts.get("data") or []
    if not pages:
        return page_id, token

    match = next((p for p in pages if str(p.get("id")) == page_id), None)
    if not match and len(pages) == 1:
        match = pages[0]
        page_id = str(match.get("id") or page_id)
    if not match:
        names = ", ".join(f"{p.get('name')} ({p.get('id')})" for p in pages[:8])
        raise PublishError(
            f"Page ID {page_id} not in me/accounts. Available: {names or 'none'}"
        )
    page_token = "".join((match.get("access_token") or "").split())
    if not page_token:
        raise PublishError(
            "me/accounts returned the Page but no Page access_token. "
            "Regenerate the user token with pages_show_list, pages_manage_posts, "
            "pages_read_engagement."
        )
    return page_id, page_token


def publish_facebook(conn: dict, message: str, link: str = "") -> dict[str, Any]:
    page_id, token = resolve_facebook_page_token(
        conn.get("account_id") or "", conn.get("access_token") or ""
    )
    # Keep resolved page token on conn so callers can persist it.
    conn["account_id"] = page_id
    conn["access_token"] = token
    payload = {"message": message, "access_token": token}
    if link:
        payload["link"] = link
    data = _request(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/feed",
        method="POST",
        data=payload,
    )
    post_id = data.get("id") or ""
    return {
        "platform_post_id": post_id,
        "live_url": f"https://www.facebook.com/{post_id}" if post_id else "",
        "raw": data,
        "page_id": page_id,
    }


def publish_instagram(conn: dict, caption: str, image_url: str) -> dict[str, Any]:
    """Requires IG Business account linked to Page + publicly reachable image URL."""
    ig_user_id = (conn.get("account_id") or "").strip()
    token = (conn.get("access_token") or "").strip()
    if not ig_user_id or not token:
        raise PublishError("Instagram connection needs IG User ID and access token")
    if not image_url:
        raise PublishError("Instagram auto-post needs a public image URL (upload to Media first)")
    creation = _request(
        f"https://graph.facebook.com/v21.0/{ig_user_id}/media",
        method="POST",
        data={"image_url": image_url, "caption": caption, "access_token": token},
    )
    creation_id = creation.get("id")
    if not creation_id:
        raise PublishError("Instagram media container was not created")
    published = _request(
        f"https://graph.facebook.com/v21.0/{ig_user_id}/media_publish",
        method="POST",
        data={"creation_id": creation_id, "access_token": token},
    )
    media_id = published.get("id") or ""
    return {
        "platform_post_id": media_id,
        "live_url": f"https://www.instagram.com/p/{media_id}/" if media_id else "",
        "raw": published,
    }


def publish_linkedin(conn: dict, text: str) -> dict[str, Any]:
    token = (conn.get("access_token") or "").strip()
    author = (conn.get("account_id") or "").strip()  # urn:li:person:... or urn:li:organization:...
    if not token or not author:
        raise PublishError("LinkedIn needs access token and author URN (person or organization)")
    if not author.startswith("urn:li:"):
        author = f"urn:li:organization:{author}" if author.isdigit() else f"urn:li:person:{author}"
    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    data = _request(
        "https://api.linkedin.com/v2/ugcPosts",
        method="POST",
        data=payload,
        form=False,
        headers={"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0"},
    )
    post_id = data.get("id") or ""
    return {"platform_post_id": post_id, "live_url": "", "raw": data}


def sync_facebook_metrics(conn: dict, post_id: str) -> dict[str, int]:
    token = (conn.get("access_token") or "").strip()
    if not token or not post_id:
        raise PublishError("Missing Facebook token or post id")
    q = urllib.parse.urlencode(
        {
            "fields": "shares,reactions.summary(true),comments.summary(true)",
            "access_token": token,
        }
    )
    data = _request(f"https://graph.facebook.com/v21.0/{post_id}?{q}")
    reactions = ((data.get("reactions") or {}).get("summary") or {}).get("total_count") or 0
    comments = ((data.get("comments") or {}).get("summary") or {}).get("total_count") or 0
    shares = ((data.get("shares") or {}).get("count") or 0)
    reach = 0
    try:
        iq = urllib.parse.urlencode(
            {
                "metric": "post_impressions_unique",
                "access_token": token,
            }
        )
        insights = _request(f"https://graph.facebook.com/v21.0/{post_id}/insights?{iq}")
        values = (insights.get("data") or [{}])[0].get("values") or [{}]
        reach = int(values[0].get("value") or 0)
    except PublishError:
        reach = reactions + comments + shares
    return {
        "reach": int(reach),
        "likes": int(reactions),
        "comments": int(comments),
        "shares": int(shares),
    }


def sync_instagram_metrics(conn: dict, media_id: str) -> dict[str, int]:
    token = (conn.get("access_token") or "").strip()
    if not token or not media_id:
        raise PublishError("Missing Instagram token or media id")
    q = urllib.parse.urlencode(
        {
            "metric": "impressions,reach,likes,comments,saved,shares",
            "access_token": token,
        }
    )
    try:
        data = _request(f"https://graph.facebook.com/v21.0/{media_id}/insights?{q}")
        metrics = {row.get("name"): (row.get("values") or [{}])[0].get("value", 0) for row in data.get("data") or []}
        return {
            "reach": int(metrics.get("reach") or metrics.get("impressions") or 0),
            "likes": int(metrics.get("likes") or 0),
            "comments": int(metrics.get("comments") or 0),
            "shares": int(metrics.get("shares") or metrics.get("saved") or 0),
        }
    except PublishError:
        q2 = urllib.parse.urlencode(
            {
                "fields": "like_count,comments_count",
                "access_token": token,
            }
        )
        data = _request(f"https://graph.facebook.com/v21.0/{media_id}?{q2}")
        return {
            "reach": 0,
            "likes": int(data.get("like_count") or 0),
            "comments": int(data.get("comments_count") or 0),
            "shares": 0,
        }


def publish_for_channel(
    platform: str,
    conn: dict,
    *,
    message: str,
    image_url: str = "",
    link: str = "",
) -> dict[str, Any]:
    platform = (platform or "").lower()
    if platform == "facebook":
        return publish_facebook(conn, message, link=link)
    if platform == "instagram":
        return publish_instagram(conn, message, image_url)
    if platform == "linkedin":
        return publish_linkedin(conn, message)
    if platform == "whatsapp":
        raise PublishError(
            "WhatsApp has no simple public auto-post API for Community/Broadcast. "
            "Use the WhatsApp pack checklist (copy & send)."
        )
    if platform == "youtube":
        raise PublishError(
            "YouTube auto-upload needs OAuth client + video file upload. "
            "Save credentials now; full upload lands in next cut. Mark published manually for now."
        )
    raise PublishError(f"Unsupported platform: {platform}")


def sync_metrics_for_channel(platform: str, conn: dict, platform_post_id: str) -> dict[str, int]:
    platform = (platform or "").lower()
    if platform == "facebook":
        return sync_facebook_metrics(conn, platform_post_id)
    if platform == "instagram":
        return sync_instagram_metrics(conn, platform_post_id)
    raise PublishError(f"Live analytics sync not yet available for {platform}")
