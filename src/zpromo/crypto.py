"""Encrypt private data at rest so the repo can stay public (free Actions minutes + Pages).

* state/zpromo.sqlite is packed to state/zpromo.sqlite.enc before it is pushed to the
  `state` branch, and unpacked at the start of every run.
* Zazzle earnings CSVs are encrypted locally (`python -m zpromo.cli encrypt-file x.csv`)
  and committed as data/zazzle_reports/x.csv.enc — nobody else can read your sales.
Key: repo secret ZPROMO_KEY (generate once with `python -m zpromo.cli keygen`).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from nacl import secret, utils


def _box() -> secret.SecretBox:
    k = os.environ.get("ZPROMO_KEY")
    if not k:
        raise RuntimeError("ZPROMO_KEY not set")
    return secret.SecretBox(base64.b64decode(k))


def keygen() -> str:
    return base64.b64encode(utils.random(secret.SecretBox.KEY_SIZE)).decode()


def encrypt_bytes(data: bytes) -> bytes:
    return _box().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return _box().decrypt(data)


def encrypt_file(src: Path, dst: Path | None = None) -> Path:
    dst = dst or src.with_name(src.name + ".enc")
    dst.write_bytes(encrypt_bytes(src.read_bytes()))
    return dst


def decrypt_file(src: Path, dst: Path) -> Path:
    dst.write_bytes(decrypt_bytes(src.read_bytes()))
    return dst
