"""Pinterest board specs: name + keyword-rich description + suggested cover, derived from categories.

Several categories may share one board (e.g. Christmas cards + ornaments + gifts → "Christmas Cards & Gifts");
the description merges all their keywords.  Descriptions follow Pinterest SEO advice: natural sentence,
main keywords first, ≤500 chars.
"""
from __future__ import annotations

from .config import Category


def board_name(cat: Category, settings: dict) -> str:
    return cat.board or settings["platforms"]["pinterest"].get("default_board", "Zazzle Gift Finds")


def board_specs(cats: list[Category], settings: dict) -> dict[str, dict]:
    specs: dict[str, dict] = {}
    for c in cats:
        name = board_name(c, settings)
        s = specs.setdefault(name, {"name": name, "categories": [], "topics": [], "tags": [], "custom": None})
        s["categories"].append(c.key)
        s["topics"].append(c.qs)
        s["tags"] += [str(t) for t in c.tags if str(t) not in s["tags"]]
        if getattr(c, "board_desc", None):
            s["custom"] = c.board_desc
    for s in specs.values():
        topics = ", ".join(dict.fromkeys(s["topics"]))
        desc = s["custom"] or (
            f"{s['name']}: the best-selling, fully personalizable {topics} on Zazzle, hand-picked from "
            f"independent designers. Add your own names, photos, dates and colors to make them yours. "
            f"Updated every week with trending designs and gift ideas.")
        s["description"] = desc[:500]
        s["keywords"] = ", ".join(s["tags"][:10])
    return specs


def cover_suggestions(con, specs: dict[str, dict]) -> dict[str, dict]:
    """Best candidate for each board's cover: your own top product if the board has one, else rank #1."""
    out = {}
    for name, s in specs.items():
        ph = ",".join("?" * len(s["categories"]))
        row = con.execute(
            f"""SELECT p.title, p.image_url, p.url, p.is_own, MIN(r.rank) rk FROM rankings r
                JOIN products p USING(product_id) WHERE r.category IN ({ph}) AND p.alive=1 AND p.image_url IS NOT NULL
                GROUP BY p.product_id ORDER BY p.is_own DESC, rk LIMIT 1""", s["categories"]).fetchone()
        if row:
            out[name] = dict(row)
    return out
