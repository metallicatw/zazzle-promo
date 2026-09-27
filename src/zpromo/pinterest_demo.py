"""Local demo app for the Pinterest Standard-access review video.

    python -m zpromo.cli pinterest-demo            (then open http://localhost:8085)

What the reviewer needs to see (Pinterest developer guidelines):
  1. a real OAuth 2.0 flow on pinterest.com (no password / cookies collected by the app)
  2. a live integration: read the account + boards, create a board, create a Pin, show the API responses
Flow of this app:  / → "Connect with Pinterest" → Pinterest consent screen → /callback
  → /app (account, boards, Zazzle products) → preview → Publish → API response + link to the Pin.

Trial apps may only write to the Sandbox (api-sandbox.pinterest.com, Pins visible only to you).
Put a Sandbox token (developers.pinterest.com → My apps → your app → "Generate sandbox token")
in PINTEREST_SANDBOX_TOKEN and writes go there; reads (account, boards) use the OAuth token.
The refresh token from the OAuth exchange is printed to this console (never shown on the page),
so it can be saved as the GitHub secret PINTEREST_REFRESH_TOKEN afterwards.
"""
from __future__ import annotations

import base64
import html
import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from . import copywriter
from .boards import board_name, board_specs
from .config import load_categories, load_settings
from .links import referral_link
from .pinimage import make_pin
from .zazzle_feed import FeedClient

PROD = "https://api.pinterest.com/v5"
SANDBOX = "https://api-sandbox.pinterest.com/v5"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
e = html.escape

STATE: dict = {"token": None, "oauth_state": None, "products": {}, "log": []}

CSS = """body{margin:0;font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:#faf8f4;color:#222}
main{max-width:980px;margin:0 auto;padding:24px 16px}h1{margin:0 0 4px}.muted{color:#666}
.card{background:#fff;border:1px solid #e5e1da;border-radius:12px;padding:16px;margin:14px 0}
.btn{display:inline-block;background:#e60023;color:#fff;border:0;border-radius:24px;padding:10px 20px;
font-weight:600;text-decoration:none;cursor:pointer;font-size:15px}.btn.gray{background:#555}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
.grid a{color:inherit;text-decoration:none;border:1px solid #e5e1da;border-radius:10px;overflow:hidden;background:#fff}
.grid img{width:100%;aspect-ratio:1;object-fit:contain;background:#fff}.grid div{padding:6px 8px;font-size:13px}
pre{background:#1e1e1e;color:#d4f7c5;padding:12px;border-radius:8px;overflow:auto;font-size:12.5px;max-height:320px}
table{border-collapse:collapse}td{padding:3px 10px 3px 0;vertical-align:top}.tag{background:#eee;border-radius:6px;padding:1px 6px;font-size:12px}"""


def page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>"
            f"<h1>zpromo · Zazzle Pin Scheduler</h1><p class=muted>Personal tool that turns Zazzle products into "
            f"Pinterest Pins on my own account (Kanavrin) with my affiliate link.</p>{body}"
            f"<p class=muted style='margin-top:40px'><a href='/privacy'>Privacy policy</a> · "
            f"Data stays on this computer; tokens are held in memory only.</p></main></body></html>").encode()


def api(method: str, path: str, *, write=False, **kw):
    sandbox_tok = os.environ.get("PINTEREST_SANDBOX_TOKEN")
    base, tok = (SANDBOX, sandbox_tok) if (write and sandbox_tok) else (PROD, STATE["token"])
    r = requests.request(method, base + path, headers={"Authorization": f"Bearer {tok}"}, timeout=60, **kw)
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:500]}
    STATE["log"].insert(0, {"call": f"{method} {base.split('//')[1]}{path}", "status": r.status_code, "response": data})
    return r.status_code, data


def load_products(S, C):
    if STATE["products"]:
        return
    fc = FeedClient(S["zazzle"]["feed_base"], 1)
    items = []
    for st in S["zazzle"]["own_stores"][:1]:
        items += [(i, True, C[0]) for i in fc.store(st, 1, 4)]
    cat = next((c for c in C if c.in_season(__import__("datetime").date.today())), C[0])
    items += [(i, False, cat) for i in fc.search(cat.qs, 1, 8)]
    for it, own, c in items:
        STATE["products"][it.product_id] = {"item": it, "own": own, "cat": c}


class H(BaseHTTPRequestHandler):
    S = C = None
    app_id = secret = redirect = None

    def log_message(self, *a):  # quiet
        pass

    def send(self, body: bytes, code=200, ctype="text/html; charset=utf-8", location=None):
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ routes
    def do_GET(self):  # noqa: C901
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/":
            body = ("<div class=card><h2>1. Connect your Pinterest account</h2><p>You will be sent to "
                    "<b>pinterest.com</b> to sign in and approve access. This app never sees your password.</p>"
                    f"<p>Requested scopes: {' '.join(f'<span class=tag>{s}</span>' for s in SCOPES.split(','))}</p>"
                    "<a class=btn href='/login'>Connect with Pinterest</a></div>")
            return self.send(page("zpromo demo", body))
        if u.path == "/login":
            STATE["oauth_state"] = secrets.token_urlsafe(16)
            url = "https://www.pinterest.com/oauth/?" + urlencode({
                "client_id": self.app_id, "redirect_uri": self.redirect, "response_type": "code",
                "scope": SCOPES, "state": STATE["oauth_state"]})
            return self.send(b"", 302, location=url)
        if u.path == "/callback":
            if q.get("state") != STATE["oauth_state"] or "code" not in q:
                return self.send(page("error", f"<div class=card>OAuth failed: {e(json.dumps(q))}</div>"), 400)
            r = requests.post(f"{PROD}/oauth/token", auth=(self.app_id, self.secret), timeout=30, data={
                "grant_type": "authorization_code", "code": q["code"], "redirect_uri": self.redirect})
            d = r.json()
            if "access_token" not in d:
                return self.send(page("error", f"<div class=card><pre>{e(json.dumps(d, indent=1))}</pre></div>"), 400)
            STATE["token"] = d["access_token"]
            print("\n=== OAuth OK. Save this as GitHub secret PINTEREST_REFRESH_TOKEN (do NOT show on video) ===")
            print(d.get("refresh_token"), "\n(expires in", d.get("refresh_token_expires_in"), "s)\n")
            STATE["log"].insert(0, {"call": "POST api.pinterest.com/v5/oauth/token", "status": r.status_code,
                                    "response": {k: ("•••" if "token" in k else v) for k, v in d.items()}})
            return self.send(b"", 302, location="/app")
        if u.path == "/app":
            if not STATE["token"]:
                return self.send(b"", 302, location="/")
            _, me = api("GET", "/user_account")
            _, bd = api("GET", "/boards", params={"page_size": 50})
            load_products(self.S, self.C)
            boards = "".join(f"<li>{e(b['name'])} <span class=muted>({b.get('pin_count', '?')} pins)</span></li>"
                             for b in bd.get("items", [])) or "<li class=muted>no boards yet</li>"
            grid = "".join(
                f"<a href='/preview?pid={pid}'><img src='{e(p['item'].image_url or '')}'><div>"
                f"{'<b>MY SHOP</b> · ' if p['own'] else ''}{e(p['item'].title[:70])}</div></a>"
                for pid, p in STATE["products"].items())
            body = (f"<div class=card><h2>2. Connected ✅</h2><table><tr><td>Account</td><td><b>{e(me.get('username', '?'))}</b>"
                    f" ({e(me.get('account_type', ''))})</td></tr></table><h3>Your boards (GET /v5/boards)</h3><ul>{boards}</ul></div>"
                    f"<div class=card><h2>3. Pick a Zazzle product to pin</h2><p class=muted>Live from Zazzle's public RSS feed."
                    f"</p><div class=grid>{grid}</div></div>{self.log_html()}")
            return self.send(page("zpromo demo", body))
        if u.path == "/preview":
            p = STATE["products"].get(q.get("pid", ""))
            if not p:
                return self.send(b"", 302, location="/app")
            it, own, cat = p["item"], p["own"], p["cat"]
            link = referral_link(it.url, is_own=own, ambassador_id=self.S["zazzle"]["ambassador_id"],
                                 tracking_code=None if own else "pin")
            prod = {"product_id": it.product_id, "title": it.title, "price": it.price, "store": it.store,
                    "description": it.description, "keywords": it.keywords, "is_own": own}
            copy = copywriter.build(prod, cat, self.S, "pinterest", link)
            img = make_pin(it.image_url, copy["title"])
            p.update(copy=copy, link=link, img=img, board=board_name(cat, self.S),
                     board_desc=board_specs([cat], self.S)[board_name(cat, self.S)]["description"])
            body = (f"<div class=card><h2>4. Review the Pin before publishing</h2><div style='display:flex;gap:20px;flex-wrap:wrap'>"
                    f"<img style='width:260px;border-radius:10px;border:1px solid #ddd' src='data:image/jpeg;base64,"
                    f"{base64.b64encode(img).decode()}'><table><tr><td>Board</td><td><b>{e(p['board'])}</b></td></tr>"
                    f"<tr><td>Title</td><td>{e(copy['title'])}</td></tr><tr><td>Description</td><td>{e(copy['description'])}</td></tr>"
                    f"<tr><td>Link</td><td>{e(link)}</td></tr><tr><td>Alt text</td><td>{e(copy['alt'])}</td></tr></table></div>"
                    f"<form method=post action='/publish'><input type=hidden name=pid value='{e(it.product_id)}'>"
                    f"<p><button class=btn>Publish Pin</button> <a class='btn gray' href='/app'>Cancel</a></p></form></div>")
            return self.send(page("preview", body))
        if u.path == "/privacy":
            return self.send(page("privacy", PRIVACY_HTML))
        return self.send(b"not found", 404, "text/plain")

    def do_POST(self):
        if self.path != "/publish":
            return self.send(b"", 404)
        n = int(self.headers.get("Content-Length", 0))
        pid = parse_qs(self.rfile.read(n).decode()).get("pid", [""])[0]
        p = STATE["products"].get(pid)
        if not p or "copy" not in p:
            return self.send(b"", 302, location="/app")
        # find or create the board
        _, bd = api("GET", "/boards", write=True, params={"page_size": 100})
        board = next((b for b in bd.get("items", []) if b["name"].lower() == p["board"].lower()), None)
        if not board:
            _, board = api("POST", "/boards", write=True, json={"name": p["board"], "description": p["board_desc"],
                                                                 "privacy": "PUBLIC"})
        code, pin = api("POST", "/pins", write=True, json={
            "board_id": board.get("id"), "title": p["copy"]["title"], "description": p["copy"]["description"],
            "link": p["link"], "alt_text": p["copy"]["alt"],
            "media_source": {"source_type": "image_base64", "content_type": "image/jpeg",
                             "data": base64.b64encode(p["img"]).decode()}})
        ok = code in (200, 201) and pin.get("id")
        sandbox = bool(os.environ.get("PINTEREST_SANDBOX_TOKEN"))
        msg = (f"<h2>5. Pin created ✅</h2><p>Pin id <b>{e(pin['id'])}</b> on board <b>{e(p['board'])}</b>"
               f"{' (Sandbox – visible only to me)' if sandbox else ''}.</p>"
               f"<p><a class=btn target=_blank href='https://www.pinterest.com/pin/{e(pin['id'])}/'>Open on Pinterest</a> "
               f"<a class='btn gray' href='/app'>Back</a></p>") if ok else "<h2>Publish failed</h2>"
        self.send(page("done", f"<div class=card>{msg}</div>{self.log_html()}"))

    def log_html(self) -> str:
        rows = "".join(f"<p><b>{e(x['call'])}</b> → {x['status']}</p><pre>{e(json.dumps(x['response'], indent=1)[:1500])}</pre>"
                       for x in STATE["log"][:4])
        return f"<div class=card><h2>API calls (latest first)</h2>{rows}</div>" if rows else ""


PRIVACY_HTML = """<div class=card><h2>Privacy policy</h2>
<p>zpromo is a personal automation tool operated by the owner of the Pinterest account it is connected to.
It is not offered to other users.</p>
<ul><li><b>Data accessed:</b> your Pinterest account name, your boards and the Pins this tool creates, plus Pin
analytics (impressions, saves, outbound clicks) for those Pins.</li>
<li><b>Purpose:</b> create and schedule Pins of Zazzle products on your own boards and measure their performance.</li>
<li><b>Storage:</b> the OAuth refresh token is stored as an encrypted GitHub Actions secret; post history is stored
encrypted. No data is sold or shared with third parties.</li>
<li><b>Revoke access:</b> Pinterest → Settings → Security → Connected apps → remove the app at any time.</li>
<li><b>Contact:</b> eggeggyang2005@gmail.com</li></ul></div>"""


def serve(port: int = 8085):
    S, C = load_settings(), load_categories()
    H.S, H.C = S, C
    H.app_id, H.secret = os.environ["PINTEREST_APP_ID"], os.environ["PINTEREST_APP_SECRET"]
    H.redirect = f"http://localhost:{port}/callback"
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"Demo running: http://localhost:{port}   (redirect URI to register: {H.redirect})")
    print("Sandbox writes:", "ON" if os.environ.get("PINTEREST_SANDBOX_TOKEN") else "OFF (production API)")
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
