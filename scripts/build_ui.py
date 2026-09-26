#!/usr/bin/env python3
"""Stamp the browser entry point and record its deterministic asset identity."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
META_NAME = "arena-ui-build"
PLACEHOLDER = "__ARENA_UI_BUILD__"
META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
HEAD_END = re.compile(r"</head\s*>", re.IGNORECASE)


def _attribute(tag, name):
    return re.search(
        r"(?<![\w:-])" + re.escape(name)
        + r"\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
        tag,
        re.IGNORECASE,
    )


def stamp_index(source, build_id):
    """Replace only the stamp value, preserving the rest of the HTML bytes."""
    matches = []
    for match in META_TAG.finditer(source):
        name = _attribute(match.group(), "name")
        if name and next(value for value in name.groups() if value is not None).lower() == META_NAME:
            matches.append(match)
    if len(matches) > 1:
        raise ValueError("index.html contains duplicate arena-ui-build stamps")
    if not matches:
        head_end = HEAD_END.search(source)
        if not head_end:
            raise ValueError("index.html must contain </head> for the UI build stamp")
        return source[:head_end.start()] + f'<meta name="{META_NAME}" content="{build_id}">' + source[head_end.start():]
    match = matches[0]
    tag = match.group()
    content = _attribute(tag, "content")
    if content:
        group = next(index for index in (1, 2, 3) if content.group(index) is not None)
        start, end = content.span(group)
        tag = tag[:start] + build_id + tag[end:]
    else:
        insertion = len(tag) - (2 if tag.endswith("/>") else 1)
        tag = tag[:insertion] + f' content="{build_id}"' + tag[insertion:]
    return source[:match.start()] + tag + source[match.end():]


def _assets(web_root):
    paths = []
    for path in web_root.rglob("*"):
        relative = path.relative_to(web_root)
        name = path.name.lower()
        is_test = (
            any(part.lower() in {"tests", "__tests__"} for part in relative.parts)
            or name.startswith(("test_", "test.", "test-"))
            or ".test." in name or ".spec." in name
        )
        is_asset = (
            relative.as_posix() == "index.html"
            or path.suffix.lower() in {".js", ".css"}
            or (len(relative.parts) == 2 and relative.parts[0] == "icons" and path.suffix.lower() == ".svg")
        )
        if is_asset and not is_test:
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != web_root.parent):
                raise ValueError(f"UI asset must not be a symlink: {relative}")
            if path.is_file():
                paths.append(path)
    if web_root / "index.html" not in paths:
        raise ValueError("UI entry point index.html is missing")
    return sorted(paths, key=lambda path: path.relative_to(web_root).as_posix())


def compute_manifest(web_root, version):
    """Compute identity without writing; the HTML stamp is not self-referential."""
    web_root = Path(web_root).resolve()
    if not isinstance(version, str) or not version.strip():
        raise ValueError("registry version must be a nonempty string")
    assets = {}
    for path in _assets(web_root):
        data = path.read_bytes()
        if path.name == "index.html" and path.parent == web_root:
            data = stamp_index(data.decode("utf-8"), PLACEHOLDER).encode("utf-8")
        assets[path.relative_to(web_root).as_posix()] = hashlib.sha256(data).hexdigest()
    identity = {"schema": 1, "version": version, "assets": assets}
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"schema": 1, "id": hashlib.sha256(encoded).hexdigest(), "version": version, "assets": assets}


def _atomic_write(path, data):
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
        os.chmod(name, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def build(web_root, version, *, check=False):
    """Write a matching manifest/stamp, or reject any drift without modifying files."""
    web_root = Path(web_root).resolve()
    manifest = compute_manifest(web_root, version)
    index = web_root / "index.html"
    source = index.read_bytes().decode("utf-8")
    stamped = stamp_index(source, manifest["id"])
    manifest_path = web_root / "build.txt"
    if check:
        try:
            saved = json.loads(manifest_path.read_bytes())
        except (OSError, ValueError) as error:
            raise ValueError("UI build manifest is missing or invalid; run scripts/build_ui.py") from error
        if saved != manifest or source != stamped:
            raise ValueError("UI assets or stamp have changed; run scripts/build_ui.py")
    else:
        if source != stamped:
            _atomic_write(index, stamped.encode("utf-8"))
        encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if not manifest_path.exists() or manifest_path.read_bytes() != encoded:
            _atomic_write(manifest_path, encoded)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="reject stale assets/HTML/manifest without writing")
    parser.add_argument("--web-root", type=Path, default=ROOT / "arena" / "web")
    parser.add_argument("--registry", type=Path, default=ROOT / "benchmark.json")
    args = parser.parse_args(argv)
    try:
        registry = json.loads(args.registry.read_bytes())
        manifest = build(args.web_root, registry.get("version"), check=args.check)
    except (OSError, UnicodeError, ValueError, AttributeError) as error:
        print(f"UI build failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "verified" if args.check else "built", "id": manifest["id"], "version": manifest["version"], "assets": len(manifest["assets"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
