"""End-to-end with fake Zazzle feed + fake platforms (no network)."""
import csv
from datetime import timedelta

import pytest

from zpromo import harvest, planner, publisher, report, sales, site
from zpromo import platforms as P
from zpromo.config import load_categories, load_settings
from zpromo.db import connect, iso, utcnow
from zpromo.platforms.bluesky import Bluesky
from zpromo.zazzle_feed import FeedItem


class FakeFeed:
    calls = 0

    def search(self, qs, page, page_size=60, sort_period=30):
        FakeFeed.calls += 1
        if page > 3:
            return []
        base = abs(hash(qs)) % 10**6
        return [FeedItem(f"2{base:06d}{page:03d}{i:08d}", f"{qs} item p{page} #{i}",
                         f"https://www.zazzle.com/x-2{base:06d}{page:03d}{i:08d}", "https://rlv.zcache.com/a.jpg?max_dim=1000",
                         "$5.00", f"creator{i % 25}", "nice design", "tag1, tag2") for i in range(page_size)]

    def store(self, store, page, page_size=100):
        if page > 1:
            return []
        return [FeedItem(f"9{abs(hash(store)) % 10**6:06d}{i:011d}", f"{store} own #{i}",
                         f"https://www.zazzle.com/own-9{abs(hash(store)) % 10**6:06d}{i:011d}", "https://rlv.zcache.com/o.jpg",
                         "$3.00", None, "mine", "") for i in range(20)]


class FakePlatform:
    published = []

    def __init__(self, name):
        self.name = name

    def publish(self, post, product, category, copy):
        FakePlatform.published.append((self.name, post["link"], copy))
        return f"{self.name}-{post['id']}", f"https://example/{self.name}/{post['id']}"

    def metrics(self, posts):
        return {p["id"]: {"impression": 100, "outbound_click": 3} if self.name == "pinterest" else {"likes": 2}
                for p in posts}


@pytest.fixture
def world(tmp_path, monkeypatch):
    S, C = load_settings(), load_categories()
    S["zazzle"]["pages_per_category"] = 4
    S["zazzle"]["page_size"] = 20
    S["zazzle"]["harvest_pages_per_run"] = 1000
    today = utcnow().date()
    for k in ("pinterest", "tumblr", "bluesky", "threads"):
        S["platforms"][k]["start_date"] = (today - timedelta(days=30)).isoformat()
        S["platforms"][k]["windows_utc"] = [[0, 24]]
    monkeypatch.setattr(P, "get", lambda name, s: FakePlatform(name))
    con = connect(tmp_path / "s.sqlite")
    return con, S, C, tmp_path


def test_full_cycle(world, monkeypatch):
    con, S, C, tmp = world
    feed = FakeFeed()
    n_own = harvest.harvest_own_stores(con, feed, S)
    assert n_own == 40
    res = harvest.run_harvest(con, feed, C, S, utcnow().date())
    assert res["errors"] == 0
    # 3 pages have items, page 4 is empty -> marked empty, not retried
    assert con.execute("SELECT COUNT(*) FROM harvest_pages WHERE status='empty'").fetchone()[0] == len(C)
    assert harvest.pages_due(con, C, S, utcnow().date()) == []

    out = planner.plan(con, S, C)
    assert out["tumblr"] > 0
    # force everything due now
    con.execute("UPDATE posts SET scheduled_at=?", (iso(utcnow() - timedelta(minutes=1)),))
    S["platforms"]["pinterest"]["mode"] = "api"
    summ = publisher.run_posts(con, S, C, per_run=50)
    assert all(v["posted"] > 0 for v in summ.values()), summ
    for plat, link, copy in FakePlatform.published:
        if "own-9" in link:
            assert "?" not in link
        else:
            assert "rf=238439349232116915" in link

    m = publisher.collect_metrics(con, S)
    assert m["pinterest"]["posts_measured"] > 0

    st = report.build_stats(con, S, C)
    assert st["platforms"]["pinterest"]["ctr_pct"] == 3.0
    md = report.to_markdown(st)
    assert "每日報告" in md
    out_dir = tmp / "site"
    site.build(con, S, C, report.redact_money(st), out_dir)
    idx = (out_dir / "index.html").read_text()
    assert "From my own shops" in idx
    page = (out_dir / "c" / f"{C[0].key}.html").read_text()
    assert "rf=238439349232116915&amp;tc=site" in page
    assert (out_dir / "report" / "index.html").exists()


def test_pinterest_csv_export(world):
    con, S, C, tmp = world
    feed = FakeFeed()
    harvest.run_harvest(con, feed, C, S, utcnow().date())
    S["platforms"]["pinterest"]["mode"] = "csv"
    planner.plan(con, S, C)
    files = publisher.export_pinterest_csv(con, S, C, tmp / "exp")
    assert files
    rows = list(csv.DictReader(open(files[0], encoding="utf-8")))
    assert len(rows) <= 200
    assert rows[0]["Pinterest board"] and rows[0]["Link"].startswith("https://www.zazzle.com/")
    assert len(rows[0]["Description"]) <= 500
    # exported posts are not exported twice
    assert publisher.export_pinterest_csv(con, S, C, tmp / "exp2") == []
    # csv posts are not sent via API
    assert "pinterest" not in publisher.run_posts(con, S, C)


def test_encrypted_sales_import(world, monkeypatch):
    con, S, C, tmp = world
    from zpromo.crypto import encrypt_file, keygen
    monkeypatch.setenv("ZPROMO_KEY", keygen())
    d = tmp / "rep"
    d.mkdir()
    f = d / "referrals.csv"
    f.write_text("Date,Product Title,Product ID,Sale Amount,Referral Commission,Type\n"
                 "09/20/2026,Greenery Invite,256123456789012345,$120.00,$18.00,Cross-Promotion\n"
                 "09/21/2026,My Card,256999888777666555,$40.00,$20.00,Self-Promotion\n", encoding="utf-8")
    encrypt_file(f)
    f.unlink()
    r = sales.import_dir(con, d)
    assert r == {"files": 1, "new_rows": 2}
    assert sales.import_dir(con, d)["new_rows"] == 0  # idempotent
    rows = {x["product_id"]: dict(x) for x in con.execute("SELECT * FROM sales")}
    assert rows["256123456789012345"]["commission"] == 18.0
    assert rows["256123456789012345"]["kind"] == "cross"
    assert rows["256999888777666555"]["kind"] == "self"
    assert rows["256123456789012345"]["sale_date"] == "2026-09-20"
    st = report.redact_money(report.build_stats(con, S, C))
    assert all(v["commission"] == "—" for v in st["sales_30d"].values())


def test_bluesky_facet_bytes():
    text = "Café ✨ design\nhttps://www.zazzle.com/x-1?rf=2"
    f = Bluesky.link_facet(text, "https://www.zazzle.com/x-1?rf=2")[0]
    b = text.encode()
    assert b[f["index"]["byteStart"]:f["index"]["byteEnd"]].decode() == "https://www.zazzle.com/x-1?rf=2"
