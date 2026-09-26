import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from zpromo import copywriter, harvest, planner
from zpromo.config import load_categories, load_settings
from zpromo.db import connect
from zpromo.links import canonical, product_id_from_url, referral_link
from zpromo.zazzle_feed import FeedItem, hires, parse_feed

FIX = Path(__file__).parent / "fixtures"
AID = "238439349232116915"


# ------------------------------------------------ links (money rules!)
def test_cross_promo_gets_rf():
    u = "https://www.zazzle.com/some_mug-168123456789012345?foo=1"
    assert referral_link(u, is_own=False, ambassador_id=AID) == \
        "https://www.zazzle.com/some_mug-168123456789012345?rf=238439349232116915"


def test_cross_promo_tracking_code():
    u = "https://www.zazzle.com/some_mug-168123456789012345"
    assert referral_link(u, is_own=False, ambassador_id=AID, tracking_code="pin").endswith("?rf=238439349232116915&tc=pin")


def test_self_promo_has_no_params_at_all():
    u = "https://zazzle.com/my_card-256999888777666555?rf=238439349232116915&tc=pin"
    out = referral_link(u, is_own=True, ambassador_id=AID, tracking_code="pin")
    assert out == "https://www.zazzle.com/my_card-256999888777666555"
    assert "?" not in out


def test_product_id():
    assert product_id_from_url("https://www.zazzle.com/a_b-256123456789012345?rf=1") == "256123456789012345"
    assert product_id_from_url("https://www.zazzle.com/store/abc") is None
    assert canonical("http://zazzle.com/x-1?y=2#z") == "https://www.zazzle.com/x-1"


# ------------------------------------------------ feed parsing
def test_parse_feed():
    items = parse_feed((FIX / "feed_sample.xml").read_bytes())
    assert len(items) == 2
    a, b = items
    assert a.product_id == "256123456789012345"
    assert a.url == "https://www.zazzle.com/elegant_greenery_wedding_invitation-256123456789012345"
    assert a.price == "$2.61" and a.store == "somecreatorstore"
    assert "max_dim=1000" in a.image_url
    assert b.price == "$1.99" and b.store == "ReadyCardCard"


def test_hires_leaves_unknown_urls():
    assert hires("https://x/y.jpg") == "https://x/y.jpg"


# ------------------------------------------------ config
def test_config_loads_and_seasons():
    S, C = load_settings(), load_categories()
    assert S["zazzle"]["ambassador_id"] == AID
    assert len(C) >= 30
    hal = next(c for c in C if c.key == "halloween_gifts")
    assert hal.in_season(date(2026, 10, 1)) is True
    assert hal.in_season(date(2026, 3, 1)) is False
    plan = next(c for c in C if c.key == "planners")  # wraps new year
    assert plan.in_season(date(2027, 1, 10)) is True
    assert next(c for c in C if c.key == "mugs").in_season(date(2026, 1, 1)) is None


# ------------------------------------------------ planner
def test_daily_cap_ramp():
    p = {"start_date": "2026-09-28", "ramp": [[1, 8], [3, 12], [9, 25]]}
    assert planner.daily_cap(p, date(2026, 9, 27)) == 0
    assert planner.daily_cap(p, date(2026, 9, 28)) == 8
    assert planner.daily_cap(p, date(2026, 10, 12)) == 12
    assert planner.daily_cap(p, date(2026, 12, 1)) == 25


def test_slots_respect_windows_and_gap():
    slots = planner.make_slots(10, [[0, 4], [18, 21]], 40, date(2026, 10, 1), None, random.Random(1))
    assert len(slots) == 10
    for s in slots:
        assert s.hour in (0, 1, 2, 3, 18, 19, 20)
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(slots, slots[1:])]
    assert min(gaps) >= 40


def _seed(con, cats, n_per_cat=100, n_stores=30, own=10):
    items = []
    k = 0
    for c in cats:
        for r in range(1, n_per_cat + 1):
            k += 1
            pid = f"2{k:017d}"
            it = FeedItem(pid, f"{c.qs} #{r}", f"https://www.zazzle.com/p-{pid}", "https://img/x.jpg?max_dim=1000",
                          "$9.99", f"store{k % n_stores}", "desc", "kw")
            harvest.upsert_items(con, [it], [], set())
            con.execute("INSERT INTO rankings VALUES(?,?,?,?,?)", (c.key, pid, (r - 1) // 60 + 1, r, "2026-01-01T00:00:00Z"))
    for i in range(own):
        pid = f"9{i:017d}"
        harvest.upsert_items(con, [FeedItem(pid, f"own {i}", f"https://www.zazzle.com/o-{pid}", "https://img/o.jpg",
                                            None, "readycardcard", "", "")], ["readycardcard"], set())
    con.commit()


@pytest.fixture
def env(tmp_path, monkeypatch):
    S, C = load_settings(), load_categories()
    for k in ("pinterest", "tumblr", "bluesky", "threads"):  # tests must not depend on the user's enabled flags
        S["platforms"][k]["enabled"] = True
    con = connect(tmp_path / "t.sqlite")
    _seed(con, C)
    return con, S, C


def test_plan_day_rules(env):
    con, S, C = env
    day = date(2026, 10, 20)  # pinterest week 4 -> cap 12
    n = planner.plan_day(con, "pinterest", S, C, day, random.Random(3))
    assert n == 12
    posts = con.execute("SELECT * FROM posts WHERE platform='pinterest'").fetchall()
    own = [p for p in posts if p["is_own"]]
    assert len(own) == round(12 * S["own_product_share"])
    for p in own:
        assert "?" not in p["link"]
    for p in posts:
        if not p["is_own"]:
            assert f"rf={AID}" in p["link"] and "tc=pin" in p["link"]
    # store diversity
    stores = [con.execute("SELECT store FROM products WHERE product_id=?", (p["product_id"],)).fetchone()[0]
              for p in posts if not p["is_own"]]
    assert max(stores.count(s) for s in set(stores)) <= S["max_per_store_per_day"]
    # idempotent: planning the same day again adds nothing
    assert planner.plan_day(con, "pinterest", S, C, day) == 0


def test_rank_order_and_no_repeat(env):
    con, S, C = env
    seen = set()
    for d in range(20):
        planner.plan_day(con, "tumblr", S, C, date(2026, 11, 1) + timedelta(days=d), random.Random(d))
    rows = con.execute("SELECT product_id, category FROM posts WHERE platform='tumblr' AND is_own=0").fetchall()
    ids = [r["product_id"] for r in rows]
    assert len(ids) == len(set(ids)), "never repeats a product on the same platform"
    # within each category the picked ranks are increasing (top pages first)
    for c in C:
        ranks = [con.execute("SELECT rank FROM rankings WHERE category=? AND product_id=?", (c.key, r["product_id"])).fetchone()[0]
                 for r in rows if r["category"] == c.key]
        assert ranks == sorted(ranks)
    seen |= set(ids)


def test_seasonal_categories_advance_faster(env):
    con, S, C = env
    for d in range(10):
        planner.plan_day(con, "tumblr", S, C, date(2026, 10, 5) + timedelta(days=d), random.Random(d))
    cnt = lambda k: con.execute("SELECT COUNT(*) FROM posts WHERE category=? AND platform='tumblr'", (k,)).fetchone()[0]  # noqa
    assert cnt("halloween_gifts") > cnt("valentines")


def test_copy_limits(env):
    con, S, C = env
    p = dict(con.execute("SELECT * FROM products LIMIT 1").fetchone())
    p["title"] = "A" * 300
    p["description"] = "word " * 400
    link = "https://www.zazzle.com/p-1?rf=" + AID
    for plat, field, lim in [("pinterest", "description", 500), ("threads", "text", 500), ("bluesky", "text", 300)]:
        out = copywriter.build(p, C[0], S, plat, link)
        assert len(out[field]) <= lim, plat
        assert out["title"] and len(out["title"]) <= 100
    assert link in copywriter.build(p, C[0], S, "bluesky", link)["text"]
    assert "#ad" in copywriter.build(p, C[0], S, "pinterest", link)["description"]
