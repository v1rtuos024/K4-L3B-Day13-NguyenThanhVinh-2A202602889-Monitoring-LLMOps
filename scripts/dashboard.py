"""Six-panel local dashboard backed by the structured JSONL log.

Run: python scripts/dashboard.py, then open http://127.0.0.1:8765.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from statistics import mean
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "config/dashboard.yaml").read_text(encoding="utf-8"))["dashboard"]
LOG_PATH = ROOT / "data/logs.jsonl"
CP3_RUN_PATH = ROOT / "submission/evidence/cp3-run.json"


def percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return float(ordered[index])


def recent_records(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=CONFIG["time_range_minutes"])
    if not LOG_PATH.exists():
        return []
    records = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            ts = datetime.fromisoformat(record["ts"].replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError):
            continue
        if cutoff <= ts <= now:
            records.append(record)
    return records


def summarize(records: list[dict]) -> dict:
    received = [r for r in records if r.get("event") == "request_received"]
    responses = [r for r in records if r.get("event") == "response_sent"]
    failures = [r for r in records if r.get("event") == "request_failed"]
    tools = [r for r in records if r.get("tool_success") is not None]
    latency = [float(r["latency_ms"]) for r in responses if isinstance(r.get("latency_ms"), (int, float))]
    ttft = [float(r["ttft_ms"]) for r in responses if isinstance(r.get("ttft_ms"), (int, float))]
    by_minute = defaultdict(lambda: {"traffic": 0, "cost": 0.0})
    for r in records:
        minute = r["ts"][:16]
        if r.get("event") == "request_received":
            by_minute[minute]["traffic"] += 1
        if r.get("event") == "response_sent":
            by_minute[minute]["cost"] += float(r.get("cost_usd") or 0)
    scores = [float(r["quality_score"]) for r in responses if isinstance(r.get("quality_score"), (int, float))]
    return {
        "latency": {"P50": percentile(latency, 50), "P95": percentile(latency, 95), "P99": percentile(latency, 99), "TTFT P95": percentile(ttft, 95)},
        "traffic": {"requests": len(received), "peak requests/min": max((v["traffic"] for v in by_minute.values()), default=0)},
        "errors": {"error rate": 100 * len(failures) / len(received) if received else 0, "retrieval success": 100 * sum(r["tool_success"] is True for r in tools) / len(tools) if tools else 0, "types": dict(Counter(r.get("error_type", "unknown") for r in failures))},
        "cost": {"total": sum(float(r.get("cost_usd") or 0) for r in responses), "peak USD/min": max((v["cost"] for v in by_minute.values()), default=0)},
        "tokens": {"input": sum(int(r.get("tokens_in") or 0) for r in responses), "output": sum(int(r.get("tokens_out") or 0) for r in responses)},
        "quality": {"mean": mean(scores) if scores else 0},
        "series": dict(sorted(by_minute.items())),
        "response_count": len(responses),
    }


def latency_chart(records: list[dict], phases: dict, anomaly_limit: float) -> str:
    rows = sorted([r for r in records if r.get("event") == "response_sent" and isinstance(r.get("latency_ms"), (int, float))], key=lambda r: r["ts"])
    if not rows:
        return "<p>No response data in this window.</p>"
    times = [datetime.fromisoformat(r["ts"].replace("Z", "+00:00")).timestamp() for r in rows]
    start, end = times[0], times[-1]
    span = max(end - start, 1)
    ceiling = max(3300, max(r["latency_ms"] for r in rows) * 1.1)
    colors = {"baseline": "#2575b5", "incident": "#c63737", "recovery": "#27854b"}
    membership = {cid: name for name, phase in phases.items() for cid in phase["correlation_ids"]}
    x = lambda t: 55 + (t - start) / span * 485
    y = lambda ms: 155 - ms / ceiling * 130
    svg = ['<svg class="timeline" viewBox="0 0 570 200" role="img" aria-label="Request latency and TTFT over time, UTC">']
    for name, phase in phases.items():
        if not any(r["correlation_id"] in phase["correlation_ids"] for r in rows):
            continue
        begin = max(start, datetime.fromisoformat(phase["started_at"].replace("Z", "+00:00")).timestamp())
        finish = min(end, datetime.fromisoformat(phase["ended_at"].replace("Z", "+00:00")).timestamp())
        svg.append(f'<rect x="{x(begin):.1f}" y="25" width="{max(2, x(finish)-x(begin)):.1f}" height="130" fill="{colors.get(name, "#aaa")}" opacity="0.07"/>')
    for limit, label, color in ((0, "0", "#8090a0"), (anomaly_limit, f"Challenge {anomaly_limit:g} ms", "#c63737"), (3000, "SLO 3000 ms", "#9a6500")):
        svg.append(f'<line x1="55" y1="{y(limit):.1f}" x2="540" y2="{y(limit):.1f}" stroke="{color}" stroke-dasharray="4 3"/><text x="58" y="{y(limit)-4:.1f}" fill="{color}" font-size="11">{label}</text>')
    latency_points = " ".join(f'{x(t):.1f},{y(r["latency_ms"]):.1f}' for t, r in zip(times, rows))
    ttft_points = " ".join(f'{x(t):.1f},{y(r.get("ttft_ms", 0)):.1f}' for t, r in zip(times, rows))
    svg.append(f'<polyline points="{latency_points}" fill="none" stroke="#53677e" stroke-width="1.5"/><polyline points="{ttft_points}" fill="none" stroke="#8753ad" stroke-width="1.5"/>')
    for t, row in zip(times, rows):
        color = colors.get(membership.get(row["correlation_id"]), "#53677e")
        svg.append(f'<circle cx="{x(t):.1f}" cy="{y(row["latency_ms"]):.1f}" r="3.5" fill="{color}"><title>{escape(row["ts"])} {escape(row["correlation_id"])}: {row["latency_ms"]} ms</title></circle>')
    for fraction, anchor in ((0, "start"), (0.5, "middle"), (1, "end")):
        label = datetime.fromtimestamp(start + fraction * span, timezone.utc).strftime("%H:%M:%S")
        svg.append(f'<text x="{55+485*fraction:.1f}" y="176" text-anchor="{anchor}" fill="#566579" font-size="11">{label}</text>')
    svg.append('<text x="55" y="194" fill="#566579" font-size="11">UTC · blue baseline · red incident · green recovery · purple TTFT</text></svg>')
    comparisons = []
    for name, phase in phases.items():
        subset = [r for r in rows if r["correlation_id"] in phase["correlation_ids"]]
        if subset:
            comparisons.append(f'{name} P95 {percentile([r["latency_ms"] for r in subset], 95):g} ms')
    return "".join(svg) + f'<p class="comparison">{escape(" · ".join(comparisons))}</p>'


def render(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    records = recent_records(now)
    data = summarize(records)
    run = json.loads(CP3_RUN_PATH.read_text(encoding="utf-8")) if CP3_RUN_PATH.exists() else {}
    panels = {p["id"]: p for p in CONFIG["panels"]}
    body = []
    specs = [
        ("latency", [("P50", "ms"), ("P95", "ms"), ("P99", "ms"), ("TTFT P95", "ms")], data["latency"]),
        ("traffic", [("requests", "requests"), ("peak requests/min", "requests/min")], data["traffic"]),
        ("errors", [("error rate", "%"), ("retrieval success", "%")], data["errors"]),
        ("cost", [("total", "USD"), ("peak USD/min", "USD/min")], data["cost"]),
        ("tokens", [("input", "tokens"), ("output", "tokens")], data["tokens"]),
        ("quality", [("mean", "score 0–1")], data["quality"]),
    ]
    for panel_id, fields, values in specs:
        config = panels[panel_id]
        threshold = config["threshold"]
        relation = "≤" if threshold["operator"] == "lte" else "≥"
        metrics = "".join(
            f'<div class="metric"><span>{escape(name)}</span><strong>{values[name]:.3f}</strong><small>{escape(unit)}</small></div>'
            for name, unit in fields
        )
        extra = ""
        if panel_id == "latency":
            extra = latency_chart(records, run.get("phases", {}), run.get("challenge_threshold_ms", 2000))
        if panel_id == "errors":
            extra = "<p>Error types: " + escape(json.dumps(values["types"], ensure_ascii=False)) + "</p>"
        if panel_id in {"traffic", "cost"}:
            key = "traffic" if panel_id == "traffic" else "cost"
            series = list(data["series"].items())[-30:]
            high = max((point[key] for _, point in series), default=0) or 1
            bars = "".join(
                f'<div title="{escape(minute)}: {point[key]:.4f}" style="height:{max(2, point[key] / high * 80):.1f}px"></div>'
                for minute, point in series
            )
            extra = f'<div class="bars">{bars}</div><small>Per-minute trend · UTC</small>'
        body.append(
            f'<section><h2>{escape(config["title"])}</h2><div class="metrics">{metrics}</div>'
            f'<p class="threshold">Threshold: {escape(str(threshold["aggregation"]))} {relation} {threshold["value"]} {escape(config["unit"])}</p>{extra}</section>'
        )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="{CONFIG['refresh_seconds']}">
<title>{escape(CONFIG['title'])}</title><style>
body{{font:16px system-ui;background:#f3f5f8;color:#17223b;max-width:1260px;margin:auto;padding:24px}}
header{{display:flex;justify-content:space-between;align-items:end;margin-bottom:24px}}h1{{margin:0;font-size:26px}}h2{{font-size:19px;margin:0 0 18px}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}section{{background:white;border:1px solid #dce2ea;border-radius:12px;padding:22px;min-height:205px}}
.metrics{{display:flex;gap:24px;flex-wrap:wrap}}.metric{{display:flex;flex-direction:column;min-width:95px}}.metric strong{{font-size:30px;color:#1765b3}}small,.metric span{{color:#566579}}
.threshold{{border-top:1px solid #e3e8ee;padding-top:12px;margin-top:20px;font-size:13px;color:#374b63}}.bars{{height:85px;display:flex;align-items:end;gap:3px;margin-top:8px}}.bars div{{background:#2d80bd;min-width:4px;flex:1}}
.timeline{{width:100%;height:auto;display:block}}.comparison{{font-size:13px;color:#374b63}}
@media(max-width:750px){{.grid{{grid-template-columns:1fr}}header{{display:block}}}}</style></head><body>
<header><div><h1>{escape(CONFIG['title'])}</h1><p>Source: data/logs.jsonl · Last {CONFIG['time_range_minutes']} minutes · {data['response_count']} responses</p></div><div>Window ends {now.strftime('%Y-%m-%d %H:%M:%S UTC')}<br>Refresh {CONFIG['refresh_seconds']}s</div></header>
<main class="grid">{''.join(body)}</main></body></html>'''


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        window_end = None
        if url.path == "/cp3" and CP3_RUN_PATH.exists():
            run = json.loads(CP3_RUN_PATH.read_text(encoding="utf-8"))
            name = parse_qs(url.query).get("phase", ["recovery" if "recovery" in run["phases"] else "incident"])[0]
            if name not in run["phases"]:
                self.send_error(404)
                return
            window_end = datetime.fromisoformat(run["phases"][name]["ended_at"].replace("Z", "+00:00"))
        elif url.path != "/":
            self.send_error(404)
            return
        page = render(window_end).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


if __name__ == "__main__":
    print("Dashboard: http://127.0.0.1:8765", flush=True)
    HTTPServer(("127.0.0.1", 8765), DashboardHandler).serve_forever()
