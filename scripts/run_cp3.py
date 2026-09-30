"""Run the released CP3 baseline and challenge; investigate metrics before traces.

Requires the lab API running without --reload. Does not modify challenge.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.challenge import load_challenge
from scripts.dashboard import summarize

EVIDENCE = ROOT / "submission/evidence"
BASE_URL = "http://127.0.0.1:8000"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(name: str, value: dict) -> None:
    (EVIDENCE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_load(name: str, *options: str) -> dict:
    started = timestamp()
    command = [sys.executable, str(ROOT / "scripts/load_test.py"), *options]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    ended = timestamp()
    (EVIDENCE / f"cp3-{name}-workload.txt").write_text(
        "python scripts/load_test.py " + " ".join(options) + "\n" + result.stdout + result.stderr,
        encoding="utf-8",
    )
    if result.returncode or "Error:" in result.stdout:
        raise RuntimeError(f"{name} workload failed; inspect saved output")
    records = [json.loads(line) for line in (ROOT / "data/logs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    records = [r for r in records if started <= r.get("ts", "") <= ended]
    responses = [r for r in records if r.get("event") == "response_sent"]
    if not responses:
        raise RuntimeError(f"No response logs for {name}")
    return {"started_at": started, "ended_at": ended, "metrics": summarize(records), "correlation_ids": [r["correlation_id"] for r in responses]}


def main() -> None:
    challenge = load_challenge()
    if challenge.challenge_id != "day13-k4-l3b-monitoring-llmops-v1":
        raise RuntimeError("Unexpected official challenge ID")
    if "--recover" in sys.argv:
        run = json.loads((EVIDENCE / "cp3-run.json").read_text(encoding="utf-8"))
        result = subprocess.run([sys.executable, "scripts/inject_incident.py", "--disable"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        (EVIDENCE / "cp3-recovery-action.txt").write_text("python scripts/inject_incident.py --disable\n" + result.stdout + result.stderr, encoding="utf-8")
        result.check_returncode()
        health = httpx.get(f"{BASE_URL}/health").json()
        if any(health["incidents"].values()):
            raise RuntimeError("Incident remains enabled")
        run["recovery_health"] = health
        run["phases"]["recovery"] = run_load("recovery", "--challenge", "--concurrency", "5")
        write_json("cp3-run.json", run)
        write_json("12-incident-metric.json", {"challenge_id": challenge.challenge_id, "phases": run["phases"], "threshold_ms": challenge.latency_threshold_ms})
        print(json.dumps(run["phases"]["recovery"], indent=2))
        return
    health = httpx.get(f"{BASE_URL}/health").json()
    if not health.get("ok") or any(health["incidents"].values()):
        raise RuntimeError("Start with healthy API and every incident disabled")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    run = {"challenge_id": challenge.challenge_id, "challenge_threshold_ms": challenge.latency_threshold_ms, "initial_health": health, "phases": {}}
    run["phases"]["baseline"] = run_load("baseline")
    injection = subprocess.run([sys.executable, "scripts/inject_incident.py"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    (EVIDENCE / "cp3-injection.txt").write_text("python scripts/inject_incident.py\n" + injection.stdout + injection.stderr, encoding="utf-8")
    if injection.returncode:
        raise RuntimeError("Challenge injection failed")
    run["phases"]["incident"] = run_load("incident", "--challenge", "--concurrency", "5")
    records = [json.loads(line) for line in (ROOT / "data/logs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    phase_ids = set(run["phases"]["incident"]["correlation_ids"])
    abnormal = [r for r in records if r.get("event") == "response_sent" and r.get("correlation_id") in phase_ids and r.get("latency_ms", 0) > challenge.latency_threshold_ms]
    if not abnormal:
        raise RuntimeError("No latency anomaly found; inspect metrics before selecting a trace")
    selected = max(abnormal, key=lambda r: r["latency_ms"])
    selected = {k: v for k, v in selected.items() if k != "payload"}
    run["selected_request"] = selected
    run["abnormal_request_count"] = len(abnormal)
    write_json("cp3-run.json", run)
    write_json("12-incident-metric.json", {"challenge_id": challenge.challenge_id, "phases": run["phases"], "threshold_ms": challenge.latency_threshold_ms})
    (EVIDENCE / "13-incident-log.txt").write_text(
        "Source: actual response_sent in data/logs.jsonl; payload omitted to keep the private challenge query out of submitted evidence.\n"
        + json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"baseline_latency": run["phases"]["baseline"]["metrics"]["latency"], "incident_latency": run["phases"]["incident"]["metrics"]["latency"], "abnormal_requests": len(abnormal), "correlation_id": selected["correlation_id"], "trace_id": selected["trace_id"]}, indent=2))


if __name__ == "__main__":
    main()
