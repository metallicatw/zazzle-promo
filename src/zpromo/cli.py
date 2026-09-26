"""Command line entry point:  python -m zpromo.cli <command>

  probe            抓一頁 Zazzle feed 看解析結果（第一次部署先跑這個）
  harvest          依序抓取各分類前 15 頁（每次有預算上限）
  plan             產生今天（CSV 模式為未來 7 天）的發文排程
  post             發出已到時間的貼文
  hourly           = plan + post（GitHub Actions 每小時）
  daily            = 自家商店同步 + harvest + plan + Pinterest CSV + metrics + 匯入銷售 + 報告 + 網站
  export-pinterest 產生 Pinterest 批次上傳 CSV
  metrics / import-sales / report / build-site / status
  threads-refresh  續期 Threads token（有 GH_PAT 時自動寫回 repo secret）
  auth-pinterest   取得 Pinterest refresh token（本機一次性）
  auth-tumblr      取得 Tumblr OAuth1 token（本機一次性）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import requests

from . import harvest as hv
from . import planner, publisher, report, sales, site
from .config import DATA_DIR, SITE_DIR, STATE_DIR, load_categories, load_settings
from .db import connect, iso, kv_get, kv_set, utcnow
from .zazzle_feed import FeedClient

log = logging.getLogger("zpromo")


def _client(settings):
    z = settings["zazzle"]
    return FeedClient(z["feed_base"], z.get("request_delay_seconds", 3))


def notify(settings, text: str):
    url = os.environ.get("NOTIFY_WEBHOOK")
    if not url:
        return
    try:
        requests.post(url, json={"content": text[:1900], "text": text[:3900]}, timeout=15)
    except Exception as e:  # noqa: BLE001
        log.warning("notify failed: %s", e)


def step_summary(md: str):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")


def set_github_secret(name: str, value: str) -> bool:
    """Write a repo secret via the GitHub API (needs GH_PAT with Secrets: write)."""
    tok, repo = os.environ.get("GH_PAT"), os.environ.get("GITHUB_REPOSITORY")
    if not (tok and repo):
        return False
    from base64 import b64encode

    from nacl import encoding, public
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    key = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=h, timeout=30).json()
    box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    enc = b64encode(box.encrypt(value.encode())).decode()
    r = requests.put(f"https://api.github.com/repos/{repo}/actions/secrets/{name}", headers=h,
                     json={"encrypted_value": enc, "key_id": key["key_id"]}, timeout=30)
    return r.status_code in (201, 204)


# ---------------------------------------------------------------- commands
def cmd_probe(con, S, C, a):
    cl = _client(S)
    cat = C[0]
    items = cl.search(cat.qs, 1, 5, S["zazzle"].get("sort_period", 30))
    print(f"[search '{cat.qs}' p1] {len(items)} items")
    for it in items:
        print(json.dumps(it.__dict__, ensure_ascii=False)[:400])
    for st in S["zazzle"]["own_stores"]:
        own = cl.store(st, 1, 5)
        print(f"[store {st}] {len(own)} items", *(f"  {i.product_id} {i.title[:60]} store={i.store}" for i in own), sep="\n")
    return {"search_items": len(items)}


def cmd_harvest(con, S, C, a):
    today = utcnow().date()
    res = {}
    if a.own or today.weekday() == 0 or not con.execute("SELECT 1 FROM products WHERE is_own=1 LIMIT 1").fetchone():
        res["own_products"] = hv.harvest_own_stores(con, _client(S), S)
    res.update(hv.run_harvest(con, _client(S), C, S, today))
    return res


def cmd_plan(con, S, C, a):
    return planner.plan(con, S, C)


def cmd_post(con, S, C, a):
    return publisher.run_posts(con, S, C, per_run=a.per_run)


def cmd_hourly(con, S, C, a):
    return {"plan": cmd_plan(con, S, C, a), "post": cmd_post(con, S, C, a)}


def cmd_export_pinterest(con, S, C, a):
    pc = S["platforms"]["pinterest"]
    if not pc.get("enabled") or pc.get("mode") != "csv":
        return {"skipped": "pinterest not in csv mode"}
    first = kv_get(con, "pinterest_last_export") is None
    if not (a.force or first or utcnow().date().weekday() == int(pc.get("csv_export_weekday", 0))):
        return {"skipped": "not export day"}
    files = publisher.export_pinterest_csv(con, S, C, STATE_DIR / "exports" / "pinterest")
    kv_set(con, "pinterest_last_export", iso(utcnow()))
    con.commit()
    return {"files": [f.name for f in files]}


def cmd_metrics(con, S, C, a):
    return publisher.collect_metrics(con, S)


def cmd_import_sales(con, S, C, a):
    return sales.import_dir(con, DATA_DIR / "zazzle_reports")


def cmd_report(con, S, C, a):
    st = report.build_stats(con, S, C)
    public = not S.get("privacy", {}).get("public_money", False)
    md_full = report.to_markdown(st)
    md = report.to_markdown(st, hide_money=public)
    out = STATE_DIR / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{utcnow().date().isoformat()}.md").write_text(md, encoding="utf-8")
    step_summary(md)
    if S.get("notify", {}).get("daily_summary") or (st["alerts"] and S.get("notify", {}).get("on_error")):
        notify(S, md_full)  # webhook is private -> full numbers
    print(md)
    return {"alerts": len(st["alerts"])}


def cmd_build_site(con, S, C, a):
    st = report.build_stats(con, S, C)
    if not S.get("privacy", {}).get("public_money", False):
        st = report.redact_money(st)
    return site.build(con, S, C, st, SITE_DIR)


def cmd_daily(con, S, C, a):
    out = {}
    for name, fn in [("harvest", cmd_harvest), ("plan", cmd_plan), ("export_pinterest", cmd_export_pinterest),
                     ("metrics", cmd_metrics), ("import_sales", cmd_import_sales), ("report", cmd_report),
                     ("site", cmd_build_site)]:
        try:
            out[name] = fn(con, S, C, a)
        except Exception as e:  # noqa: BLE001 — one failing stage must not kill the rest
            log.exception("daily stage %s failed", name)
            out[name] = {"error": str(e)[:300]}
    return out


def cmd_status(con, S, C, a):
    print(report.to_markdown(report.build_stats(con, S, C)))  # local/private use
    return {}


def cmd_threads_refresh(con, S, C, a):
    from .platforms.threads import refresh_token
    data = refresh_token(os.environ["THREADS_ACCESS_TOKEN"])
    new = data["access_token"]
    kv_set(con, "threads_token_set_at", iso(utcnow()))
    con.commit()
    if set_github_secret("THREADS_ACCESS_TOKEN", new):
        return {"refreshed": True, "secret_updated": True, "expires_in": data.get("expires_in")}
    print("NEW THREADS TOKEN (update the repo secret THREADS_ACCESS_TOKEN):\n" + new)
    return {"refreshed": True, "secret_updated": False}


def cmd_auth_pinterest(con, S, C, a):
    app_id, secret = os.environ["PINTEREST_APP_ID"], os.environ["PINTEREST_APP_SECRET"]
    redirect = a.redirect or "http://localhost:8085/"
    if not a.code:
        print("1) 開啟以下網址授權，完成後複製網址列 ?code= 後面的值：\n"
              f"https://www.pinterest.com/oauth/?client_id={app_id}&redirect_uri={redirect}"
              "&response_type=code&scope=boards:read,boards:write,pins:read,pins:write,user_accounts:read")
        print("2) 再執行：python -m zpromo.cli auth-pinterest --code <CODE>")
        return {}
    r = requests.post("https://api.pinterest.com/v5/oauth/token", auth=(app_id, secret),
                      data={"grant_type": "authorization_code", "code": a.code, "redirect_uri": redirect}, timeout=30)
    d = r.json()
    print(json.dumps({k: d.get(k) for k in ("refresh_token", "refresh_token_expires_in", "scope")}, indent=1))
    return {}


def cmd_auth_tumblr(con, S, C, a):
    from requests_oauthlib import OAuth1Session
    ck, cs = os.environ["TUMBLR_CONSUMER_KEY"], os.environ["TUMBLR_CONSUMER_SECRET"]
    oa = OAuth1Session(ck, client_secret=cs, callback_uri="http://localhost:8085/")
    tok = oa.fetch_request_token("https://www.tumblr.com/oauth/request_token")
    print("開啟並授權：", oa.authorization_url("https://www.tumblr.com/oauth/authorize"))
    verifier = input("貼上跳轉網址中的 oauth_verifier：").strip()
    oa = OAuth1Session(ck, client_secret=cs, resource_owner_key=tok["oauth_token"],
                       resource_owner_secret=tok["oauth_token_secret"], verifier=verifier)
    acc = oa.fetch_access_token("https://www.tumblr.com/oauth/access_token")
    print(f"TUMBLR_TOKEN={acc['oauth_token']}\nTUMBLR_TOKEN_SECRET={acc['oauth_token_secret']}")
    return {}


def cmd_keygen(con, S, C, a):
    from .crypto import keygen
    print("把下面這串存成 GitHub repo secret ZPROMO_KEY（也請自己另外備份）：\n" + keygen())
    return {}


def cmd_encrypt_file(con, S, C, a):
    from pathlib import Path

    from .crypto import encrypt_file
    out = encrypt_file(Path(a.path))
    return {"written": str(out)}


COMMANDS = {
    "probe": cmd_probe, "harvest": cmd_harvest, "plan": cmd_plan, "post": cmd_post, "hourly": cmd_hourly,
    "daily": cmd_daily, "export-pinterest": cmd_export_pinterest, "metrics": cmd_metrics,
    "import-sales": cmd_import_sales, "report": cmd_report, "build-site": cmd_build_site, "status": cmd_status,
    "threads-refresh": cmd_threads_refresh, "auth-pinterest": cmd_auth_pinterest, "auth-tumblr": cmd_auth_tumblr,
    "keygen": cmd_keygen, "encrypt-file": cmd_encrypt_file,
}
NO_RUN_LOG = {"probe", "status", "auth-pinterest", "auth-tumblr", "keygen", "encrypt-file"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="zpromo")
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--per-run", type=int, default=3, help="max posts per platform per run")
    ap.add_argument("--own", action="store_true", help="force own-store resync")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--code")
    ap.add_argument("--redirect")
    ap.add_argument("--path", help="file for encrypt-file")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    S, C = load_settings(), load_categories()
    con = connect(STATE_DIR / "zpromo.sqlite")
    started = iso(utcnow())
    ok, res = True, {}
    try:
        res = COMMANDS[a.command](con, S, C, a) or {}
    except Exception as e:
        ok, res = False, {"error": str(e)[:500]}
        log.exception("command failed")
        notify(S, f"❌ zpromo {a.command} failed: {e}")
    finally:
        if a.command not in NO_RUN_LOG:
            con.execute("INSERT INTO runs(command,started_at,finished_at,ok,summary) VALUES(?,?,?,?,?)",
                        (a.command, started, iso(utcnow()), int(ok), json.dumps(res, ensure_ascii=False, default=str)[:2000]))
            con.commit()
    print(json.dumps(res, ensure_ascii=False, default=str, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

