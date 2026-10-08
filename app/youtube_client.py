import os
from datetime import date, datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import settings

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

ANALYTICS_METRICS = [
    "views",
    "engagedViews",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
]


def get_credentials() -> Credentials:
    token = Path(settings.youtube_token_file)
    if not token.exists() and os.getenv("YOUTUBE_TOKEN_JSON"):
        token.write_text(os.environ["YOUTUBE_TOKEN_JSON"])
    if not token.exists():
        raise RuntimeError("Nog niet ingelogd bij YouTube: draai `python -m scripts.youtube_auth`")
    creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.write_text(creds.to_json())
        else:
            raise RuntimeError("YouTube-token ongeldig: draai `python -m scripts.youtube_auth` opnieuw")
    return creds


def is_connected() -> bool:
    try:
        get_credentials()
        return True
    except Exception:
        return False


def upload_video(path: Path, title: str, description: str, tags: list[str], publish_at: datetime | None = None) -> str:
    youtube = build("youtube", "v3", credentials=get_credentials(), cache_discovery=False)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags[:30],
            "categoryId": settings.youtube_category_id,
        },
        "status": {
            "privacyStatus": settings.youtube_privacy,
            "selfDeclaredMadeForKids": False,
            # Verplichte melding voor realistische AI-gegenereerde content.
            "containsSyntheticMedia": True,
        },
    }
    if publish_at is not None:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    return response["id"]


def fetch_basic_stats(youtube_ids: list[str]) -> dict[str, dict]:
    """Realtime tellers uit de Data API (weergaven, likes, reacties)."""
    youtube = build("youtube", "v3", credentials=get_credentials(), cache_discovery=False)
    result = {}
    for i in range(0, len(youtube_ids), 50):
        resp = youtube.videos().list(part="statistics", id=",".join(youtube_ids[i : i + 50])).execute()
        for item in resp.get("items", []):
            s = item["statistics"]
            result[item["id"]] = {
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
            }
    return result


def fetch_analytics(youtube_ids: list[str], start: date, end: date) -> dict[str, dict]:
    """Kijkgedrag uit de YouTube Analytics API (loopt ~1-2 dagen achter)."""
    analytics = build("youtubeAnalytics", "v2", credentials=get_credentials(), cache_discovery=False)
    metrics = list(ANALYTICS_METRICS)
    result: dict[str, dict] = {}
    for i in range(0, len(youtube_ids), 200):
        chunk = youtube_ids[i : i + 200]
        try:
            resp = _query(analytics, chunk, metrics, start, end)
        except HttpError:
            # Oudere API-versies kennen engagedViews niet; probeer zonder.
            metrics = [m for m in metrics if m != "engagedViews"]
            resp = _query(analytics, chunk, metrics, start, end)
        headers = [h["name"] for h in resp.get("columnHeaders", [])]
        for row in resp.get("rows", []):
            values = dict(zip(headers, row))
            result[values.pop("video")] = values
    return result


def _query(analytics, ids: list[str], metrics: list[str], start: date, end: date) -> dict:
    return (
        analytics.reports()
        .query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics=",".join(metrics),
            dimensions="video",
            filters="video==" + ",".join(ids),
            sort="-views",
            maxResults=200,
        )
        .execute()
    )
