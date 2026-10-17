"""Read-only capability probe: counts and field names only, never conversation paths or content."""

from __future__ import annotations

from .collectors import all_collectors, discover_all, probe_all


def run_probe(env=None, home=None, collectors=None) -> dict:
    collectors = collectors if collectors is not None else all_collectors(env, home)
    probes = probe_all(collectors=collectors)
    found = discover_all(collectors=collectors)
    report = {}
    totals = {"sessions": 0, "with_cwd": 0, "without_cwd": 0, "archived": 0}
    for name, probe in probes.items():
        result = found.get(name, {"status": "ok", "detail": "", "sessions": []})
        sessions = result["sessions"]
        entry = {
            "status": probe["status"], "detail": probe["detail"], "fields": dict(probe["fields"]),
            "sessions": len(sessions), "with_cwd": sum(1 for s in sessions if s.cwd),
            "without_cwd": sum(1 for s in sessions if not s.cwd), "archived": sum(1 for s in sessions if s.archived),
            "distinct_cwds": len({s.cwd for s in sessions if s.cwd}),
        }
        if result["status"] != "ok":
            entry["status"], entry["detail"] = "unsupported", result["detail"]
        for key in totals:
            totals[key] += entry[key]
        report[name] = entry
    return {"collectors": report, "totals": totals}
