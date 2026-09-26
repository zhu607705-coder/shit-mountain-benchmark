#!/usr/bin/env python3
"""Export all twelve public tasks by allowlist; no solutions or organizer code."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
from cli import TASKS, task_files


def main():
    target = ROOT.parent / "shit-mountain-benchmark-contestant-v0.1.zip"
    manifest = {}
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        intro = ("# 屎山 Bug 挑战赛参赛包\n\n统一12题：R1–R4、C1–C4、F1–F4。每题从tasks/<ID>/PROMPT.md开始。\n\n"
                 "C1/C2保留repository/buggy/，复制到自己的提交目录后修改；C3/C4从starter/开始；R3/R4实现submission.py。\n"
                 "题面中的judge.py/e2e_env_judge.py是主办方验收入口，本参赛包不提供参考解、主办方期望值或裁判内部。\n"
                 "请自行编写和运行自测，并保留复现、定位、修改与回归证据。最终交付完整提交及TEST_REPORT.md。\n"
                 "评测规则、允许工具和预算以该轮发放的round配置为准。源包不是不可信代码安全沙箱。\n")
        archive.writestr("README.md", intro)
        for task in sorted(TASKS, key=lambda t: ("RCF".index(t[0]), int(t[1:]))):
            public = task_files(task)
            for name, blob in public.items():
                if any(part in {"organizer", "results", "baseline", "__pycache__"} for part in Path(name).parts) or Path(name).name in {"baseline.py", "baseline.html", "oracle.py"}:
                    raise ValueError("non-public file in export: " + name)
                member = f"tasks/{task}/{name}"
                archive.writestr(member, blob)
                manifest[member] = hashlib.sha256(blob).hexdigest()
        archive.writestr("MANIFEST.sha256.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with ZipFile(target) as archive:
        if archive.testzip():
            raise RuntimeError("archive CRC verification failed")
        for name, digest in manifest.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise RuntimeError("archive content mismatch")
    print(json.dumps({"archive": str(target), "tasks": len(TASKS), "public_files": len(manifest),
                      "bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
