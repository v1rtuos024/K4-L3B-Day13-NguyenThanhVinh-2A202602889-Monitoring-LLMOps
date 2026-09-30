"""Export the current six-panel dashboard as a self-contained SVG image."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dashboard import CONFIG, recent_records, summarize  # noqa: E402


def main() -> None:
    now = datetime.now(timezone.utc)
    data = summarize(recent_records(now))
    panels = {p["id"]: p for p in CONFIG["panels"]}
    specs = [
        ("latency", [("P50", "ms"), ("P95", "ms"), ("P99", "ms"), ("TTFT P95", "ms")], data["latency"]),
        ("traffic", [("requests", "requests"), ("peak requests/min", "req/min")], data["traffic"]),
        ("errors", [("error rate", "%"), ("retrieval success", "%")], data["errors"]),
        ("cost", [("total", "USD"), ("peak USD/min", "USD/min")], data["cost"]),
        ("tokens", [("input", "tokens"), ("output", "tokens")], data["tokens"]),
        ("quality", [("mean", "score 0–1")], data["quality"]),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="930" viewBox="0 0 1280 930">',
        '<rect width="1280" height="930" fill="#f3f5f8"/>',
        '<text x="40" y="55" font-family="Arial" font-size="27" font-weight="bold" fill="#17223b">K4-L3B Day 13 Monitoring &amp; LLMOps</text>',
        f'<text x="40" y="82" font-family="Arial" font-size="15" fill="#506076">Source: data/logs.jsonl · Last {CONFIG["time_range_minutes"]} minutes · {data["response_count"]} responses · Updated {now:%Y-%m-%d %H:%M:%S} UTC · Refresh {CONFIG["refresh_seconds"]}s</text>',
    ]
    for index, (panel_id, fields, values) in enumerate(specs):
        x = 40 + index % 2 * 610
        y = 112 + index // 2 * 262
        panel = panels[panel_id]
        threshold = panel["threshold"]
        relation = "≤" if threshold["operator"] == "lte" else "≥"
        parts.extend([
            f'<rect x="{x}" y="{y}" width="590" height="242" rx="12" fill="white" stroke="#dce2ea"/>',
            f'<text x="{x+22}" y="{y+33}" font-family="Arial" font-size="20" font-weight="bold" fill="#17223b">{escape(panel["title"])}</text>',
        ])
        for j, (name, unit) in enumerate(fields):
            col = j % 2
            row = j // 2
            mx = x + 22 + col * 278
            my = y + 70 + row * 65
            parts.extend([
                f'<text x="{mx}" y="{my}" font-family="Arial" font-size="14" fill="#566579">{escape(name)}</text>',
                f'<text x="{mx}" y="{my+29}" font-family="Arial" font-size="27" font-weight="bold" fill="#1765b3">{values[name]:.3f}</text>',
                f'<text x="{mx+150}" y="{my+28}" font-family="Arial" font-size="12" fill="#566579">{escape(unit)}</text>',
            ])
        parts.extend([
            f'<line x1="{x+22}" y1="{y+197}" x2="{x+568}" y2="{y+197}" stroke="#dce2ea"/>',
            f'<text x="{x+22}" y="{y+222}" font-family="Arial" font-size="14" fill="#374b63">Threshold: {escape(str(threshold["aggregation"]))} {relation} {threshold["value"]} {escape(panel["unit"])}</text>',
        ])
        if panel_id == "errors":
            parts.append(f'<text x="{x+300}" y="{y+172}" font-family="Arial" font-size="12" fill="#566579">Error types: {escape(str(values["types"]))}</text>')
    parts.append('</svg>')
    output = ROOT / "submission/evidence/11-dashboard-overview.svg"
    output.write_text("\n".join(parts), encoding="utf-8")
    print(f"Exported {output.relative_to(ROOT)} from {data['response_count']} response logs")


if __name__ == "__main__":
    main()
