"""Sinh dashboard 6 panel từ data/logs.jsonl theo contract config/dashboard.yaml.

    python scripts/build_dashboard.py                      # data/dashboard.html, cửa sổ 60 phút tới hiện tại
    python scripts/build_dashboard.py --png out.png        # thêm ảnh PNG qua Edge/Chrome headless
    python scripts/build_dashboard.py --json               # in số liệu tổng hợp để ghi report

Trang HTML tự refresh theo `refresh_seconds`; chạy script định kỳ (hoặc --watch) để cập nhật số liệu.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge",
    "google-chrome",
    "chromium",
)


def load_records(path: Path, start: datetime, end: datetime) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if start <= ts <= end:
            rec["_ts"] = ts
            records.append(rec)
    return records


def compute(records: list[dict], start: datetime, minutes: int) -> dict:
    received = [r for r in records if r.get("event") == "request_received"]
    responses = [r for r in records if r.get("event") == "response_sent"]
    failed = [r for r in records if r.get("event") == "request_failed"]
    tool = [r for r in records if r.get("tool_success") is not None]

    def bucket(rec: dict) -> int:
        return int((rec["_ts"] - start).total_seconds() // 60)

    per_min: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for r in received:
        per_min["traffic"][bucket(r)].append(1)
    for r in failed:
        per_min["failed"][bucket(r)].append(1)
    for r in responses:
        b = bucket(r)
        per_min["latency"][b].append(r["latency_ms"])
        per_min["cost"][b].append(r["cost_usd"])
        per_min["quality"][b].append(r["quality_score"])
        per_min["tokens_in"][b].append(r["tokens_in"])
        per_min["tokens_out"][b].append(r["tokens_out"])

    latencies = [r["latency_ms"] for r in responses]
    ttfts = [r["ttft_ms"] for r in responses]
    series = {
        "latency_p95": {b: percentile(v, 95) for b, v in per_min["latency"].items()},
        "traffic": {b: len(v) for b, v in per_min["traffic"].items()},
        "error_rate": {
            b: 100 * len(per_min["failed"].get(b, [])) / n
            for b, n in ((b, len(v)) for b, v in per_min["traffic"].items())
        },
        "cost": {b: sum(v) for b, v in per_min["cost"].items()},
        "tokens_in": {b: sum(v) for b, v in per_min["tokens_in"].items()},
        "tokens_out": {b: sum(v) for b, v in per_min["tokens_out"].items()},
        "quality": {b: mean(v) for b, v in per_min["quality"].items()},
    }
    active_minutes = max(1, len(per_min["traffic"]))
    return {
        "window_start": start.isoformat(),
        "window_minutes": minutes,
        "latency_p50": percentile(latencies, 50),
        "latency_p95": percentile(latencies, 95),
        "latency_p99": percentile(latencies, 99),
        "ttft_p95": percentile(ttfts, 95),
        "traffic_count": len(received),
        "traffic_rpm_active": round(len(received) / active_minutes, 2),
        "error_rate_pct": round(100 * len(failed) / len(received), 2) if received else 0.0,
        "error_breakdown": dict(Counter(r.get("error_type") or "unknown" for r in failed)),
        "retrieval_success_pct": (
            round(100 * sum(r["tool_success"] is True for r in tool) / len(tool), 2) if tool else None
        ),
        "cost_total_usd": round(sum(r["cost_usd"] for r in responses), 6),
        "tokens_in_total": sum(r["tokens_in"] for r in responses),
        "tokens_out_total": sum(r["tokens_out"] for r in responses),
        "quality_mean": round(mean(r["quality_score"] for r in responses), 3) if responses else None,
        "series": series,
    }


def svg_chart(
    series: dict[str, dict[int, float]],
    minutes: int,
    threshold: float | None,
    kind: str = "line",
    colors: tuple[str, ...] = ("var(--s1)", "var(--s2)"),
) -> str:
    width, height, pad_l, pad_b, pad_t = 460, 150, 44, 22, 10
    values = [v for s in series.values() for v in s.values()]
    top = max(values + ([threshold] if threshold is not None else []) + [1e-9]) * 1.15
    plot_w, plot_h = width - pad_l - 8, height - pad_b - pad_t

    def x(b: float) -> float:
        return pad_l + plot_w * (b + 0.5) / minutes

    def y(v: float) -> float:
        return pad_t + plot_h * (1 - v / top)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    for frac in (0, 0.5, 1):
        gy = pad_t + plot_h * (1 - frac)
        parts.append(f'<line x1="{pad_l}" x2="{width - 8}" y1="{gy:.1f}" y2="{gy:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_l - 4}" y="{gy + 3:.1f}" class="tick" text-anchor="end">{fmt(top * frac)}</text>')
    for m in range(0, minutes + 1, 15):
        label = f"-{minutes - m}m" if m < minutes else "now"
        parts.append(f'<text x="{pad_l + plot_w * m / minutes:.1f}" y="{height - 6}" class="tick" text-anchor="middle">{label}</text>')
    bar_w = max(2.0, plot_w / minutes * 0.7 / max(1, len(series)))
    for idx, (name, points) in enumerate(series.items()):
        color = colors[idx % len(colors)]
        if kind == "bar":
            for b, v in points.items():
                bx = x(b) - bar_w * len(series) / 2 + idx * bar_w
                parts.append(f'<rect x="{bx:.1f}" y="{y(v):.1f}" width="{bar_w:.1f}" height="{y(0) - y(v):.1f}" fill="{color}"><title>{name}: {fmt(v)}</title></rect>')
        else:
            pts = sorted(points.items())
            if len(pts) > 1:
                path = " ".join(f"{x(b):.1f},{y(v):.1f}" for b, v in pts)
                parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
            for b, v in pts:
                parts.append(f'<circle cx="{x(b):.1f}" cy="{y(v):.1f}" r="3" fill="{color}"><title>{name}: {fmt(v)}</title></circle>')
    if threshold is not None:
        ty = y(threshold)
        parts.append(f'<line x1="{pad_l}" x2="{width - 8}" y1="{ty:.1f}" y2="{ty:.1f}" class="threshold"/>')
        parts.append(f'<text x="{width - 10}" y="{ty - 4:.1f}" class="tick thr" text-anchor="end">threshold {fmt(threshold)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def fmt(v: float | None) -> str:
    if v is None:
        return "–"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:.0f}"
    if abs(v) >= 0.1 or v == 0:
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{v:.4f}"


def status(value: float | None, threshold: dict) -> str:
    if value is None:
        return "na"
    ok = value <= threshold["value"] if threshold["operator"] == "lte" else value >= threshold["value"]
    return "ok" if ok else "bad"


def render(stats: dict, config: dict, generated: datetime) -> str:
    dash = config["dashboard"]
    panels = {p["id"]: p for p in dash["panels"]}
    minutes = dash["time_range_minutes"]
    s = stats["series"]

    def thr(pid: str) -> dict:
        return panels[pid]["threshold"]

    def op(t: dict) -> str:
        return "≤" if t["operator"] == "lte" else "≥"

    def stat(label: str, value: str, cls: str = "") -> str:
        return f'<div class="stat {cls}"><span>{html.escape(label)}</span><b>{value}</b></div>'

    def panel(pid: str, stats_html: str, chart: str, legend: str = "") -> str:
        p = panels[pid]
        t = p["threshold"]
        return (
            f'<section class="panel"><header><h2>{html.escape(p["title"])}</h2>'
            f'<span class="unit">unit: {html.escape(p["unit"])}</span></header>'
            f'<div class="stats">{stats_html}</div>{chart}'
            f'<footer>{legend}<span class="thrnote">threshold: {t["aggregation"]} {op(t)} {fmt(t["value"])}</span></footer></section>'
        )

    lat_t, err_t, cost_t, tok_t, q_t, trf_t = (thr(k) for k in ("latency", "errors", "cost", "tokens", "quality", "traffic"))
    breakdown = ", ".join(f"{k}: {v}" for k, v in stats["error_breakdown"].items()) or "none"
    rs = stats["retrieval_success_pct"]
    body = "".join([
        panel("latency",
              stat("P50", f'{fmt(stats["latency_p50"])} ms')
              + stat("P95", f'{fmt(stats["latency_p95"])} ms', status(stats["latency_p95"], lat_t))
              + stat("P99", f'{fmt(stats["latency_p99"])} ms')
              + stat("TTFT P95", f'{fmt(stats["ttft_p95"])} ms'),
              svg_chart({"p95 latency": s["latency_p95"]}, minutes, lat_t["value"]),
              '<span class="key k1">P95 latency / minute</span>'),
        panel("traffic",
              stat("Requests", str(stats["traffic_count"]))
              + stat("Req/min (active)", fmt(stats["traffic_rpm_active"]), status(stats["traffic_rpm_active"], trf_t)),
              svg_chart({"requests": s["traffic"]}, minutes, trf_t["value"], kind="bar"),
              '<span class="key k1">requests / minute</span>'),
        panel("errors",
              stat("Error rate", f'{fmt(stats["error_rate_pct"])} %', status(stats["error_rate_pct"], err_t))
              + stat("Retrieval success", f"{fmt(rs)} %", "ok" if rs is not None and rs >= 90 else ("na" if rs is None else "bad"))
              + stat("Breakdown", html.escape(breakdown)),
              svg_chart({"error rate %": s["error_rate"]}, minutes, err_t["value"]),
              '<span class="key k1">error rate % / minute</span>'),
        panel("cost",
              stat("Total", f'${stats["cost_total_usd"]:.4f}', status(stats["cost_total_usd"], cost_t)),
              svg_chart({"cost": s["cost"]}, minutes, cost_t["value"], kind="bar"),
              '<span class="key k1">USD / minute</span>'),
        panel("tokens",
              stat("Input", f'{stats["tokens_in_total"]:,}', status(stats["tokens_in_total"], tok_t))
              + stat("Output", f'{stats["tokens_out_total"]:,}', status(stats["tokens_out_total"], tok_t)),
              svg_chart({"tokens_in": s["tokens_in"], "tokens_out": s["tokens_out"]}, minutes, None, kind="bar"),
              '<span class="key k1">tokens_in</span><span class="key k2">tokens_out</span> / minute'),
        panel("quality",
              stat("Mean score", fmt(stats["quality_mean"]), status(stats["quality_mean"], q_t)),
              svg_chart({"quality": s["quality"]}, minutes, q_t["value"]),
              '<span class="key k1">mean quality / minute</span>'),
    ])
    start = datetime.fromisoformat(stats["window_start"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{dash['refresh_seconds']}">
<title>{html.escape(dash['title'])}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --fg:#1d2330; --muted:#667085; --line:#e4e7ec; --s1:#2f6fed; --s2:#e8833a;
        --ok:#1a7f4b; --bad:#c4312f; --thr:#c4312f; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111418; --card:#1a1e24; --fg:#e6e8eb; --muted:#98a2b3; --line:#2b3139;
        --s1:#6b9bff; --s2:#f0a060; --ok:#4cc38a; --bad:#ff6b67; --thr:#ff6b67; }} }}
* {{ box-sizing:border-box }} body {{ margin:0; padding:20px; background:var(--bg); color:var(--fg); font:14px/1.4 system-ui,Segoe UI,sans-serif }}
.top {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:baseline; gap:8px; margin-bottom:14px }}
h1 {{ font-size:20px; margin:0 }} .meta {{ color:var(--muted); font-size:13px }}
.grid6 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:14px }}
.panel {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px }}
.panel header {{ display:flex; justify-content:space-between; align-items:baseline }} h2 {{ font-size:15px; margin:0 0 8px }}
.unit,.thrnote {{ color:var(--muted); font-size:12px }} .stats {{ display:flex; flex-wrap:wrap; gap:18px; margin-bottom:6px }}
.stat span {{ display:block; color:var(--muted); font-size:12px }} .stat b {{ font-size:20px; font-variant-numeric:tabular-nums }}
.stat.ok b {{ color:var(--ok) }} .stat.bad b {{ color:var(--bad) }}
svg {{ width:100%; height:auto; display:block }} .grid {{ stroke:var(--line) }} .tick {{ fill:var(--muted); font-size:10px }}
.threshold {{ stroke:var(--thr); stroke-dasharray:5 4; stroke-width:1.5 }} .thr {{ fill:var(--thr) }}
footer {{ display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:12px; color:var(--muted); margin-top:4px }}
.key::before {{ content:""; display:inline-block; width:10px; height:10px; border-radius:2px; margin:0 4px 0 8px; vertical-align:-1px }}
.k1::before {{ background:var(--s1) }} .k2::before {{ background:var(--s2) }}
@media (max-width:480px) {{ body {{ padding:16px }} .grid6 {{ grid-template-columns:1fr }} }}
</style></head><body>
<div class="top"><h1>{html.escape(dash['title'])}</h1>
<div class="meta">Time range: last {minutes} min ({start:%H:%M}–{generated:%H:%M} UTC) · refresh {dash['refresh_seconds']}s ·
source: data/logs.jsonl · generated {generated:%Y-%m-%d %H:%M:%S} UTC</div></div>
<div class="grid6">{body}</div></body></html>"""


def screenshot(html_path: Path, png_path: Path) -> None:
    browser = next((b for b in BROWSERS if Path(b).exists() or shutil.which(b)), None)
    if browser is None:
        raise SystemExit("Không tìm thấy Edge/Chrome để chụp PNG")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.unlink(missing_ok=True)
    # Profile riêng: nếu dùng profile mặc định khi trình duyệt đang mở, headless sẽ thoát mà không chụp
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-color-profile=srgb",
             f"--user-data-dir={profile}", "--window-size=1400,640",
             f"--screenshot={png_path.resolve()}", html_path.resolve().as_uri()],
            check=True, capture_output=True, timeout=60,
        )
        # Trên Windows, launcher có thể thoát trước khi tiến trình con ghi xong ảnh
        deadline = time.time() + 30
        while time.time() < deadline and not png_path.exists():
            time.sleep(0.5)
        time.sleep(1)
    if not png_path.exists():
        raise SystemExit(f"Trình duyệt không tạo được {png_path}")


def build(args: argparse.Namespace) -> dict:
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    minutes = config["dashboard"]["time_range_minutes"]
    end = datetime.now(timezone.utc) if args.until is None else datetime.fromisoformat(args.until.replace("Z", "+00:00"))
    start = end - timedelta(minutes=minutes)
    stats = compute(load_records(args.logs, start, end), start, minutes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(stats, config, end), encoding="utf-8")
    if args.png:
        screenshot(args.out, args.png)
    return stats


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "dashboard.html")
    parser.add_argument("--png", type=Path, help="Chụp dashboard ra PNG (cần Edge/Chrome)")
    parser.add_argument("--until", help="Mốc cuối cửa sổ (ISO, UTC); mặc định là hiện tại")
    parser.add_argument("--json", action="store_true", help="In số liệu tổng hợp")
    parser.add_argument("--watch", action="store_true", help="Sinh lại theo refresh_seconds")
    args = parser.parse_args()

    while True:
        stats = build(args)
        if args.json:
            print(json.dumps({k: v for k, v in stats.items() if k != "series"}, indent=2, ensure_ascii=False))
        else:
            print(f"Đã ghi {args.out}" + (f" và {args.png}" if args.png else ""))
        if not args.watch:
            break
        time.sleep(yaml.safe_load(args.config.read_text(encoding="utf-8"))["dashboard"]["refresh_seconds"])


if __name__ == "__main__":
    main()
