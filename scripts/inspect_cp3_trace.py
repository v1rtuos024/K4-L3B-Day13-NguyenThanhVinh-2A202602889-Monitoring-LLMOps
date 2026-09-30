"""Read only the metric-selected CP3 trace and a baseline trace from Langfuse."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from langfuse import get_client

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "submission/evidence"
load_dotenv(ROOT / ".env")
ALLOWED = {"correlation_id", "feature", "model", "prompt_name", "prompt_label", "prompt_version", "prompt_source", "doc_count", "success", "ttft_ms", "cost_usd"}


def get_trace(client, trace_id: str, phase: dict) -> list[dict]:
    started = datetime.fromisoformat(phase["started_at"].replace("Z", "+00:00")) - timedelta(seconds=5)
    ended = datetime.fromisoformat(phase["ended_at"].replace("Z", "+00:00")) + timedelta(seconds=5)
    for attempt in range(6):
        observations = client.api.observations.get_many(
            trace_id=trace_id, from_start_time=started, to_start_time=ended,
            fields="core,basic,metadata,model,usage,prompt,metrics,io,trace_context", limit=20,
        ).data
        if len(observations) == 3:
            break
        if attempt == 5:
            raise RuntimeError(f"Expected three observations for {trace_id}, got {len(observations)}")
        time.sleep(2)
    rows = []
    for o in sorted(observations, key=lambda item: item.start_time):
        rows.append({
            "name": o.name, "type": o.type, "id": o.id, "parent_id": o.parent_observation_id,
            "start_time": o.start_time.isoformat(), "end_time": o.end_time.isoformat(),
            "duration_ms": round((o.end_time - o.start_time).total_seconds() * 1000, 3),
            "level": o.level, "metadata": {k: v for k, v in (o.metadata or {}).items() if k in ALLOWED},
            "model": o.model, "usage_details": o.usage_details, "cost_details": o.cost_details,
            "prompt_name": o.prompt_name, "prompt_version": o.prompt_version,
            "input_empty": o.input in (None, "", "null"), "output_empty": o.output in (None, "", "null"),
        })
    root = next(row for row in rows if row["name"] == "lab-agent-run")
    if any(row["parent_id"] != root["id"] for row in rows if row is not root):
        raise RuntimeError("Incorrect parent-child trace linkage")
    return rows


def main() -> None:
    run = json.loads((EVIDENCE / "cp3-run.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in (ROOT / "data/logs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    baseline_ids = set(run["phases"]["baseline"]["correlation_ids"])
    baseline = sorted([r for r in records if r.get("event") == "response_sent" and r.get("correlation_id") in baseline_ids], key=lambda r: r["latency_ms"])
    baseline = baseline[len(baseline) // 2]
    selected = run["selected_request"]
    client = get_client()
    project = client.api.projects.get().data[0]
    incident_rows = get_trace(client, selected["trace_id"], run["phases"]["incident"])
    baseline_rows = get_trace(client, baseline["trace_id"], run["phases"]["baseline"])
    root = next(row for row in incident_rows if row["name"] == "lab-agent-run")
    if root["metadata"].get("correlation_id") != selected["correlation_id"]:
        raise RuntimeError("Trace/log correlation mismatch")
    result = {
        "project_name": project.name, "project_id": project.id, "challenge_id": run["challenge_id"],
        "baseline": {"correlation_id": baseline["correlation_id"], "trace_id": baseline["trace_id"], "observations": baseline_rows},
        "incident": {"correlation_id": selected["correlation_id"], "trace_id": selected["trace_id"], "observations": incident_rows},
    }
    (EVIDENCE / "14-incident-trace.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"project": project.name, "baseline": [(r["name"], r["duration_ms"]) for r in baseline_rows], "incident": [(r["name"], r["duration_ms"], r["level"]) for r in incident_rows], "empty_io": all(r["input_empty"] and r["output_empty"] for r in incident_rows + baseline_rows)}, indent=2, default=str))


if __name__ == "__main__":
    main()
