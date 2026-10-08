import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    theme TEXT NOT NULL,
    prompt_template TEXT NOT NULL,
    title_style TEXT NOT NULL DEFAULT '',
    hashtags TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    parent_id INTEGER REFERENCES strategies(id),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL REFERENCES strategies(id),
    status TEXT NOT NULL,              -- generating | ready | uploading | uploaded | failed
    prompt TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    file_path TEXT,
    youtube_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    fetched_at TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    shares INTEGER,
    subscribers_gained INTEGER,
    engaged_views INTEGER,
    avg_view_duration REAL,
    avg_view_percentage REAL
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
"""

SEED_STRATEGIES = [
    {
        "name": "Kinetisch zand snijden",
        "theme": "kinetic sand cutting",
        "prompt_template": "Extreme close-up of a sharp knife slowly slicing through a block of {color} kinetic sand "
        "on a clean pastel surface, satisfying crumbling texture, crisp ASMR crunch sounds, soft studio lighting, "
        "vertical 9:16, no people, no text.",
        "title_style": "Kort, rustgevend, 1 emoji, eindigt op #shorts",
        "hashtags": "#asmr #satisfying #kineticsand #shorts",
    },
    {
        "name": "Glazen fruit snijden",
        "theme": "glass fruit cutting",
        "prompt_template": "Macro shot of a knife cutting a translucent glass {fruit} on a wooden board, "
        "glassy crackling ASMR sounds, glittering reflections, shallow depth of field, vertical 9:16, no text.",
        "title_style": "Nieuwsgierig makend, vraagvorm",
        "hashtags": "#asmr #glassfruit #satisfying #shorts",
    },
    {
        "name": "Zeep snijden",
        "theme": "soap cutting",
        "prompt_template": "Close-up of hands cutting colorful layered soap cubes with a sharp blade, "
        "crisp crunchy ASMR sounds, flakes falling, bright clean lighting, vertical 9:16, no text.",
        "title_style": "Beschrijvend, max 6 woorden",
        "hashtags": "#asmr #soapcutting #oddlysatisfying #shorts",
    },
    {
        "name": "Regen op het raam",
        "theme": "cozy rain ambience",
        "prompt_template": "Cozy cinematic shot from inside a warm dimly lit room looking at heavy rain on a window at "
        "night, {detail}, gentle rain and distant thunder ASMR sounds, vertical 9:16, no people, no text.",
        "title_style": "Sfeervol, 'slaap'/'ontspan' woorden",
        "hashtags": "#asmr #rainsounds #relax #shorts",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0] == 0:
            for s in SEED_STRATEGIES:
                insert_strategy(conn, **s)


def insert_strategy(conn, *, name, theme, prompt_template, title_style="", hashtags="", parent_id=None, notes="") -> int:
    cur = conn.execute(
        "INSERT INTO strategies (name, theme, prompt_template, title_style, hashtags, parent_id, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, theme, prompt_template, title_style, hashtags, parent_id, notes, now_iso()),
    )
    return cur.lastrowid


def log(message: str, level: str = "info") -> None:
    with connect() as conn:
        conn.execute("INSERT INTO logs (ts, level, message) VALUES (?, ?, ?)", (now_iso(), level, message))


def latest_stats_by_video(conn) -> dict[int, sqlite3.Row]:
    rows = conn.execute(
        "SELECT s.* FROM stats s JOIN (SELECT video_id, MAX(id) AS id FROM stats GROUP BY video_id) m ON s.id = m.id"
    ).fetchall()
    return {r["video_id"]: r for r in rows}
