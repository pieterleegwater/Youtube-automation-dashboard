"""Eenmalig inloggen bij YouTube. Opent een browser en slaat token.json op.

Gebruik:  python -m scripts.youtube_auth
Op een server zonder browser:  python -m scripts.youtube_auth --console
"""

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import settings
from app.youtube_client import SCOPES


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(settings.youtube_client_secret, SCOPES)
    open_browser = "--console" not in sys.argv
    creds = flow.run_local_server(port=8085, open_browser=open_browser, access_type="offline", prompt="consent")
    Path(settings.youtube_token_file).write_text(creds.to_json())
    print(f"Ingelogd. Token opgeslagen in {settings.youtube_token_file}")


if __name__ == "__main__":
    main()
