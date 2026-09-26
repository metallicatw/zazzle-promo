"""Execute due posts, collect metrics, export Pinterest CSV."""
from __future__ import annotations

import logging
from datetime import timedelta

from . import copywriter, platforms
from .config import Category
from .db import iso, parse_iso, utcnow
from .planner import SOCIAL, due_posts, reschedule
from .platforms import AuthError, RateLimited

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def _ctx(con, post, catmap, cats):
    product = dict(con.execute("SELECT * FROM products WHERE product_id=?", (post["product_id"],)).fetchone())
    cat = catmap.get(post["category"]) or cats[0]
    return product, cat


def run_posts(con, settings: dict, cats: list[Category], per_run: int = 3) -> dict:
    catmap = {c.key: c for c in cats}
    summary = {}
    for plat in SOCIAL:
        pcfg = settings["platforms"].get(plat, {})
        if not pcfg.get("enabled") or (plat == "pinterest" and pcfg.get("mode") == "csv"):
            continue
        res = {"posted": 0, "failed": 0, "deferred": 0, "error": None}
        due = due_posts(con, plat, per_run)
        if not due:
            summary[plat] = res
            continue
        try:
            client = platforms.get(plat, settings)
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)
            summary[plat] = res
            continue
        for post in due:
            product, cat = _ctx(con, post, catmap, cats)
            copy = copywriter.build(product, cat, settings, plat, post["link"])
            try:
                rid, rurl = client.publish(post, product, cat, copy)
                con.execute("UPDATE posts SET status='posted',posted_at=?,remote_id=?,remote_url=?,error=NULL,"
                            "attempts=attempts+1 WHERE id=?", (iso(utcnow()), rid, rurl, post["id"]))
                res["posted"] += 1
            except RateLimited as e:
                log.warning("%s rate limited: %s", plat, e)
                for p in due:  # push everything still pending back 2h
                    reschedule(con, p["id"], 120)
                res["error"], res["deferred"] = f"rate limited: {e}", len(due) - res["posted"]
                con.commit()
                break
            except AuthError as e:
                res["error"] = f"AUTH: {e}"
                con.execute("UPDATE posts SET error=? WHERE id=?", (str(e)[:500], post["id"]))
                con.commit()
                break  # no point trying the rest
            except Exception as e:  # noqa: BLE001
                log.exception("%s publish failed", plat)
                att = post["attempts"] + 1
                status = "failed" if att >= MAX_ATTEMPTS else "scheduled"
                con.execute("UPDATE posts SET attempts=?, status=?, error=? WHERE id=?",
                            (att, status, str(e)[:500], post["id"]))
                if status == "scheduled":
                    reschedule(con, post["id"], 60 * att)
                res["failed"] += 1
                res["error"] = str(e)[:200]
            con.commit()
        summary[plat] = res
    # scheduled posts left stale for >2 days (e.g. platform disabled) are skipped
    con.execute("UPDATE posts SET status='skipped' WHERE status='scheduled' AND scheduled_at<?",
                (iso(utcnow() - timedelta(days=2)),))
    con.commit()
    return summary


def export_pinterest_csv(con, settings: dict, cats: list[Category], out_dir) -> list:
    """CSV mode: every scheduled Pinterest post in the next 7 days → official bulk-upload CSV."""
    from .platforms.pinterest import export_csv
    catmap = {c.key: c for c in cats}
    pcfg = settings["platforms"]["pinterest"]
    rows, ids = [], []
    horizon = iso(utcnow() + timedelta(days=8))
    for post in con.execute("""SELECT * FROM posts WHERE platform='pinterest' AND status='scheduled'
                               AND scheduled_at<=? ORDER BY scheduled_at""", (horizon,)):
        product, cat = _ctx(con, post, catmap, cats)
        copy = copywriter.build(product, cat, settings, "pinterest", post["link"])
        when = parse_iso(post["scheduled_at"])
        floor = utcnow() + timedelta(hours=1, minutes=45 * len(rows))
        if when < floor:  # never hand Pinterest a publish date in the past
            when = floor
        rows.append({
            "Title": copy["title"],
            "Media URL": product["image_url"],
            "Pinterest board": cat.board or pcfg.get("default_board"),
            "Thumbnail": "",
            "Description": copy["description"],
            "Link": post["link"],
            "Publish date": when.strftime("%Y-%m-%dT%H:%M:%S"),
            "Keywords": ", ".join(copy["tags"]),
        })
        ids.append(post["id"])
    if not rows:
        return []
    files = export_csv(rows, out_dir, utcnow().strftime("%Y%m%d"))
    con.executemany("UPDATE posts SET status='exported', posted_at=scheduled_at WHERE id=?", [(i,) for i in ids])
    con.commit()
    return files


def collect_metrics(con, settings: dict, days: int = 60) -> dict:
    today = utcnow().date().isoformat()
    since = iso(utcnow() - timedelta(days=days))
    summary = {}
    for plat in SOCIAL:
        pcfg = settings["platforms"].get(plat, {})
        if not pcfg.get("enabled") or (plat == "pinterest" and pcfg.get("mode") == "csv"):
            continue
        posts = con.execute("""SELECT * FROM posts WHERE platform=? AND status='posted' AND remote_id IS NOT NULL
                               AND posted_at>=?""", (plat, since)).fetchall()
        if not posts:
            continue
        try:
            vals = platforms.get(plat, settings).metrics(posts)
        except Exception as e:  # noqa: BLE001
            summary[plat] = {"error": str(e)[:200]}
            continue
        for pid, mets in vals.items():
            for k, v in mets.items():
                con.execute("""INSERT INTO metrics(post_id,platform,metric,value,measured_on) VALUES(?,?,?,?,?)
                               ON CONFLICT(post_id,metric,measured_on) DO UPDATE SET value=excluded.value""",
                            (pid, plat, k, float(v or 0), today))
        summary[plat] = {"posts_measured": len(vals)}
    con.commit()
    return summary
