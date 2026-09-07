# BCOBA Digital Hub — Developer Handoff

Share this folder (or a GitHub repo of it) with the next developer.

## What this project is

Internal **BCOBA Digital & Social Media Management Hub**:
intake → draft/review/approve → multi-channel packs → schedule/publish → engagement → analytics.

Stack: Python `server.py` + SQLite + static HTML/JS (`app.html`, `js/hub.js`, `css/hub.css`).

## Quick start

```bash
cd bcoba-digital-hub
python3 server.py
# or: ./start.sh
```

Open: http://localhost:8787

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@bcoba.lk | admin123 |
| Editor | editor@bcoba.lk | editor123 |
| Approver | approver@bcoba.lk | approve123 |
| Contributor | contributor@bcoba.lk | contrib123 |
| Channel Admin | channel@bcoba.lk | channel123 |

Health: http://localhost:8787/api/health

## Key files

| Path | Purpose |
|------|---------|
| `server.py` | API + SQLite + scheduler |
| `app.html` / `index.html` | App shell / login |
| `js/hub.js` | Frontend |
| `css/hub.css` | Styles |
| `publishers/social.py` | Facebook / IG / LinkedIn publish adapters |
| `hub_crypto.py` | Encrypts saved platform tokens |
| `scripts/seed_sample.py` | Sample analytics data |
| `docs/BCOBA-Digital-Hub-Team-Guide.pdf` | Team overview (share with non-devs too) |
| `data/hub.sqlite` | Local DB (created at runtime; do not commit secrets) |

## What works today

- Content queue: **draft → submitted → review → approve → schedule/publish**
- Facebook Page **Quick post** + saved Connections (encrypted tokens)
- WhatsApp = **manual copy/send pack** (no Community auto-API)
- Templates, process diagrams, brand guide, calendar, engagement, analytics
- Instagram / LinkedIn adapters exist; need real account setup to finish testing
- **Reels + TikTok** = planned (see team guide roadmap)

## Do NOT share / commit

- `data/.hub_key` (encryption key for tokens)
- `data/hub.sqlite` if it contains real Page tokens
- Real Facebook/LinkedIn access tokens
- `.env` if added later
- Unrelated folders (e.g. `VentureTea-FactoryFloor/`) unless intentional

`.gitignore` already excludes sqlite, uploads, `.hub_key`, `.env`.

## Facebook test notes (for the next dev)

1. Meta app (e.g. `BCOBA_TEST`) + Graph API Explorer
2. Permissions: `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`
3. Run `me/accounts` → use Page `id` + Page `access_token` (or user token; Hub resolves Page token)
4. Hub → **Connections** → Quick post
5. Personal FB/IG profiles cannot auto-post; **Pages** only
6. Explorer tokens expire (~1–2 hours); long-lived Page token needed for production

## Suggested next development

1. Reels (FB/IG short video pack + publish)
2. TikTok channel + Content Posting API
3. Instagram Professional link to official Page
4. LinkedIn Company Page posting
5. Long-lived token exchange UI (App ID + App Secret)
6. Deploy beyond localhost (hosting, HTTPS, backups)

## Team docs to send together

1. `docs/BCOBA-Digital-Hub-Team-Guide.pdf` — product/process for Digital Comms  
2. This file — technical handoff for developers  
3. `README.md` — start commands + feature list  

## How to package for another developer

**Option A — Zip (fast)**  
Zip the project **without** `VentureTea-FactoryFloor/`, `data/hub.sqlite`, `data/.hub_key`, `__pycache__/`.

**Option B — GitHub (better)**  
1. Create a private GitHub repo  
2. First commit of Hub code only  
3. Invite the developer as collaborator  
4. They clone + `python3 server.py`

Ask the project owner which option to use if not already decided.
