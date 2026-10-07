import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from google import genai
from google.genai import types

from .config import settings

POLL_SECONDS = 10
VIDEO_TIMEOUT_SECONDS = 15 * 60


def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY ontbreekt in .env")
    return genai.Client(api_key=settings.gemini_api_key)


def _json_call(prompt: str) -> dict:
    response = _client().models.generate_content(
        model=settings.text_model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=1.0),
    )
    return json.loads(response.text)


def write_video_plan(strategy: dict, recent_titles: list[str]) -> dict:
    """Laat Gemini een concrete videoprompt + titel/beschrijving maken binnen de strategie."""
    prompt = f"""Je bent een producer van een YouTube Shorts ASMR-kanaal.
Maak EEN nieuwe video binnen deze strategie:
- Thema: {strategy["theme"]}
- Prompt-sjabloon (vul placeholders tussen {{}} creatief in en varieer details): {strategy["prompt_template"]}
- Titelstijl: {strategy["title_style"]}
- Hashtags: {strategy["hashtags"]}

Recente titels (niet herhalen): {json.dumps(recent_titles[:15], ensure_ascii=False)}

Regels: de videoprompt is Engels, visueel concreet, verticaal 9:16, met ASMR-geluid, zonder tekst in beeld,
en de eerste seconde moet direct pakkend zijn (tegen wegswipen). Titel max 70 tekens.
Antwoord als JSON: {{"prompt": str, "title": str, "description": str, "tags": [str]}}"""
    plan = _json_call(prompt)
    return {
        "prompt": plan["prompt"],
        "title": plan["title"][:100],
        "description": plan.get("description", ""),
        "tags": plan.get("tags", []),
    }


def fallback_plan(strategy: dict) -> dict:
    """Plan zonder tekstmodel: placeholders worden vervangen door hun naam."""
    prompt = re.sub(r"\{(\w+)\}", r"\1", strategy["prompt_template"])
    return {
        "prompt": prompt,
        "title": f"{strategy['name']} ASMR #shorts",
        "description": f"{strategy['name']}\n\n{strategy['hashtags']}",
        "tags": [t.lstrip("#") for t in strategy["hashtags"].split()],
    }


def _generate_clip(prompt: str, out_path: Path) -> None:
    client = _client()
    operation = client.models.generate_videos(
        model=settings.veo_model,
        prompt=prompt,
        config=types.GenerateVideosConfig(
            aspect_ratio="9:16",
            resolution=settings.video_resolution,
            number_of_videos=1,
        ),
    )
    deadline = time.monotonic() + VIDEO_TIMEOUT_SECONDS
    while not operation.done:
        if time.monotonic() > deadline:
            raise TimeoutError("Veo-generatie duurde te lang")
        time.sleep(POLL_SECONDS)
        operation = client.operations.get(operation)
    if operation.error:
        raise RuntimeError(f"Veo-fout: {operation.error}")
    videos = operation.response.generated_videos if operation.response else None
    if not videos:
        raise RuntimeError("Veo gaf geen video terug (mogelijk geblokkeerd door safety filters)")
    video = videos[0].video
    client.files.download(file=video)
    video.save(str(out_path))


def generate_video(prompt: str, out_path: Path, clips: int | None = None) -> Path:
    """Genereer een video; bij meerdere clips worden ze met ffmpeg aan elkaar geplakt."""
    clips = clips or settings.clips_per_video
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if clips <= 1:
        _generate_clip(prompt, out_path)
        return out_path
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is nodig voor CLIPS_PER_VIDEO > 1")
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i in range(clips):
            part = Path(tmp) / f"part{i}.mp4"
            _generate_clip(f"{prompt} (shot {i + 1} of {clips}, continuous scene)", part)
            parts.append(part)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out_path)],
            check=True,
            capture_output=True,
        )
    return out_path


def propose_strategy(performance: list[dict]) -> dict:
    """Vraag Gemini om een nieuwe strategie op basis van wat wel en niet werkt."""
    prompt = f"""Je analyseert een YouTube Shorts ASMR-kanaal. Per strategie zie je de gemiddelde score (0-1),
het percentage kijkers dat bleef kijken (rest swipete weg), gemiddeld bekeken percentage en weergaven:
{json.dumps(performance, ensure_ascii=False, indent=2)}

Bedenk EEN nieuwe strategie die voortbouwt op wat het best werkt en vermijdt wat slecht scoort
(bijv. sterkere hook in de eerste seconde, ander materiaal, andere kleuren of geluiden).
prompt_template is Engels, mag placeholders tussen {{}} bevatten, verticaal 9:16, ASMR-geluid, geen tekst in beeld.
Antwoord als JSON: {{"name": str (Nederlands, kort), "theme": str, "prompt_template": str,
"title_style": str, "hashtags": str, "based_on_strategy_id": int, "reasoning": str (Nederlands, 1-2 zinnen)}}"""
    return _json_call(prompt)
