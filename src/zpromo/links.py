"""Referral link rules (from the Zazzle Ambassador Center / Program Agreement).

* Self-Promotion (your own store's products): share the plain URL with NO parameters.
  Zazzle's tracker credits you automatically at 35–50%.  Adding ?rf= downgrades it to 15%.
* Cross-Promotion (anyone else's products): append ?rf=<Ambassador ID>  -> 15%.
* Referral window 45 days; a newer referral only overrides after 14 days.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit, urlunsplit

PRODUCT_ID_RE = re.compile(r"-(\d{15,20})(?:[/?#]|$)")


def canonical(url: str) -> str:
    """Drop query string / fragment and force https://www.zazzle.com host."""
    p = urlsplit(url.strip())
    netloc = p.netloc or "www.zazzle.com"
    if netloc in ("zazzle.com",):
        netloc = "www.zazzle.com"
    return urlunsplit(("https", netloc, p.path, "", ""))


def product_id_from_url(url: str) -> str | None:
    m = PRODUCT_ID_RE.search(urlsplit(url).path + "?")
    return m.group(1) if m else None


def referral_link(url: str, *, is_own: bool, ambassador_id: str,
                  tracking_code: str | None = None) -> str:
    base = canonical(url)
    if is_own:
        return base  # self-promo: absolutely no parameters
    params = {"rf": ambassador_id}
    if tracking_code:
        params["tc"] = tracking_code
    return f"{base}?{urlencode(params)}"


def is_own_store(store: str | None, own_stores: list[str]) -> bool:
    if not store:
        return False
    s = store.strip().lower()
    return any(s == o.strip().lower() for o in own_stores)
