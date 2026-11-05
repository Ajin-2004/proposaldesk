"""ProposalDesk: a proposal/quote tracker for freelancers.

There is NO AI in this app. The customer's own Claude (connected through MCP)
does the thinking and writing; this app only saves, serves and lets people edit.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "proposaldesk.db"))
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
PUBLIC_BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
FREE_LIMIT = 3
STATUSES = ["Draft", "Sent", "Accepted", "Rejected"]
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$", "CAD": "C$"}

app = FastAPI(title="ProposalDesk", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=os.environ.get("HTTPS_ONLY", "0") == "1",
    max_age=60 * 60 * 24 * 14,
)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ---------------------------------------------------------------- database
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def q(sql, args=(), one=False):
    with closing(_conn()) as c:
        rows = c.execute(sql, args).fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def x(sql, args=()):
    with closing(_conn()) as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def init_db():
    with closing(_conn()) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                mcp_token TEXT UNIQUE NOT NULL,
                plan TEXT NOT NULL DEFAULT 'free',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                client_name TEXT NOT NULL,
                title TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                items_json TEXT NOT NULL DEFAULT '[]',
                currency TEXT NOT NULL DEFAULT 'INR',
                terms TEXT NOT NULL DEFAULT '',
                valid_until TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Draft',
                share_token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        c.commit()


# ---------------------------------------------------------------- auth
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(check, digest)


def create_user(email: str, password: str, plan: str = "free"):
    return x(
        "INSERT INTO users (email, password_hash, mcp_token, plan, created_at) VALUES (?,?,?,?,?)",
        (email.strip().lower(), hash_password(password), secrets.token_urlsafe(32), plan, now()),
    )


def current_user(request: Request):
    uid = request.session.get("uid")
    if not uid:
        return None
    return q("SELECT * FROM users WHERE id=?", (uid,), one=True)


def seed_demo_user():
    email = os.environ.get("DEMO_EMAIL", "demo@proposaldesk.app").lower()
    password = os.environ.get("DEMO_PASSWORD", "demo-pass-123")
    if not q("SELECT id FROM users WHERE email=?", (email,), one=True):
        create_user(email, password, plan="pro")


# ---------------------------------------------------------------- proposals (shared by UI and MCP)
def clean_items(items):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            raise ValueError("Each line item must be an object with description, qty and rate.")
        desc = str(it.get("description", "")).strip()
        if not desc:
            continue
        try:
            qty = float(it.get("qty", 1))
            rate = float(it.get("rate", 0))
        except (TypeError, ValueError):
            raise ValueError("Line item qty and rate must be numbers.")
        if qty < 0 or rate < 0:
            raise ValueError("Line item qty and rate cannot be negative.")
        out.append({"description": desc, "qty": qty, "rate": rate})
    return out


def items_total(items):
    return round(sum(i["qty"] * i["rate"] for i in items), 2)


def base_url(request: Request) -> str:
    return PUBLIC_BASE_URL or str(request.base_url).rstrip("/")


def proposal_dict(row, base=""):
    items = json.loads(row["items_json"])
    return {
        "id": row["id"],
        "client_name": row["client_name"],
        "title": row["title"],
        "scope": row["scope"],
        "items": items,
        "total": items_total(items),
        "currency": row["currency"],
        "terms": row["terms"],
        "valid_until": row["valid_until"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "edit_url": f"{base}/proposals/{row['id']}",
        "share_url": f"{base}/p/{row['share_token']}",
    }


def get_proposal(user_id, pid):
    row = q("SELECT * FROM proposals WHERE id=? AND user_id=?", (pid, user_id), one=True)
    if not row:
        raise ValueError(f"No proposal with id {pid}.")
    return row


def create_proposal(user, data):
    client_name = str(data.get("client_name", "")).strip()
    title = str(data.get("title", "")).strip()
    if not client_name or not title:
        raise ValueError("client_name and title are required.")
    if user["plan"] == "free":
        count = q("SELECT COUNT(*) AS n FROM proposals WHERE user_id=?", (user["id"],), one=True)["n"]
        if count >= FREE_LIMIT:
            raise ValueError(
                f"Free plan limit reached ({FREE_LIMIT} proposals). Delete one or upgrade to Pro for unlimited proposals."
            )
    currency = str(data.get("currency") or "INR").upper()
    items = clean_items(data.get("items"))
    stamp = now()
    pid = x(
        """INSERT INTO proposals
           (user_id, client_name, title, scope, items_json, currency, terms, valid_until, status, share_token, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            user["id"], client_name, title, str(data.get("scope", "")), json.dumps(items), currency,
            str(data.get("terms", "")), str(data.get("valid_until", "")), "Draft",
            secrets.token_urlsafe(12), stamp, stamp,
        ),
    )
    return get_proposal(user["id"], pid)


def update_proposal(user, pid, data):
    row = get_proposal(user["id"], pid)
    fields = {}
    for key in ("client_name", "title", "scope", "terms", "valid_until"):
        if key in data and data[key] is not None:
            fields[key] = str(data[key]).strip() if key in ("client_name", "title") else str(data[key])
    if "currency" in data and data["currency"]:
        fields["currency"] = str(data["currency"]).upper()
    if "items" in data and data["items"] is not None:
        fields["items_json"] = json.dumps(clean_items(data["items"]))
    if "status" in data and data["status"] is not None:
        fields["status"] = normalise_status(data["status"])
    if "client_name" in fields and not fields["client_name"]:
        raise ValueError("client_name cannot be empty.")
    if "title" in fields and not fields["title"]:
        raise ValueError("title cannot be empty.")
    if fields:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        x(f"UPDATE proposals SET {cols} WHERE id=? AND user_id=?", (*fields.values(), row["id"], user["id"]))
    return get_proposal(user["id"], pid)


def normalise_status(value):
    for s in STATUSES:
        if str(value).strip().lower() == s.lower():
            return s
    raise ValueError(f"status must be one of: {', '.join(STATUSES)}.")


def list_proposals(user, status=None):
    if status:
        return q(
            "SELECT * FROM proposals WHERE user_id=? AND status=? ORDER BY updated_at DESC, id DESC",
            (user["id"], normalise_status(status)),
        )
    return q("SELECT * FROM proposals WHERE user_id=? ORDER BY updated_at DESC, id DESC", (user["id"],))


# ---------------------------------------------------------------- template helpers
def money(amount, currency="INR"):
    symbol = CURRENCY_SYMBOLS.get(str(currency).upper(), str(currency).upper() + " ")
    return f"{symbol}{amount:,.2f}"


templates.env.filters["money"] = money
templates.env.globals["STATUSES"] = STATUSES


def render(request, name, **ctx):
    ctx.setdefault("user", current_user(request))
    ctx.setdefault("error", None)
    return templates.TemplateResponse(request, name, ctx)


# ---------------------------------------------------------------- web routes
init_db()
seed_demo_user()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def home(request: Request):
    if current_user(request):
        return RedirectResponse("/proposals", status_code=303)
    return render(request, "home.html")


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    return render(request, "auth.html", mode="signup")


@app.post("/signup")
async def signup(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    if "@" not in email or len(password) < 8:
        return render(request, "auth.html", mode="signup", error="Enter a valid email and a password of at least 8 characters.")
    if q("SELECT id FROM users WHERE email=?", (email,), one=True):
        return render(request, "auth.html", mode="signup", error="That email is already registered.")
    request.session["uid"] = create_user(email, password)
    return RedirectResponse("/connect", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "auth.html", mode="login")


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    row = q("SELECT * FROM users WHERE email=?", (email,), one=True)
    if not row or not verify_password(str(form.get("password", "")), row["password_hash"]):
        return render(request, "auth.html", mode="login", error="Wrong email or password.")
    request.session["uid"] = row["id"]
    return RedirectResponse("/proposals", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


def need_login(request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    return user, None


@app.get("/proposals", response_class=HTMLResponse)
def proposals_page(request: Request, status: str = ""):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    active = status if status in STATUSES else None
    rows = [proposal_dict(r) for r in list_proposals(user, active)]
    total_count = q("SELECT COUNT(*) AS n FROM proposals WHERE user_id=?", (user["id"],), one=True)["n"]
    return render(request, "list.html", proposals=rows, active=active, total_count=total_count, free_limit=FREE_LIMIT)


@app.get("/proposals/new", response_class=HTMLResponse)
def new_form(request: Request):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    blank = {"id": None, "client_name": "", "title": "", "scope": "", "items": [{"description": "", "qty": 1, "rate": 0}],
             "currency": "INR", "terms": "", "valid_until": "", "status": "Draft"}
    return render(request, "edit.html", p=blank)


def form_to_data(form):
    descs, qtys, rates = form.getlist("item_desc"), form.getlist("item_qty"), form.getlist("item_rate")
    items = []
    for i, d in enumerate(descs):
        items.append({"description": d, "qty": qtys[i] if i < len(qtys) and qtys[i] != "" else 1,
                      "rate": rates[i] if i < len(rates) and rates[i] != "" else 0})
    return {
        "client_name": form.get("client_name", ""), "title": form.get("title", ""), "scope": form.get("scope", ""),
        "terms": form.get("terms", ""), "valid_until": form.get("valid_until", ""),
        "currency": form.get("currency", "INR"), "items": items,
    }


@app.post("/proposals")
async def create_from_form(request: Request):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    data = form_to_data(await request.form())
    try:
        row = create_proposal(user, data)
    except ValueError as e:
        data["id"], data["status"] = None, "Draft"
        data["items"] = data["items"] or [{"description": "", "qty": 1, "rate": 0}]
        return render(request, "edit.html", p=data, error=str(e))
    return RedirectResponse(f"/proposals/{row['id']}?saved=1", status_code=303)


@app.get("/proposals/{pid}", response_class=HTMLResponse)
def edit_page(request: Request, pid: int, saved: int = 0):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    try:
        row = get_proposal(user["id"], pid)
    except ValueError:
        return Response("Proposal not found", status_code=404)
    return render(request, "edit.html", p=proposal_dict(row, base_url(request)), saved=bool(saved))


@app.post("/proposals/{pid}")
async def save_from_form(request: Request, pid: int):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    form = await request.form()
    data = form_to_data(form)
    data["status"] = form.get("status") or None
    try:
        update_proposal(user, pid, data)
    except ValueError as e:
        data.update({"id": pid, "status": data["status"] or "Draft"})
        return render(request, "edit.html", p=data, error=str(e))
    return RedirectResponse(f"/proposals/{pid}?saved=1", status_code=303)


@app.post("/proposals/{pid}/delete")
def delete_proposal(request: Request, pid: int):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    x("DELETE FROM proposals WHERE id=? AND user_id=?", (pid, user["id"]))
    return RedirectResponse("/proposals", status_code=303)


@app.get("/p/{token}", response_class=HTMLResponse)
def public_view(request: Request, token: str):
    row = q("SELECT * FROM proposals WHERE share_token=?", (token,), one=True)
    if not row:
        return Response("This proposal link is not valid.", status_code=404)
    owner = q("SELECT email FROM users WHERE id=?", (row["user_id"],), one=True)
    return render(request, "public.html", p=proposal_dict(row), owner_email=owner["email"], user=None)


@app.get("/connect", response_class=HTMLResponse)
def connect_page(request: Request):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    return render(request, "connect.html", mcp_url=f"{base_url(request)}/mcp/{user['mcp_token']}")


@app.post("/connect/rotate")
def rotate_token(request: Request):
    user, redirect = need_login(request)
    if redirect:
        return redirect
    x("UPDATE users SET mcp_token=? WHERE id=?", (secrets.token_urlsafe(32), user["id"]))
    return RedirectResponse("/connect", status_code=303)


# ---------------------------------------------------------------- MCP (JSON-RPC 2.0 over HTTP)
ITEMS_SCHEMA = {
    "type": "array",
    "description": "Priced line items. The app calculates the total, so do not include one.",
    "items": {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "qty": {"type": "number", "description": "Quantity or hours. Defaults to 1."},
            "rate": {"type": "number", "description": "Price per unit in the proposal currency."},
        },
        "required": ["description", "rate"],
    },
}
PROPOSAL_FIELDS = {
    "client_name": {"type": "string", "description": "Client or company name."},
    "title": {"type": "string", "description": "Short proposal title, e.g. 'Brand refresh'."},
    "scope": {"type": "string", "description": "Plain-text scope of work: deliverables, timeline, assumptions. Use line breaks; no markdown tables."},
    "items": ITEMS_SCHEMA,
    "currency": {"type": "string", "description": "ISO code such as INR, USD, EUR, GBP. Defaults to INR."},
    "terms": {"type": "string", "description": "Payment and other terms, plain text."},
    "valid_until": {"type": "string", "description": "Date the quote is valid until, e.g. 2026-12-01."},
}
TOOLS = [
    {
        "name": "create_proposal",
        "description": "Create a new proposal/quote in the user's ProposalDesk as a Draft. Write the scope, line items and terms yourself, then call this. Returns the saved proposal with edit and share links.",
        "inputSchema": {"type": "object", "properties": PROPOSAL_FIELDS, "required": ["client_name", "title"]},
    },
    {
        "name": "update_proposal",
        "description": "Change fields of an existing proposal. Only send the fields you want to change. If you send items, they replace all existing line items.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Proposal id."}, **PROPOSAL_FIELDS},
            "required": ["id"],
        },
    },
    {
        "name": "get_proposal",
        "description": "Get the full details of one proposal by id.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
    {
        "name": "list_proposals",
        "description": "List the user's proposals, newest first, optionally filtered by status.",
        "inputSchema": {"type": "object", "properties": {"status": {"type": "string", "enum": STATUSES}}},
    },
    {
        "name": "set_status",
        "description": "Move a proposal between Draft, Sent, Accepted and Rejected.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "status": {"type": "string", "enum": STATUSES}},
            "required": ["id", "status"],
        },
    },
]
SERVER_INSTRUCTIONS = (
    "ProposalDesk stores freelancer proposals. You write the content (scope, line items, terms); "
    "the app saves it and calculates totals. After creating or updating a proposal, give the user "
    "its edit_url so they can review it, and mention the share_url when they want to send it to the client."
)


def call_tool(user, name, args, base):
    if name == "create_proposal":
        return proposal_dict(create_proposal(user, args), base)
    if name == "update_proposal":
        pid = int(args.get("id", 0))
        return proposal_dict(update_proposal(user, pid, args), base)
    if name == "get_proposal":
        return proposal_dict(get_proposal(user["id"], int(args.get("id", 0))), base)
    if name == "list_proposals":
        rows = [proposal_dict(r, base) for r in list_proposals(user, args.get("status"))]
        return {"count": len(rows), "proposals": [
            {k: p[k] for k in ("id", "client_name", "title", "status", "total", "currency", "updated_at", "edit_url")} for p in rows]}
    if name == "set_status":
        return proposal_dict(update_proposal(user, int(args.get("id", 0)), {"status": args.get("status")}), base)
    raise KeyError(name)


def rpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle_rpc(msg, user, base):
    if not isinstance(msg, dict):
        return rpc_error(None, -32600, "Invalid request")
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if rid is None:  # notification: no response
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": params.get("protocolVersion") or "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "proposaldesk", "version": "1.0.0"},
            "instructions": SERVER_INSTRUCTIONS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            result = call_tool(user, name, args, base)
            text, is_error = json.dumps(result, ensure_ascii=False, indent=2), False
        except KeyError:
            return rpc_error(rid, -32602, f"Unknown tool: {name}")
        except ValueError as e:
            text, is_error = str(e), True
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}
    return rpc_error(rid, -32601, f"Method not found: {method}")


@app.post("/mcp/{token}")
async def mcp_endpoint(request: Request, token: str):
    user = q("SELECT * FROM users WHERE mcp_token=?", (token,), one=True)
    if not user:
        return JSONResponse(rpc_error(None, -32001, "Invalid MCP link"), status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(rpc_error(None, -32700, "Parse error"), status_code=400)
    base = base_url(request)
    if isinstance(body, list):
        replies = [r for r in (handle_rpc(m, user, base) for m in body) if r is not None]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = handle_rpc(body, user, base)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@app.get("/mcp/{token}")
def mcp_get(token: str):
    return Response("This is an MCP endpoint. Add this URL as a custom connector in Claude.", status_code=405, headers={"Allow": "POST"})
