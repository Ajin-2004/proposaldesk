"""End-to-end test: drives the MCP endpoint like Claude does, then checks the web UI."""
import os
import re
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DEMO_EMAIL"] = "demo@proposaldesk.app"
os.environ["DEMO_PASSWORD"] = "demo-pass-123"

from fastapi.testclient import TestClient  # noqa: E402

import app as appmod  # noqa: E402


def rpc(client, url, method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return client.post(url, json=body)


def tool(client, url, name, args):
    r = rpc(client, url, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return res["isError"], res["content"][0]["text"]


def test_everything():
    import json

    with TestClient(appmod.app) as c:
        # --- login as seeded demo user and find the MCP link
        r = c.post("/login", data={"email": "demo@proposaldesk.app", "password": "demo-pass-123"}, follow_redirects=False)
        assert r.status_code == 303
        page = c.get("/connect").text
        mcp_url = re.search(r"http://testserver(/mcp/[A-Za-z0-9_\-]+)", page).group(1)

        # --- MCP handshake
        init = rpc(c, mcp_url, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}).json()
        assert init["result"]["serverInfo"]["name"] == "proposaldesk"
        assert c.post(mcp_url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
        names = [t["name"] for t in rpc(c, mcp_url, "tools/list").json()["result"]["tools"]]
        assert names == ["create_proposal", "update_proposal", "get_proposal", "list_proposals", "set_status"], names

        # --- Claude creates a proposal
        err, text = tool(c, mcp_url, "create_proposal", {
            "client_name": "Acme", "title": "Brand refresh",
            "scope": "Three-page brand refresh.\nTwo rounds of revisions.",
            "items": [{"description": "Design", "qty": 3, "rate": 15000}, {"description": "Handover", "rate": 15000}],
            "currency": "inr", "terms": "50% advance", "valid_until": "2026-11-19"})
        assert not err, text
        created = json.loads(text)
        assert created["total"] == 60000 and created["status"] == "Draft" and created["currency"] == "INR"

        # --- it appears in the web UI
        assert "Brand refresh" in c.get("/proposals").text
        pid = created["id"]
        edit = c.get(f"/proposals/{pid}")
        assert edit.status_code == 200 and "Three-page brand refresh" in edit.text

        # --- the person edits it in the UI
        r = c.post(f"/proposals/{pid}", data={
            "client_name": "Acme Ltd", "title": "Brand refresh v2", "scope": "Edited scope", "terms": "100% advance",
            "valid_until": "2026-12-01", "currency": "INR", "status": "Sent",
            "item_desc": ["Design", "Extra"], "item_qty": ["2", "1"], "item_rate": ["10000", "5000"]}, follow_redirects=False)
        assert r.status_code == 303

        # --- Claude sees the person's edits
        err, text = tool(c, mcp_url, "get_proposal", {"id": pid})
        got = json.loads(text)
        assert got["client_name"] == "Acme Ltd" and got["status"] == "Sent" and got["total"] == 25000

        # --- Claude updates and sets status
        err, text = tool(c, mcp_url, "update_proposal", {"id": pid, "terms": "30 days net"})
        assert json.loads(text)["terms"] == "30 days net" and json.loads(text)["total"] == 25000
        err, text = tool(c, mcp_url, "set_status", {"id": pid, "status": "accepted"})
        assert json.loads(text)["status"] == "Accepted"
        err, text = tool(c, mcp_url, "list_proposals", {"status": "Accepted"})
        assert json.loads(text)["count"] == 1

        # --- error paths come back as tool errors, not crashes
        assert tool(c, mcp_url, "set_status", {"id": pid, "status": "bogus"})[0] is True
        assert tool(c, mcp_url, "get_proposal", {"id": 9999})[0] is True
        assert tool(c, mcp_url, "create_proposal", {"title": "no client"})[0] is True
        assert rpc(c, mcp_url, "tools/call", {"name": "nope", "arguments": {}}).json()["error"]["code"] == -32602

        # --- public share page works logged out, and shows the price
        share = got["share_url"].replace("http://testserver", "")
        anon = TestClient(appmod.app)
        pub = anon.get(share)
        assert pub.status_code == 200 and "₹25,000.00" in pub.text and "Brand refresh v2" in pub.text
        assert anon.get("/proposals", follow_redirects=False).status_code == 303
        assert anon.get(f"/proposals/{pid}", follow_redirects=False).status_code == 303

        # --- bad token rejected
        assert anon.post("/mcp/not-a-real-token", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401

        # --- HTML in content is escaped on the public page (XSS check)
        err, text = tool(c, mcp_url, "create_proposal", {"client_name": "X", "title": "<script>alert(1)</script>"})
        share2 = json.loads(text)["share_url"].replace("http://testserver", "")
        assert "<script>alert(1)</script>" not in anon.get(share2).text

        # --- another user cannot see demo's proposals, and the free limit holds
        other = TestClient(appmod.app)
        r = other.post("/signup", data={"email": "free@example.com", "password": "password123"}, follow_redirects=False)
        assert r.status_code == 303
        assert f"Brand refresh" not in other.get("/proposals").text
        assert other.get(f"/proposals/{pid}").status_code == 404
        other_url = re.search(r"(/mcp/[A-Za-z0-9_\-]+)", other.get("/connect").text).group(1)
        for i in range(3):
            assert tool(other, other_url, "create_proposal", {"client_name": "C", "title": f"T{i}"})[0] is False
        err, text = tool(other, other_url, "create_proposal", {"client_name": "C", "title": "T4"})
        assert err and "Free plan limit" in text

        # --- rotating the link kills the old one
        other.post("/connect/rotate")
        assert other.post(other_url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401

        # --- delete
        assert c.post(f"/proposals/{pid}/delete", follow_redirects=False).status_code == 303
        assert c.get(f"/proposals/{pid}").status_code == 404


def test_no_ai_inside():
    root = os.path.dirname(os.path.abspath(__file__))
    banned = re.compile(r"openai|anthropic|api[_-]?key|sk-[A-Za-z0-9]{10,}|google\.generativeai|cohere|langchain", re.I)
    for name in ("app.py", "requirements.txt"):
        text = open(os.path.join(root, name)).read()
        assert not banned.search(text), f"AI reference found in {name}"
