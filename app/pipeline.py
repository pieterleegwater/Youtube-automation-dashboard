"""De dagelijkse taken: genereren, uploaden, statistieken ophalen en strategieën bijsturen."""

import json
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import gemini_client, youtube_client
from .config import settings
from .db import connect, insert_strategy, latest_stats_by_video, log, now_iso
from .strategy import MIN_AGE_HOURS, Arm, choose_arm, pick_losers, score_video, stayed_ratio

MAX_ACTIVE_STRATEGIES = 6
STATS_WINDOW_DAYS = 60

_lock = threading.Lock()


def _local_date(iso: str) -> date:
    return datetime.fromisoformat(iso).astimezone(ZoneInfo(settings.timezone)).date()


def _today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _age_hours(iso: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600


# --------------------------------------------------------------------------- analyse


def video_metrics(stats) -> dict:
    if stats is None:
        return {"views": 0, "stayed": None, "avg_pct": None, "score": None}
    stayed = stayed_ratio(stats["views"], stats["engaged_views"], stats["avg_view_percentage"])
    return {
        "views": stats["views"],
        "likes": stats["likes"],
        "stayed": stayed,
        "avg_pct": stats["avg_view_percentage"],
        "score": score_video(stats["views"], stats["engaged_views"], stats["avg_view_percentage"]),
    }


def build_arms(conn, only_active: bool = True) -> tuple[list[Arm], dict[int, int]]:
    where = "WHERE active = 1" if only_active else ""
    arms = {r["id"]: Arm(r["id"]) for r in conn.execute(f"SELECT id FROM strategies {where}")}
    pending: dict[int, int] = {}
    latest = latest_stats_by_video(conn)
    for v in conn.execute("SELECT * FROM videos WHERE status IN ('ready', 'uploading', 'uploaded', 'generating')"):
        if v["strategy_id"] not in arms:
            continue
        m = video_metrics(latest.get(v["id"]))
        old_enough = v["published_at"] and _age_hours(v["published_at"]) >= MIN_AGE_HOURS
        if old_enough and m["score"] is not None:
            arms[v["strategy_id"]].scores.append(m["score"])
        else:
            pending[v["strategy_id"]] = pending.get(v["strategy_id"], 0) + 1
    return list(arms.values()), pending


def strategy_overview(conn) -> list[dict]:
    latest = latest_stats_by_video(conn)
    arms, pending = build_arms(conn, only_active=False)
    arm_by_id = {a.strategy_id: a for a in arms}
    rows = []
    for s in conn.execute("SELECT * FROM strategies ORDER BY active DESC, id"):
        vids = conn.execute("SELECT id FROM videos WHERE strategy_id = ? AND status = 'uploaded'", (s["id"],)).fetchall()
        metrics = [video_metrics(latest.get(v["id"])) for v in vids]
        stayed = [m["stayed"] for m in metrics if m["stayed"] is not None]
        pct = [m["avg_pct"] for m in metrics if m["avg_pct"] is not None]
        arm = arm_by_id[s["id"]]
        rows.append(
            {
                **dict(s),
                "videos": len(vids),
                "total_views": sum(m["views"] for m in metrics),
                "avg_views": round(sum(m["views"] for m in metrics) / len(metrics)) if metrics else 0,
                "stayed": sum(stayed) / len(stayed) if stayed else None,
                "avg_pct": sum(pct) / len(pct) if pct else None,
                "score": arm.mean,
                "scored": arm.n,
                "pending": pending.get(s["id"], 0),
            }
        )
    return rows


# --------------------------------------------------------------------------- taken


def generate_today(force: bool = False) -> int | None:
    """Genereer de video van vandaag (tenzij die er al is)."""
    with _lock:
        with connect() as conn:
            if not force:
                for v in conn.execute("SELECT created_at, status FROM videos WHERE status != 'failed'"):
                    if _local_date(v["created_at"]) == _today():
                        log("Video voor vandaag bestaat al, generatie overgeslagen")
                        return None
            arms, pending = build_arms(conn)
            strategy_id = choose_arm(arms, pending)
            strategy = dict(conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone())
            recent = [r["title"] for r in conn.execute("SELECT title FROM videos ORDER BY id DESC LIMIT 15")]
            video_id = conn.execute(
                "INSERT INTO videos (strategy_id, status, created_at) VALUES (?, 'generating', ?)",
                (strategy_id, now_iso()),
            ).lastrowid
        log(f"Start generatie video #{video_id} met strategie '{strategy['name']}'")

        try:
            try:
                plan = gemini_client.write_video_plan(strategy, recent)
            except Exception as exc:  # tekstmodel is optioneel
                log(f"Plan via Gemini mislukt ({exc}), sjabloon gebruikt", "warning")
                plan = gemini_client.fallback_plan(strategy)
            with connect() as conn:
                conn.execute(
                    "UPDATE videos SET prompt = ?, title = ?, description = ?, tags = ? WHERE id = ?",
                    (plan["prompt"], plan["title"], plan["description"], json.dumps(plan["tags"]), video_id),
                )
            path = gemini_client.generate_video(plan["prompt"], settings.video_dir / f"video_{video_id}.mp4")
            with connect() as conn:
                conn.execute("UPDATE videos SET status = 'ready', file_path = ? WHERE id = ?", (str(path), video_id))
            log(f"Video #{video_id} klaar: {plan['title']}")
            return video_id
        except Exception as exc:
            with connect() as conn:
                conn.execute("UPDATE videos SET status = 'failed', error = ? WHERE id = ?", (str(exc), video_id))
            log(f"Generatie video #{video_id} mislukt: {exc}", "error")
            return None


def upload_today() -> str | None:
    """Upload de oudste klaarstaande video. Genereert eerst een video als er geen klaarstaat."""
    with connect() as conn:
        for v in conn.execute("SELECT published_at FROM videos WHERE status = 'uploaded'"):
            if _local_date(v["published_at"]) == _today():
                log("Vandaag is al een video geüpload, upload overgeslagen")
                return None
        ready = conn.execute("SELECT * FROM videos WHERE status = 'ready' ORDER BY id LIMIT 1").fetchone()
    if ready is None:
        log("Geen video klaar om te uploaden, nu genereren", "warning")
        if generate_today(force=True) is None:
            return None
        return upload_today()

    with _lock:
        with connect() as conn:
            conn.execute("UPDATE videos SET status = 'uploading' WHERE id = ?", (ready["id"],))
        try:
            with connect() as conn:
                strategy = conn.execute("SELECT hashtags FROM strategies WHERE id = ?", (ready["strategy_id"],)).fetchone()
            description = ready["description"]
            if strategy and strategy["hashtags"] and strategy["hashtags"] not in description:
                description = f"{description}\n\n{strategy['hashtags']}".strip()
            youtube_id = youtube_client.upload_video(
                path=ready["file_path"],
                title=ready["title"],
                description=description,
                tags=json.loads(ready["tags"] or "[]"),
            )
            with connect() as conn:
                conn.execute(
                    "UPDATE videos SET status = 'uploaded', youtube_id = ?, published_at = ? WHERE id = ?",
                    (youtube_id, now_iso(), ready["id"]),
                )
            log(f"Video #{ready['id']} geüpload: https://youtube.com/shorts/{youtube_id}")
            return youtube_id
        except Exception as exc:
            with connect() as conn:
                conn.execute("UPDATE videos SET status = 'ready', error = ? WHERE id = ?", (str(exc), ready["id"]))
            log(f"Upload video #{ready['id']} mislukt: {exc}", "error")
            return None


def sync_stats() -> int:
    """Haal weergaven en kijkgedrag op voor recente uploads."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STATS_WINDOW_DAYS)).isoformat()
    with connect() as conn:
        videos = conn.execute(
            "SELECT id, youtube_id, published_at FROM videos WHERE status = 'uploaded' AND published_at >= ?",
            (cutoff,),
        ).fetchall()
    if not videos:
        return 0
    ids = [v["youtube_id"] for v in videos]
    try:
        basic = youtube_client.fetch_basic_stats(ids)
    except Exception as exc:
        log(f"Statistieken ophalen mislukt: {exc}", "error")
        return 0
    try:
        start = min(_local_date(v["published_at"]) for v in videos)
        analytics = youtube_client.fetch_analytics(ids, start, _today())
    except Exception as exc:
        log(f"Analytics ophalen mislukt (alleen basisstatistieken opgeslagen): {exc}", "warning")
        analytics = {}

    with connect() as conn:
        for v in videos:
            b = basic.get(v["youtube_id"], {})
            a = analytics.get(v["youtube_id"], {})
            conn.execute(
                "INSERT INTO stats (video_id, fetched_at, views, likes, comments, shares, subscribers_gained, "
                "engaged_views, avg_view_duration, avg_view_percentage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    v["id"],
                    now_iso(),
                    b.get("views", a.get("views", 0)),
                    b.get("likes", a.get("likes", 0)),
                    b.get("comments", a.get("comments", 0)),
                    a.get("shares"),
                    a.get("subscribersGained"),
                    a.get("engagedViews"),
                    a.get("averageViewDuration"),
                    a.get("averageViewPercentage"),
                ),
            )
    log(f"Statistieken bijgewerkt voor {len(videos)} video's")
    return len(videos)


def evolve_strategies() -> dict:
    """Zet slecht presterende strategieën uit en laat Gemini een nieuwe voorstellen."""
    with connect() as conn:
        arms, _ = build_arms(conn)
        losers = pick_losers(arms)
        for sid in losers:
            conn.execute(
                "UPDATE strategies SET active = 0, notes = notes || ? WHERE id = ?",
                (f"\nUitgezet op {_today()} wegens lage score.", sid),
            )
        overview = [s for s in strategy_overview(conn) if s["scored"] > 0]
        active_count = conn.execute("SELECT COUNT(*) FROM strategies WHERE active = 1").fetchone()[0]

    for sid in losers:
        log(f"Strategie #{sid} uitgezet wegens lage score")

    result = {"disabled": losers, "created": None}
    if not overview:
        log("Nog te weinig data om strategieën bij te sturen")
        return result
    if active_count >= MAX_ACTIVE_STRATEGIES:
        log("Maximaal aantal actieve strategieën bereikt, geen nieuwe voorgesteld")
        return result

    performance = [
        {
            "strategy_id": s["id"],
            "name": s["name"],
            "theme": s["theme"],
            "prompt_template": s["prompt_template"],
            "active": bool(s["active"]),
            "score": round(s["score"], 3),
            "stayed_pct": round(s["stayed"] * 100, 1) if s["stayed"] is not None else None,
            "avg_view_pct": round(s["avg_pct"], 1) if s["avg_pct"] is not None else None,
            "avg_views": s["avg_views"],
            "videos": s["scored"],
        }
        for s in overview
    ]
    try:
        proposal = gemini_client.propose_strategy(performance)
    except Exception as exc:
        log(f"Nieuwe strategie voorstellen mislukt: {exc}", "error")
        return result
    known_ids = {p["strategy_id"] for p in performance}
    parent = proposal.get("based_on_strategy_id")
    with connect() as conn:
        new_id = insert_strategy(
            conn,
            name=proposal["name"],
            theme=proposal["theme"],
            prompt_template=proposal["prompt_template"],
            title_style=proposal.get("title_style", ""),
            hashtags=proposal.get("hashtags", ""),
            parent_id=parent if parent in known_ids else None,
            notes=f"Voorgesteld door Gemini: {proposal.get('reasoning', '')}",
        )
    log(f"Nieuwe strategie #{new_id} '{proposal['name']}': {proposal.get('reasoning', '')}")
    result["created"] = new_id
    return result
