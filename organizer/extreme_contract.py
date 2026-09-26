"""Shared evidence contract. Counts are workload proxies, never intelligence multipliers."""
import math

TASKS = tuple(f"{track}{n}" for track in "RCF" for n in range(1, 5))


def finite(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("measurement must be a finite number, not bool")
    if value < 0 or (positive and value == 0):
        raise ValueError("measurement is outside its nonnegative/positive domain")
    return value


def validate_report(report):
    if not isinstance(report, dict) or report.get("task_id") not in TASKS or report.get("profile") != "extreme":
        raise ValueError("unknown task or profile")
    if report.get("scale") not in ("smoke", "full") or type(report.get("seed")) is not int:
        raise ValueError("scale and integer seed required")
    if type(report.get("audit_passed")) is not bool:
        raise ValueError("audit_passed must be a boolean distinct from candidate validity")
    dimensions = report.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("measured dimensions required")
    instantiated_growth = []
    names = set()
    for dimension in dimensions:
        name = dimension.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("unique dimension names required")
        names.add(name)
        legacy = finite(dimension.get("legacy"), positive=True)
        current = finite(dimension.get("current"))
        ratio = finite(dimension.get("ratio"))
        if not math.isclose(ratio, current / legacy, rel_tol=1e-8, abs_tol=1e-10):
            raise ValueError("reported growth ratio does not match its counts")
        if dimension.get("scope") not in ("generated", "executed", "specified"):
            raise ValueError("measurement scope must distinguish construction from execution")
        if dimension["scope"] in ("generated", "executed"):
            instantiated_growth.append(ratio)
    if report["scale"] == "full" and max(instantiated_growth, default=0) < 10:
        raise ValueError("full task must instantiate at least one >=10x measured dimension")
    mechanisms = report.get("mechanisms")
    if not isinstance(mechanisms, list) or any(not isinstance(m, str) or not m.strip() for m in mechanisms) or len(set(mechanisms)) < 2:
        raise ValueError("at least two distinct coupled mechanisms must be documented")
    if not isinstance(report.get("verification"), dict) or not report["verification"]:
        raise ValueError("verification evidence required")
    candidate = report.get("candidate_result", report.get("baseline_result"))
    if not isinstance(candidate, dict):
        raise ValueError("candidate result or explicit pending measurement required")
    if "valid" in candidate and candidate["valid"] is not None and type(candidate["valid"]) is not bool:
        raise ValueError("candidate validity must be boolean or pending")
    if candidate.get("raw_score") is not None:
        finite(candidate["raw_score"])
    return report
