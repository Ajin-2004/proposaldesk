# ProposalDesk

A proposal and quote tracker for freelancers that runs on the customer's own Claude.

- **Claude does the thinking and writing.** The customer types one sentence; Claude writes the scope, line items and terms and calls this app's MCP tools.
- **The app does everything else:** saves it, totals it, lets the person edit it, tracks Draft / Sent / Accepted / Rejected, and serves a clean share link for the client.
- **No AI inside.** No AI SDK, no API keys, no model calls. Dependencies are FastAPI, Jinja2 and SQLite.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://localhost:8000. A test user is created on first start:

- Email: `demo@proposaldesk.app`
- Password: `demo-pass-123` (override with `DEMO_EMAIL` / `DEMO_PASSWORD`)

Run the tests: `pip install pytest httpx && pytest -q`

## Environment variables

| Name | Purpose |
|---|---|
| `SECRET_KEY` | Signs login cookies. Set a long random value in production. |
| `DB_PATH` | SQLite file location. Put it on a persistent disk/volume. |
| `BASE_URL` | Optional. Public URL (e.g. `https://proposaldesk.onrender.com`) if links come out wrong. |
| `HTTPS_ONLY` | `1` marks the login cookie as Secure (set in the Dockerfile). |
| `DEMO_EMAIL`, `DEMO_PASSWORD` | Test login, created on start with the Pro plan. |

## Deploy

**Important:** SQLite is a file, so it needs a disk that survives restarts. Without one, data is wiped on every deploy.

### Render
1. Push this folder to a GitHub repo.
2. In Render: New → Blueprint → pick the repo. `render.yaml` sets up the Docker service, a 1 GB disk and a generated `SECRET_KEY`.
3. When it is live, open `https://<your-app>.onrender.com/healthz`. You should see `{"ok":true}`.

### Fly.io
```bash
fly launch --no-deploy          # accept the Dockerfile
fly volumes create data --size 1
# in fly.toml add:  [mounts]  source = "data"  destination = "/data"
fly secrets set SECRET_KEY=$(openssl rand -hex 32)
fly deploy
```

## Connect it to Claude

1. Log in to the live app and open **Connect Claude** (`/connect`). It shows your private MCP link, which looks like `https://<your-app>/mcp/<long-token>`.
2. In Claude: **Settings → Connectors → Add custom connector**. Paste the link. Leave OAuth fields empty.
3. Start a new chat and ask: *"Draft a proposal for Acme for a 3-page brand refresh, ₹60,000, valid for two weeks. Include a 50% advance."*
4. Open **Proposals** in the app. The proposal is there. Edit it, change its status, open the client link.

The token in the link is the login for Claude, so treat it like a password. **Generate a new link** on the same page revokes the old one.

## MCP tools

| Tool | What it does |
|---|---|
| `create_proposal` | New Draft with client, title, scope, line items, currency, terms, valid-until. Total is calculated by the app. |
| `update_proposal` | Change any fields. Sending `items` replaces all line items. |
| `get_proposal` | Full details of one proposal. |
| `list_proposals` | All proposals, optionally filtered by status. |
| `set_status` | Draft, Sent, Accepted or Rejected. |

The free plan allows 3 proposals; the seeded demo user is on Pro. There is no payment integration in this first version.

## Notes and limits of v1

- MCP transport is plain JSON-RPC over HTTP POST (no streaming), which is enough for tool calls.
- Auth to MCP is a secret per-user URL rather than OAuth, to keep setup to one paste.
- Login uses signed cookies with SameSite=Lax; there are no CSRF tokens yet.
- No password reset or email sending yet.
