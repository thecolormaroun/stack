#!/usr/bin/env python3
"""Apply the reviewed U3 skill layout migration safely and repeatably.

The migration record is deliberately data-first: every callable capability has
one source and one destination.  This tool validates the complete record and
all collisions before it moves a single directory.  ``--write-migration`` is
only the one-time, deterministic bootstrap for the checked-in reviewed map.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "registry/migrations/2026-07-23-skill-layout.json"
IMPORT_PROVIDERS = {"matt", "david", "impeccable", "studio", "ui", "emil", "taste-skill-suite"}


class LayoutError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LayoutError(f"{path}: expected a JSON object")
    return value


def destination_for(manifest: dict[str, Any], source: str) -> str:
    """Return the approved physical destination without changing its identity."""
    provider = manifest["ownership"]["provider"]
    family = manifest["family"]
    source_dir = Path(source).parent
    parts = source_dir.parts
    if provider in IMPORT_PROVIDERS:
        provider_dir = provider
        if provider == "taste-skill-suite":
            provider_dir = "taste-skill-suite"
        # Preserve the collection's inside layout, but remove its old root.
        old_root = {"matt": "matt", "david": "david", "impeccable": "impeccable", "studio": "studio", "ui": "ui-skills", "emil": "emil-design-eng", "taste-skill-suite": "taste-skill-suite"}[provider]
        relative = Path(*parts[2:]) if len(parts) > 2 and parts[1] == old_root else Path(parts[-1])
        return (Path("skills/imported") / provider_dir / relative / "SKILL.md").as_posix()
    # Stack-owned collections remain collections, including CDO and CPO.
    relative = Path(*parts[1:])
    if source.startswith("skills/orchestration/"):
        return source
    return (Path("skills") / family / relative / "SKILL.md").as_posix()


def build_migration(root: Path) -> dict[str, Any]:
    moves: list[dict[str, str]] = []
    for manifest_path in sorted((root / "skills").glob("**/capability.json")):
        manifest = read_json(manifest_path)
        source = manifest["source"]["skill_path"]
        moves.append({
            "canonical_name": manifest["canonical_name"],
            "source": source,
            "destination": destination_for(manifest, source),
        })
    moves.sort(key=lambda item: item["canonical_name"])
    return {
        "schema_version": 1,
        "id": "2026-07-23-skill-layout",
        "purpose": "U3 reviewed physical skill layout; canonical capability names do not change.",
        "moves": moves,
    }


def load_migration(path: Path) -> dict[str, Any]:
    migration = read_json(path)
    if migration.get("schema_version") != 1 or migration.get("id") != "2026-07-23-skill-layout":
        raise LayoutError("unsupported layout migration")
    moves = migration.get("moves")
    if not isinstance(moves, list) or not moves:
        raise LayoutError("migration must contain a non-empty moves list")
    seen_sources: set[str] = set(); seen_destinations: set[str] = set(); seen_names: set[str] = set()
    for move in moves:
        if not isinstance(move, dict) or set(move) != {"canonical_name", "source", "destination"}:
            raise LayoutError("each migration move must contain canonical_name, source, destination")
        name, source, destination = (move[key] for key in ("canonical_name", "source", "destination"))
        if not all(isinstance(value, str) and value.startswith("skills/") for value in (source, destination)) or not source.endswith("/SKILL.md") or not destination.endswith("/SKILL.md"):
            raise LayoutError(f"invalid skill path for {name!r}")
        if source in seen_sources or destination in seen_destinations or name in seen_names:
            raise LayoutError(f"duplicate migration source, destination, or canonical name: {name}")
        seen_sources.add(source); seen_destinations.add(destination); seen_names.add(name)
    return migration


def preflight(root: Path, migration: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    moves = migration["moves"]
    source_set = {move["source"] for move in moves}
    current: list[dict[str, str]] = []; complete: list[dict[str, str]] = []
    for move in moves:
        source, destination = root / move["source"], root / move["destination"]
        source_manifest = source.with_name("capability.json")
        destination_manifest = destination.with_name("capability.json")
        if source == destination:
            if not source.is_file() or not source_manifest.is_file():
                raise LayoutError(f"{move['source']}: missing no-op source or manifest")
            manifest = read_json(source_manifest)
            if manifest.get("canonical_name") != move["canonical_name"]:
                raise LayoutError(f"{move['source']}: source manifest does not match migration")
            complete.append(move)
            continue
        if source.is_file():
            if not source_manifest.is_file():
                raise LayoutError(f"{move['source']}: missing manifest")
            manifest = read_json(source_manifest)
            if manifest.get("canonical_name") != move["canonical_name"] or manifest.get("source", {}).get("skill_path") != move["source"]:
                raise LayoutError(f"{move['source']}: source manifest does not match migration")
            if destination.exists() and move["destination"] not in source_set:
                raise LayoutError(f"destination collision: {move['destination']}")
            current.append(move)
        elif destination.is_file():
            if not destination_manifest.is_file():
                raise LayoutError(f"{move['destination']}: missing manifest after prior apply")
            manifest = read_json(destination_manifest)
            transitional_source = "skills/imported/impeccable/" + Path(move["destination"]).parent.name + "/SKILL.md"
            allowed_sources = {move["source"], move["destination"], transitional_source}
            if manifest.get("canonical_name") != move["canonical_name"] or manifest.get("source", {}).get("skill_path") not in allowed_sources:
                raise LayoutError(f"{move['destination']}: destination manifest does not match migration")
            (current if manifest.get("source", {}).get("skill_path") == move["source"] else complete).append(move)
        else:
            raise LayoutError(f"missing both source and destination for {move['canonical_name']}")
    # Moving a collection root subsumes its listed children.
    roots = [move for move in current if (root / move["source"]).is_file() and not any(move["source"].startswith(other["source"].removesuffix("/SKILL.md") + "/") for other in current if other is not move)]
    return roots, complete


def rewrite_manifest_paths(root: Path, migration: dict[str, Any]) -> None:
    destinations = {move["canonical_name"]: move["destination"] for move in migration["moves"]}
    for path in sorted((root / "skills").glob("**/capability.json")):
        manifest = read_json(path); destination = destinations.get(manifest.get("canonical_name"))
        if destination is None:
            continue
        if manifest["source"]["skill_path"] != destination or manifest["ownership"]["source_path"] != destination:
            manifest["source"]["skill_path"] = destination
            manifest["ownership"]["source_path"] = destination
            path.write_text(canonical_json(manifest), encoding="utf-8")


def apply(root: Path, migration: dict[str, Any]) -> int:
    # Recover only the tool's immediately preceding provider placement when a
    # final provider namespace correction is part of the reviewed map.
    for move in migration["moves"]:
        source, destination = root / move["source"], root / move["destination"]
        previous = root / "skills/imported/impeccable" / destination.parent.name / "SKILL.md"
        if not source.exists() and not destination.exists() and previous.exists() and "skills/imported/taste-skill-suite/" in move["destination"]:
            destination.parent.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(previous.parent), str(destination.parent))
    roots, _ = preflight(root, migration)
    for move in roots:
        source_dir = (root / move["source"]).parent
        destination_dir = (root / move["destination"]).parent
        destination_dir.parent.mkdir(parents=True, exist_ok=True)
        if destination_dir.exists():
            raise LayoutError(f"destination directory collision: {destination_dir.relative_to(root)}")
        shutil.move(str(source_dir), str(destination_dir))
    rewrite_manifest_paths(root, migration)
    # A second complete preflight proves a re-run is a no-op and detects partial moves.
    followup_roots, _ = preflight(root, migration)
    if followup_roots:
        raise LayoutError("post-apply migration still has pending moves")
    return len(roots)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--migration", type=Path, default=MIGRATION_PATH)
    parser.add_argument("--write-migration", action="store_true", help="write the deterministic reviewed map from the current manifested estate")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(); root = args.root.resolve(); path = args.migration.resolve()
    if args.dry_run == args.apply:
        parser.error("choose exactly one of --dry-run or --apply")
    try:
        if args.write_migration:
            if path.exists():
                raise LayoutError(f"refusing to overwrite existing migration: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(canonical_json(build_migration(root)), encoding="utf-8")
        migration = load_migration(path)
        if args.dry_run:
            roots, complete = preflight(root, migration)
            print(json.dumps({"pending_root_moves": len(roots), "complete_capabilities": len(complete), "capabilities": len(migration["moves"])}, sort_keys=True))
        else:
            print(f"applied {apply(root, migration)} physical skill-directory moves for {len(migration['moves'])} capabilities")
        return 0
    except (LayoutError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
