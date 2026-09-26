"""Pinterest API v5.

Access tiers: *Trial* apps can only create sandbox Pins visible to yourself; public Pins need
*Standard* access (apply in developers.pinterest.com → My apps → Upgrade, with a demo video).
Until then run with `mode: csv` and upload the generated CSV via Pinterest's official
"Create Pins in bulk" tool (≤200 Pins per file, with scheduled publish dates).

Secrets: PINTEREST_APP_ID, PINTEREST_APP_SECRET, PINTEREST_REFRESH_TOKEN
Rate limits (Standard): org_write 100/min/user — we post a few per hour, far below.
"""
from __future__ import annotations

import base64
import csv
from datetime import date, timedelta
from pathlib import Path

import requests

from ..pinimage import make_pin
from .base import AuthError, check, env

API = "https://api.pinterest.com/v5"


class Pinterest:
    name = "pinterest"

    def __init__(self, settings: dict):
        self.cfg = settings["platforms"]["pinterest"]
        self.s = requests.Session()
        self._token = None
        self._boards: dict[str, str] | None = None

    # ---------- auth ----------
    def token(self) -> str:
        if self._token:
            return self._token
        app_id, secret = env("PINTEREST_APP_ID"), env("PINTEREST_APP_SECRET")
        r = requests.post(f"{API}/oauth/token",
                          auth=(app_id, secret),
                          data={"grant_type": "refresh_token", "refresh_token": env("PINTEREST_REFRESH_TOKEN")},
                          timeout=30)
        data = check(r, "pinterest")
        if "access_token" not in data:
            raise AuthError(f"pinterest token refresh failed: {data}")
        self._token = data["access_token"]
        self.s.headers["Authorization"] = f"Bearer {self._token}"
        self.refresh_token_expires_in = data.get("refresh_token_expires_in")
        return self._token

    # ---------- boards ----------
    def boards(self) -> dict[str, str]:
        if self._boards is None:
            self.token()
            self._boards, bookmark = {}, None
            while True:
                params = {"page_size": 100, **({"bookmark": bookmark} if bookmark else {})}
                data = check(self.s.get(f"{API}/boards", params=params, timeout=30), "pinterest")
                for b in data.get("items", []):
                    self._boards[b["name"].strip().lower()] = b["id"]
                bookmark = data.get("bookmark")
                if not bookmark:
                    break
        return self._boards

    def board_id(self, name: str) -> str:
        key = name.strip().lower()
        if key not in self.boards():
            data = check(self.s.post(f"{API}/boards", json={
                "name": name, "description": f"Hand-picked {name} on Zazzle — personalizable designs.",
                "privacy": "PUBLIC"}, timeout=30), "pinterest")
            self._boards[key] = data["id"]
        return self._boards[key]

    # ---------- publish ----------
    def publish(self, post, product, category, copy) -> tuple[str, str]:
        self.token()
        board = self.board_id(category.board or self.cfg.get("default_board", "Zazzle Finds"))
        img = make_pin(product["image_url"], copy["title"])
        body = {
            "board_id": board,
            "title": copy["title"],
            "description": copy["description"],
            "link": post["link"],
            "alt_text": copy["alt"],
            "media_source": {"source_type": "image_base64", "content_type": "image/jpeg",
                             "data": base64.b64encode(img).decode()},
        }
        data = check(self.s.post(f"{API}/pins", json=body, timeout=60), "pinterest")
        pid = data["id"]
        return pid, f"https://www.pinterest.com/pin/{pid}/"

    # ---------- metrics ----------
    def metrics(self, posts) -> dict[int, dict]:
        self.token()
        out = {}
        end = date.today()
        start = end - timedelta(days=89)
        for p in posts:
            r = self.s.get(f"{API}/pins/{p['remote_id']}/analytics", params={
                "start_date": start.isoformat(), "end_date": end.isoformat(),
                "metric_types": "IMPRESSION,OUTBOUND_CLICK,SAVE,PIN_CLICK"}, timeout=30)
            if r.status_code != 200:
                continue
            data = r.json().get("all", {})
            summ = data.get("summary_metrics") or data.get("lifetime_metrics") or {}
            if not summ and data.get("daily_metrics"):
                summ = {}
                for d in data["daily_metrics"]:
                    for k, v in (d.get("metrics") or {}).items():
                        summ[k] = summ.get(k, 0) + (v or 0)
            out[p["id"]] = {k.lower(): v for k, v in summ.items() if isinstance(v, (int, float))}
        return out


# ---------- CSV bulk mode ----------
CSV_HEADER = ["Title", "Media URL", "Pinterest board", "Thumbnail", "Description", "Link",
              "Publish date", "Keywords"]


def export_csv(rows: list[dict], out_dir: Path, stamp: str) -> list[Path]:
    """rows: dicts with keys matching CSV_HEADER. Splits into files of ≤200 rows."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(0, len(rows), 200):
        f = out_dir / f"pinterest_bulk_{stamp}_{i // 200 + 1}.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_HEADER)
            w.writeheader()
            w.writerows(rows[i:i + 200])
        files.append(f)
    return files
