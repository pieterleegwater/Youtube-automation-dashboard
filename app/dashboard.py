"""Gegevens voor de dashboardpagina, gedeeld door de live server en de statische versie."""

from . import pipeline, youtube_client
from .config import settings
from .db import connect, latest_stats_by_video


def dashboard_context() -> dict:
    with connect() as conn:
        latest = latest_stats_by_video(conn)
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM strategies")}
        videos = []
        for v in conn.execute("SELECT * FROM videos ORDER BY id DESC LIMIT 60"):
            videos.append({**dict(v), "strategy": names.get(v["strategy_id"], "?"), **pipeline.video_metrics(latest.get(v["id"]))})
        strategies = pipeline.strategy_overview(conn)
        logs = [dict(r) for r in conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 30")]

    uploaded = [v for v in videos if v["status"] == "uploaded"]
    stayed = [v["stayed"] for v in uploaded if v["stayed"] is not None]
    kpis = {
        "uploads": len(uploaded),
        "views": sum(v["views"] for v in uploaded),
        "stayed": sum(stayed) / len(stayed) if stayed else None,
        "best": max((s for s in strategies if s["score"] is not None), key=lambda s: s["score"], default=None),
    }
    chart = [
        {"label": v["title"][:40] or f"#{v['id']}", "views": v["views"], "stayed": v["stayed"]}
        for v in reversed(uploaded[:30])
    ]
    return {
        "videos": videos,
        "strategies": strategies,
        "logs": logs,
        "kpis": kpis,
        "chart": chart,
        "jobs": [],
        "static_mode": False,
        "youtube_connected": youtube_client.is_connected(),
        "gemini_configured": bool(settings.gemini_api_key),
    }
