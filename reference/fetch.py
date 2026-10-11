#!/usr/bin/env python3
"""Fetch every WP0 reference source and verify it against its pinned SHA-256.

Nothing fetched here is vendored in the repository (DECISIONS.md D-003).
Files land in reference/_fetched/<id>. Each entry in manifest.json lists one
or more URLs; the first that returns bytes matching the pinned checksum wins.
A file already present with the right checksum is not downloaded again.

HTML pages from itl.nist.gov are altered per request by Cloudflare (injected
scripts, rotating e-mail obfuscation tokens), so their bytes are not stable.
For them (normalize = "html_text", DECISIONS.md D-004) the saved file is the
page's visible text: scripts and styles removed, tags removed, entities
unescaped, whitespace collapsed to one space per line break. The checksum is of
that text, and reference/verify.py checks each quoted number against it.

Standard library only. Usage:
    python3 reference/fetch.py            # fetch and verify
    python3 reference/fetch.py --offline  # verify existing files only
"""
import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
DEST = HERE / "_fetched"
USER_AGENT = "stratum-reference-fetch/1.0 (reproducible research build)"

_DROP = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>")
_TAG = re.compile(r"(?s)<[^>]*>")


def html_text(data):
    text = _DROP.sub(" ", data.decode("latin-1"))
    text = html.unescape(_TAG.sub(" ", text))
    lines = (" ".join(line.split()) for line in text.splitlines())
    return ("\n".join(line for line in lines if line) + "\n").encode("utf-8")


def normalize(data, how):
    if how is None:
        return data
    if how == "html_text":
        return html_text(data)
    raise ValueError(f"unknown normalization {how!r}")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_entry(entry, offline):
    path = DEST / entry["id"]
    want = entry["sha256"]
    if path.exists() and sha256(path.read_bytes()) == want:
        return "ok (cached)"
    if offline:
        return "MISSING" if not path.exists() else "CHECKSUM MISMATCH"
    errors = []
    for url in entry["urls"]:
        try:
            data = normalize(download(url), entry.get("normalize"))
        except Exception as exc:  # network errors are reported, not fatal per URL
            errors.append(f"{url}: {exc}")
            continue
        got = sha256(data)
        if got == want:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return "ok (fallback)" if url != entry["urls"][0] else "ok"
        errors.append(f"{url}: sha256 {got} != pinned {want}")
    return "FAILED\n      " + "\n      ".join(errors)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="verify existing files only")
    args = ap.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    failed = 0
    for entry in manifest["sources"]:
        status = fetch_entry(entry, args.offline)
        failed += not status.startswith("ok")
        print(f"{status:<14} {entry['id']}")
    print(f"\n{len(manifest['sources']) - failed}/{len(manifest['sources'])} sources verified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
