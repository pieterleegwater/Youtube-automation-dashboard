"""Opdrachtregel voor GitHub Actions (of cron). Gebruik: python -m app.cli <opdracht>

Opdrachten:
  daily                   video van vandaag genereren en (ingepland) uploaden
  generate | upload | stats | evolve
  render <map>            statisch dashboard schrijven naar <map>/index.html
  toggle-strategy <id>    strategie aan/uit zetten
  add-strategy <naam> <thema> <prompt> [hashtags]
"""

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import pipeline
from .config import settings
from .dashboard import dashboard_context
from .db import connect, init_db, insert_strategy, log

APP_DIR = Path(__file__).parent
DAYS = {"mon": "maandag", "tue": "dinsdag", "wed": "woensdag", "thu": "donderdag", "fri": "vrijdag", "sat": "zaterdag", "sun": "zondag"}


def render(out_dir: str) -> Path:
    out = Path(out_dir)
    (out / "static").mkdir(parents=True, exist_ok=True)
    shutil.copy(APP_DIR / "static" / "chart.umd.js", out / "static" / "chart.umd.js")
    env = Environment(loader=FileSystemLoader(APP_DIR / "templates"), autoescape=select_autoescape(["html"]))
    context = dashboard_context()
    repo = os.getenv("GITHUB_REPOSITORY", "")
    hm = lambda t: f"{t[0]:02d}:{t[1]:02d}"  # noqa: E731
    context.update(
        static_mode=True,
        static_prefix="static/",
        updated_at=datetime.now(ZoneInfo(settings.timezone)).strftime("%d-%m %H:%M"),
        actions_url=f"https://github.com/{repo}/actions" if repo else "#",
        schedule=[
            ("Video genereren + inplannen", "dagelijks ~12:00"),
            ("Live op YouTube", f"dagelijks {hm(settings.upload_time)}"),
            ("Statistieken ophalen", "elke 6 uur"),
            ("Strategieën bijsturen", f"{DAYS.get(settings.evolve_day, settings.evolve_day)} ochtend"),
        ],
    )
    path = out / "index.html"
    path.write_text(env.get_template("index.html").render(**context), encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    init_db()
    command, args = argv[0], argv[1:]
    if command == "daily":
        pipeline.generate_today()
        result = pipeline.upload_today()
        print(result or "geen upload")
    elif command == "generate":
        print(pipeline.generate_today(force="--force" in args))
    elif command == "upload":
        print(pipeline.upload_today())
    elif command == "stats":
        print(pipeline.sync_stats())
    elif command == "evolve":
        print(pipeline.evolve_strategies())
    elif command == "render":
        print(render(args[0] if args else "site"))
    elif command == "toggle-strategy":
        with connect() as conn:
            conn.execute("UPDATE strategies SET active = 1 - active WHERE id = ?", (int(args[0]),))
        log(f"Strategie #{args[0]} aan/uit gezet")
    elif command == "add-strategy":
        name, theme, prompt = args[:3]
        hashtags = args[3] if len(args) > 3 else "#asmr #satisfying #shorts"
        with connect() as conn:
            new_id = insert_strategy(conn, name=name, theme=theme, prompt_template=prompt, hashtags=hashtags)
        log(f"Strategie #{new_id} '{name}' handmatig toegevoegd")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
