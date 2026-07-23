#!/usr/bin/env python3
"""Read-only, incremental bookmark observation collection for Stack."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
URL_RE = re.compile(r"https?://[^\s)>\]}'\"]+")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
INTAKE_ID_RE = re.compile(r"^intake_[A-Za-z0-9_-]{16,128}$")
GITHUB_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def canonical_url(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    host = parts.hostname.lower() if parts.hostname else ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return None
    host = {"twitter.com": "x.com", "www.twitter.com": "x.com", "www.x.com": "x.com"}.get(host, host)
    path = re.sub(r"/+", "/", parts.path).rstrip("/") or "/"
    if host == "github.com":
        bits = [p for p in path.split("/") if p]
        if len(bits) >= 2:
            path = "/" + bits[0].lower() + "/" + bits[1].lower()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_KEYS]
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def opaque_id(canonical: str) -> str:
    return "intake_" + hashlib.sha256(canonical.encode()).hexdigest()[:20]


def item_from(value: object, source_id: str) -> dict | None:
    if isinstance(value, str):
        url, title, revision = value, "", ""
    elif isinstance(value, dict):
        url = value.get("canonical_url") or value.get("original_url") or value.get("url") or value.get("html_url") or value.get("link") or value.get("href") or value.get("savedURL")
        title = value.get("title") or value.get("name") or value.get("text") or value.get("savedTitle") or ""
        revision = value.get("revision") or value.get("updated_at") or value.get("pushed_at") or value.get("sha") or value.get("synced_at") or value.get("bookmarked_at") or value.get("posted_at") or value.get("timeLastActiveAt") or ""
    else:
        return None
    if not isinstance(url, str):
        return None
    canonical = canonical_url(url)
    if not canonical:
        return None
    item = {"canonical": canonical, "source_id": source_id, "title": str(title), "revision": str(revision), "raw": value}
    if isinstance(value, dict) and isinstance(value.get("intake_id"), str) and INTAKE_ID_RE.fullmatch(value["intake_id"]):
        item["intake_id"] = value["intake_id"]
    return item


def hermes_link_inbox_items(source: dict) -> tuple[list[dict], str | None]:
    """Read only the stable Hermes `links` contract from an owner-provided DB."""
    env_name = source.get("db_env", "STACK_HERMES_LINK_INBOX_DB")
    if not isinstance(env_name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", env_name):
        return [], "adapter_invalid_configuration"
    raw_path = os.environ.get(env_name)
    if not raw_path:
        return [], "not_configured"
    try:
        db_path = Path(raw_path).expanduser()
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(links)")}
            required = {"intake_id", "original_url", "canonical_url", "updated_at"}
            if not required <= columns:
                return [], "adapter_invalid_response"
            rows = connection.execute(
                "SELECT intake_id, original_url, canonical_url, updated_at FROM links "
                "WHERE intake_id IS NOT NULL AND intake_id != ''"
            )
            items = []
            for intake_id, original_url, canonical, updated_at in rows:
                if not isinstance(intake_id, str) or not INTAKE_ID_RE.fullmatch(intake_id):
                    return [], "adapter_invalid_response"
                item = item_from({"intake_id": intake_id, "original_url": original_url,
                                  "canonical_url": canonical, "updated_at": updated_at}, source["id"])
                if item:
                    items.append(item)
            return dedupe(items), None
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError):
        return [], "source_unavailable"


def read_path(path: Path, source_id: str) -> list[dict]:
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            rows: list[dict] = []
            for table in tables:
                try:
                    cursor = connection.execute(f'SELECT * FROM "{table.replace(chr(34), chr(34)*2)}"')
                    columns = [d[0] for d in cursor.description]
                    rows.extend(dict(zip(columns, row)) for row in cursor)
                except sqlite3.DatabaseError:
                    continue
            return [item for row in rows if (item := item_from(row, source_id))]
        finally:
            connection.close()
    text = path.read_text(encoding="utf-8", errors="replace")
    values: list[object] = []
    if path.suffix.lower() == ".json":
        loaded = json.loads(text)
        values = loaded if isinstance(loaded, list) else [loaded]
    elif path.suffix.lower() == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = [{"title": title, "url": url} for title, url in MARKDOWN_LINK_RE.findall(text)]
        values += [{"url": match.group(0)} for match in URL_RE.finditer(text)]
    return [item for value in values if (item := item_from(value, source_id))]


def arc_items(value: object, source_id: str) -> list[dict]:
    found: list[dict] = []
    def visit(node: object) -> None:
        if isinstance(node, dict):
            candidate = item_from(node, source_id)
            if candidate:
                found.append(candidate)
            for child in node.values(): visit(child)
        elif isinstance(node, list):
            for child in node: visit(child)
    visit(value)
    return found


def github_items(source: dict) -> tuple[list[dict], str | None]:
    if "items" in source:
        return [i for value in source["items"] if (i := item_from(value, source["id"]))], None
    try:
        result = subprocess.run(["gh", "api", "--paginate", "--slurp", "user/starred"], capture_output=True, text=True, timeout=20, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return [], "credential_unavailable"
    if result.returncode != 0:
        return [], "credential_unavailable"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "adapter_invalid_response"
    values = [item for page in payload for item in page] if isinstance(payload, list) and all(isinstance(page, list) for page in payload) else []
    public = [v for v in values if isinstance(v, dict) and not v.get("private", False)]
    return [i for value in public if (i := item_from(value, source["id"]))], None


def github_repo_slug(url: str) -> str | None:
    parts = urlsplit(url)
    bits = [part for part in parts.path.split("/") if part]
    if parts.hostname != "github.com" or len(bits) < 2 or not all(GITHUB_SEGMENT_RE.fullmatch(part) for part in bits[:2]):
        return None
    return f"{bits[0].lower()}/{bits[1].lower()}"


def github_slugs_from_value(value: object) -> list[str]:
    slugs: dict[str, None] = {}
    def visit(node: object) -> None:
        if isinstance(node, dict):
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, str):
            for match in URL_RE.finditer(node):
                slug = github_repo_slug(match.group(0))
                if slug:
                    slugs.setdefault(slug, None)
    visit(value)
    return list(slugs)


def inspect_public_github_repository(slug: str, source_id: str) -> tuple[dict | None, str | None]:
    try:
        result = subprocess.run(["gh", "api", f"repos/{slug}"], capture_output=True, text=True, timeout=20, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, "credential_unavailable"
    if result.returncode != 0:
        return None, "repository_inaccessible"
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "adapter_invalid_response"
    if not isinstance(metadata, dict):
        return None, "adapter_invalid_response"
    if metadata.get("private") is not False and metadata.get("visibility") != "public":
        return None, "public_visibility_unverified"
    allowed = {
        "html_url": metadata.get("html_url") or f"https://github.com/{slug}",
        "private": False,
        "visibility": "public",
        "updated_at": metadata.get("updated_at"),
        "pushed_at": metadata.get("pushed_at"),
        "default_branch": metadata.get("default_branch"),
        "archived": bool(metadata.get("archived", False)),
        "license": (metadata.get("license") or {}).get("spdx_id") if isinstance(metadata.get("license"), dict) else None,
    }
    return item_from(allowed, source_id), None


def github_link_items(source: dict, discovered_items: list[dict] | None = None) -> tuple[list[dict], str | None]:
    """Accept only GitHub records whose public visibility is known."""
    if "items" in source:
        values = source["items"]
    elif source.get("paths"):
        values = []
        for raw_path in source.get("paths", []):
            try:
                values.extend(item["raw"] for item in read_path(Path(raw_path).expanduser(), source["id"]))
            except OSError:
                return [], "source_unavailable"
    else:
        limit = source.get("max_items", 25)
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            return [], "adapter_invalid_configuration"
        slugs: dict[str, None] = {}
        for item in discovered_items or []:
            if item.get("source_id") == source["id"]:
                continue
            for candidate_url in [item.get("canonical", ""), *[f"https://github.com/{slug}" for slug in github_slugs_from_value(item.get("raw"))]]:
                slug = github_repo_slug(candidate_url)
                if slug:
                    slugs.setdefault(slug, None)
                if len(slugs) >= limit:
                    break
            if len(slugs) >= limit:
                break
        verified: list[dict] = []
        errors: list[str] = []
        for slug in slugs:
            item, error = inspect_public_github_repository(slug, source["id"])
            if item:
                verified.append(item)
            if error:
                errors.append(error)
        if errors and verified:
            error = "public_visibility_unverified" if set(errors) == {"public_visibility_unverified"} else "partial_repository_inaccessible"
        elif errors and all(value == "credential_unavailable" for value in errors):
            error = "credential_unavailable"
        elif errors:
            error = "repository_inaccessible"
        else:
            error = None
        return dedupe(verified), error
    public = [value for value in values if isinstance(value, dict) and (value.get("private") is False or value.get("visibility") == "public")]
    if len(public) != len(values):
        # Do not place an unverified linked repository into the ledger. A later
        # adapter may provide the public metadata through `gh api`.
        return [i for value in public if (i := item_from(value, source["id"]))], "public_visibility_unverified"
    return dedupe([i for value in public if (i := item_from(value, source["id"]))]), None


def collect(source: dict, discovered_items: list[dict] | None = None) -> tuple[list[dict], str | None]:
    adapter, source_id = source.get("adapter"), source["id"]
    # Fixture/direct-input support is deliberately adapter-neutral.  It also
    # lets an owner supply an exported snapshot without granting this command
    # access to a live client profile.
    if adapter == "github_links":
        return github_link_items(source, discovered_items)
    if adapter == "hermes_link_inbox":
        return hermes_link_inbox_items(source)
    if "items" in source:
        return dedupe([i for value in source["items"] if (i := item_from(value, source_id))]), None
    if adapter in {"github_stars", "github_links"}:
        return github_items(source)
    paths = [Path(p).expanduser() for p in source.get("paths", [])]
    try:
        if adapter == "arc_snapshot":
            items: list[dict] = []
            for path in paths:
                items.extend(arc_items(json.loads(path.read_text(encoding="utf-8")), source_id))
            return dedupe(items), None
        items = []
        for path in paths:
            items.extend(read_path(path, source_id))
        return dedupe(items), None
    except (OSError, ValueError, sqlite3.Error):
        return [], "source_unavailable"


def dedupe(items: list[dict]) -> list[dict]:
    """One snapshot yields at most one observation per canonical revision."""
    unique: dict[tuple[str, str], dict] = {}
    for item in items:
        unique.setdefault((item["canonical"], item["revision"]), item)
    return list(unique.values())


def initialise(connection: sqlite3.Connection) -> None:
    connection.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS source_cursors (source_id TEXT PRIMARY KEY, cursor_digest TEXT NOT NULL, updated_at TEXT NOT NULL, run_id TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS canonical_items (canonical TEXT PRIMARY KEY, intake_id TEXT NOT NULL, first_seen_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS observations (
      id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, canonical TEXT NOT NULL, source_revision TEXT NOT NULL,
      content_digest TEXT NOT NULL, policy_digest TEXT NOT NULL, observed_at TEXT NOT NULL, run_id TEXT NOT NULL,
      raw_json TEXT NOT NULL, UNIQUE(source_id, canonical, source_revision, content_digest, policy_digest)
    );
    """)


def safe_ledger(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    connection = sqlite3.connect(path)
    os.chmod(path, 0o600)
    initialise(connection)
    return connection


def apply_source(connection: sqlite3.Connection, source: dict, items: list[dict], policy_digest: str, run_id: str, fail_after: int | None) -> tuple[int, int]:
    cursor = digest([{k: i[k] for k in ("canonical", "revision")} for i in items])
    added = changed = 0
    with connection:
        for index, item in enumerate(items, start=1):
            content_digest = digest(item["raw"])
            exists = connection.execute("SELECT 1 FROM canonical_items WHERE canonical=?", (item["canonical"],)).fetchone()
            connection.execute("INSERT OR IGNORE INTO canonical_items VALUES (?, ?, ?)", (item["canonical"], item.get("intake_id", opaque_id(item["canonical"])), now()))
            before = connection.total_changes
            connection.execute("""INSERT OR IGNORE INTO observations (source_id, canonical, source_revision, content_digest, policy_digest, observed_at, run_id, raw_json)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (source["id"], item["canonical"], item["revision"], content_digest, policy_digest, now(), run_id, json.dumps(item["raw"], default=str)))
            if connection.total_changes > before:
                added += 1
                changed += 0 if exists else 1
            if fail_after is not None and index >= fail_after:
                raise RuntimeError("injected crash before cursor commit")
        connection.execute("INSERT INTO source_cursors VALUES (?, ?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET cursor_digest=excluded.cursor_digest, updated_at=excluded.updated_at, run_id=excluded.run_id", (source["id"], cursor, now(), run_id))
    return added, changed


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default=str(Path(__file__).parents[1] / "config/bookmark-sources.json"))
    parser.add_argument("--policy", default=str(Path(__file__).parents[1] / "config/bookmark-fetch-policy.json"))
    parser.add_argument("--ledger", default=str(Path.home() / ".local/state/stack/bookmark-intake.sqlite"))
    parser.add_argument("--out", help="write redacted JSON receipt")
    parser.add_argument("--apply", action="store_true", help="durably record observations and advance cursors")
    parser.add_argument("--fail-after-observations", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    sources_doc, policy_doc = json.loads(Path(args.sources).read_text()), json.loads(Path(args.policy).read_text())
    policy_digest, run_id = digest(policy_doc), "run_" + hashlib.sha256(os.urandom(16)).hexdigest()[:16]
    receipt = {"schema_version": 1, "run_id": run_id, "mode": "apply" if args.apply else "dry-run", "policy_digest": policy_digest, "sources": [], "complete": True}
    connection = safe_ledger(Path(args.ledger)) if args.apply else None
    discovered_items: list[dict] = []
    try:
        for source in sources_doc.get("sources", []):
            if not source.get("enabled", True): continue
            items, error = collect(source, discovered_items)
            if source.get("adapter") not in {"github_stars", "github_links"}:
                discovered_items.extend(items)
            row = {"source_id": source["id"], "status": "ok", "observed": len(items), "recorded": 0, "new_canonical": 0}
            if error:
                row.update(status=error)
                receipt["complete"] = False
            if items and connection:
                try:
                    row["recorded"], row["new_canonical"] = apply_source(connection, source, items, policy_digest, run_id, args.fail_after_observations)
                except RuntimeError:
                    row["status"] = "transaction_rolled_back"; receipt["complete"] = False
            receipt["sources"].append(row)
    finally:
        if connection: connection.close()
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out: Path(args.out).write_text(encoded, encoding="utf-8")
    else: sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
