"""Eenmalig inloggen bij YouTube en token.json opslaan.

Op je eigen computer (opent een browser):
    python -m scripts.youtube_auth

Zonder browser op deze machine, in twee stappen:
    python -m scripts.youtube_auth --start
        → open de getoonde link, log in. Je komt op een pagina die niet laadt
          (http://localhost:8085/?...). Kopieer die volledige adresregel.
    python -m scripts.youtube_auth --finish "<gekopieerde adresregel>"

De OAuth-client komt uit client_secret.json, of uit de omgevingsvariabelen
YOUTUBE_OAUTH_CLIENT_ID en YOUTUBE_OAUTH_CLIENT_SECRET.
"""

import json
import os
import sys
from pathlib import Path

from google_auth_oauthlib.flow import Flow, InstalledAppFlow

from app.config import settings
from app.youtube_client import SCOPES

REDIRECT_URI = "http://localhost:8085/"
PENDING_FILE = Path(".oauth_pending.json")


def _client_config() -> dict:
    secret_file = Path(settings.youtube_client_secret)
    if secret_file.exists():
        return json.loads(secret_file.read_text())
    client_id, client_secret = os.getenv("YOUTUBE_OAUTH_CLIENT_ID"), os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET")
    if not (client_id and client_secret):
        sys.exit(f"{secret_file} niet gevonden en YOUTUBE_OAUTH_CLIENT_ID/YOUTUBE_OAUTH_CLIENT_SECRET niet gezet.")
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _save(creds) -> None:
    Path(settings.youtube_token_file).write_text(creds.to_json())
    print(f"Ingelogd. Token opgeslagen in {settings.youtube_token_file}")


def main(argv: list[str]) -> None:
    if "--start" in argv:
        flow = Flow.from_client_config(_client_config(), SCOPES, redirect_uri=REDIRECT_URI)
        url, state = flow.authorization_url(access_type="offline", prompt="consent")
        PENDING_FILE.write_text(json.dumps({"state": state, "code_verifier": flow.code_verifier}))
        print(url)
    elif "--finish" in argv:
        pending = json.loads(PENDING_FILE.read_text())
        flow = Flow.from_client_config(
            _client_config(),
            SCOPES,
            redirect_uri=REDIRECT_URI,
            state=pending["state"],
            code_verifier=pending["code_verifier"],
        )
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # redirect gaat naar http://localhost
        flow.fetch_token(authorization_response=argv[argv.index("--finish") + 1])
        PENDING_FILE.unlink()
        _save(flow.credentials)
    else:
        flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
        _save(flow.run_local_server(port=8085, access_type="offline", prompt="consent"))


if __name__ == "__main__":
    main(sys.argv[1:])
