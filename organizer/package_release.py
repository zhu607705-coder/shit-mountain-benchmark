#!/usr/bin/env python3
"""Create an organizer archive with a file hash manifest, never a hidden test claim."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"__pycache__", ".git", ".DS_Store", ".local", ".venv", "reports", "submissions", "workspaces"}


def files():
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and not any(x in EXCLUDED for x in p.parts)
                  and p.suffix != ".pyc" and not p.name.startswith(".env") and not p.name.endswith(".local.json")
                  and p != ROOT / "MANIFEST.sha256.json")


def main():
    for group, prefix in (("reasoning", "R"), ("code", "C"), ("frontend", "F")):
        ids = tuple(prefix + str(i) for i in range(1, 5))
        for name in ids:
            if not (ROOT / group / name / "PROMPT.md").is_file():
                raise SystemExit(f"missing prompt: {group}/{name}")
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files()}
    manifest_path = ROOT / "MANIFEST.sha256.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    target = ROOT.parent / (ROOT.name + ".zip")
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for p in [*files(), manifest_path]:
            archive.write(p, Path(ROOT.name) / p.relative_to(ROOT))
    with ZipFile(target) as archive:
        bad = archive.testzip()
        if bad:
            raise SystemExit(f"bad archive member: {bad}")
        count = len(archive.namelist())
    print(json.dumps({"archive": str(target), "files": count, "bytes": target.stat().st_size,
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
