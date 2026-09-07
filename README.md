# BCOBA Digital Hub (1st cut)

Internal Digital & Social Media Management Hub for Bandaranayake College OBA.

**One Hub · Many sources · One brand · One calendar · Controlled approval · Multi-channel packs · Engagement + analytics**

Main Hall Development is seeded as **Campaign #1** under Category **Projects**. It is not hard-coded into the application.

## Start

```bash
python3 server.py
# or: ./start.sh
```

Open **http://localhost:8787**

Health: http://localhost:8787/api/health

## Demo logins

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@bcoba.lk | admin123 |
| Editor | editor@bcoba.lk | editor123 |
| Approver | approver@bcoba.lk | approve123 |
| Contributor | contributor@bcoba.lk | contrib123 |
| Channel Admin | channel@bcoba.lk | channel123 |

## 1st cut includes

- Categories + campaigns (create new campaigns in Admin UI)
- Content intake → review → approve → schedule → mark published
- Master content + channel adaptations (Facebook, Instagram, LinkedIn, WhatsApp, YouTube)
- Auto hashtags: master + category + campaign
- Master content calendar
- Media library by category/campaign
- Engagement log (reply / escalate)
- Analytics by ops status, category, campaign, platform, hashtag

## Not in 1st cut

- TikTok, Facebook/Instagram Reels (planned — see `docs/BCOBA-Digital-Hub-Team-Guide.md`)
- Deep API analytics, membership/payments integrations

## Team guide

Shareable overview for Digital Comms / PPA teams:

**[`docs/BCOBA-Digital-Hub-Team-Guide.md`](docs/BCOBA-Digital-Hub-Team-Guide.md)**
- What the Hub does and how the draft → approve → publish flow works
- Channel status (Facebook live; WhatsApp manual; IG/LinkedIn partial)
- Roadmap: **Reels** + **TikTok**

## Connections (auto-post + live analytics)

1. Open **Connections**
2. Save Facebook Page / Instagram / LinkedIn access tokens (encrypted locally)
3. In **Publisher**: **Auto-publish now**, or **Schedule** (background job every 60s)
4. After posts go live: **Sync analytics** to pull reach/likes/comments

WhatsApp stays manual (copy pack). YouTube credentials can be stored; full upload comes later.

## Sample data (for analytics demo)

```bash
python3 scripts/seed_sample.py --force
```

Or in the app (admin): **Analytics → Load sample data**

This creates published posts across Projects / Alumni / Sports / History with hashtags and engagement metrics.

## Data

SQLite database: `data/hub.sqlite`  
Uploads: `data/uploads/`

## Related

Public Main Hall campaign site (sibling): `../restoring-the-pride` (port 8765)
