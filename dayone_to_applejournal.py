#!/usr/bin/env python3
"""Import a Day One JSON export into Apple Journal through journal-cli."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

__version__ = "1.0.0"

IMAGE_LINK_RE = re.compile(r"!\[[^\]]*\]\([^\n)]*\)")
H1_RE = re.compile(r"^#\s+(.+?)\s*$")
MEDIA_EXTENSIONS = ("jpg", "jpeg", "png", "heic", "gif", "tif", "tiff", "webp", "mov", "mp4", "m4v")


@dataclass(frozen=True)
class PreparedEntry:
    source_id: str
    title: str
    body: str
    date: str
    media: tuple[Path, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Day One JSON into Apple Journal. Dry-run is the default."
    )
    parser.add_argument("json_export", type=Path, help="Day One JSON export file")
    parser.add_argument("--journal", required=True, help="Existing Apple Journal journal name")
    parser.add_argument("--live", action="store_true", help="Perform writes (otherwise preview only)")
    parser.add_argument("--ledger", type=Path, help="UUID ledger path (default: beside the JSON export)")
    parser.add_argument("--journal-cli", default="journal-cli", help="journal-cli executable or path")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue after an entry fails")
    parser.add_argument("--limit", type=int, help="Process at most this many eligible entries")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args()


def load_entries(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read Day One JSON: {exc}") from exc
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise SystemExit("Expected a JSON object with an 'entries' list (or a top-level list).")
    return [entry for entry in entries if isinstance(entry, dict)]


def default_ledger(export: Path) -> Path:
    return export.with_name(f".{export.stem}.apple-journal-ledger.jsonl")


def read_ledger(path: Path, journal: str) -> set[str]:
    seen: set[str] = set()
    if not path.exists():
        return seen
    number = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("journal") == journal and record.get("source_id"):
                    seen.add(str(record["source_id"]))
    except (OSError, json.JSONDecodeError) as exc:
        location = f" near line {number}" if number else ""
        raise SystemExit(f"Ledger is unreadable{location}: {exc}") from exc
    return seen


def append_ledger(path: Path, entry: PreparedEntry, journal: str, export: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "source_id": entry.source_id,
        "journal": journal,
        "source": str(export.resolve()),
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def source_id(entry: dict[str, Any]) -> str:
    for key in ("uuid", "id", "entryUUID"):
        value = entry.get(key)
        if value:
            return str(value)
    stable = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()


def split_title_body(text: str) -> tuple[str, str]:
    text = IMAGE_LINK_RE.sub("", text.replace("\r\n", "\n")).strip()
    lines = text.splitlines()
    title = ""
    if lines:
        match = H1_RE.match(lines[0])
        if match:
            title = match.group(1).strip()
            lines = lines[1:]
    body = "\n".join(lines).strip()
    return title, body


def entry_date(entry: dict[str, Any]) -> str:
    raw = entry.get("creationDate") or entry.get("date") or entry.get("modifiedDate")
    if not raw:
        raise ValueError("missing creation date")
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(raw))
    if not match:
        raise ValueError(f"unsupported date: {raw!r}")
    return match.group(1)


def media_candidates(export_dir: Path, photo: dict[str, Any]) -> Iterable[Path]:
    photos_dir = export_dir / "photos"
    for key in ("filename", "fileName", "path"):
        value = photo.get(key)
        if value:
            candidate = Path(str(value))
            yield candidate if candidate.is_absolute() else export_dir / candidate
            yield photos_dir / candidate.name
    token = photo.get("md5") or photo.get("identifier") or photo.get("uuid")
    if token:
        declared = str(photo.get("type") or photo.get("extension") or "").lower().lstrip(".")
        if declared:
            yield photos_dir / f"{token}.{declared}"
        for extension in MEDIA_EXTENSIONS:
            yield photos_dir / f"{token}.{extension}"


def resolve_media(export_dir: Path, entry: dict[str, Any]) -> tuple[Path, ...]:
    found: list[Path] = []
    records: list[Any] = []
    for field in ("photos", "videos", "media"):
        value = entry.get(field)
        if isinstance(value, list):
            records.extend(value)
    for record in records:
        if not isinstance(record, dict):
            continue
        for candidate in media_candidates(export_dir, record):
            if candidate.is_file():
                resolved = candidate.resolve()
                if resolved not in found:
                    found.append(resolved)
                break
    return tuple(found)


def prepare(entry: dict[str, Any], export_dir: Path) -> PreparedEntry:
    text = str(entry.get("text") or "")
    title, body = split_title_body(text)
    media = resolve_media(export_dir, entry)
    return PreparedEntry(source_id(entry), title, body, entry_date(entry), media)


def command_for(item: PreparedEntry, args: argparse.Namespace, body_file: Path) -> list[str]:
    command = [args.journal_cli, "write", "--journal", args.journal, "--date", item.date, "--markdown"]
    if args.live:
        command.append("--live")
    else:
        command.append("--dry-run")
    if item.title:
        command.extend(["--title", item.title])
    if item.body:
        command.extend(["--body-file", str(body_file)])
    if item.media:
        command.append("--media")
        command.extend(str(path) for path in item.media)
    return command


def preflight(args: argparse.Namespace) -> None:
    if shutil.which(args.journal_cli) is None and not Path(args.journal_cli).is_file():
        raise SystemExit(f"Cannot find {args.journal_cli!r}. Install journal-cli first.")
    if args.live:
        result = subprocess.run([args.journal_cli, "doctor"], check=False)
        if result.returncode:
            raise SystemExit("journal-cli doctor reported a setup problem; no entries were written.")


def main() -> int:
    args = parse_args()
    export = args.json_export.expanduser().resolve()
    if not export.is_file():
        raise SystemExit(f"JSON export not found: {export}")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    ledger = (args.ledger or default_ledger(export)).expanduser().resolve()
    entries = load_entries(export)
    seen = read_ledger(ledger, args.journal)
    preflight(args)

    counts = {"eligible": 0, "imported": 0, "duplicate": 0, "empty": 0, "failed": 0}
    mode = "LIVE" if args.live else "DRY RUN"
    print(f"{mode}: {len(entries)} source entries -> {args.journal!r}")
    print(f"Ledger: {ledger}")

    for index, raw in enumerate(entries, 1):
        try:
            item = prepare(raw, export.parent)
            if item.source_id in seen:
                counts["duplicate"] += 1
                continue
            if not (item.title or item.body or item.media):
                counts["empty"] += 1
                continue
            if args.limit is not None and counts["eligible"] >= args.limit:
                break
            counts["eligible"] += 1
            label = item.title or (item.body.splitlines()[0][:60] if item.body else "media-only entry")
            print(f"[{index}/{len(entries)}] {item.date} {label}")
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as temp:
                temp.write(item.body)
                body_path = Path(temp.name)
            try:
                result = subprocess.run(command_for(item, args, body_path), check=False)
            finally:
                body_path.unlink(missing_ok=True)
            if result.returncode:
                raise RuntimeError(f"journal-cli exited with status {result.returncode}")
            if args.live:
                append_ledger(ledger, item, args.journal, export)
                seen.add(item.source_id)
                counts["imported"] += 1
        except (OSError, ValueError, RuntimeError) as exc:
            counts["failed"] += 1
            print(f"  ERROR: {exc}", file=sys.stderr)
            if not args.continue_on_error:
                break

    print("\nSummary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if not args.live:
        print("No Apple Journal entries or ledger records were created.")
    elif counts["imported"]:
        print(f"Resume safely by rerunning the same command; completed UUIDs are in {ledger}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
