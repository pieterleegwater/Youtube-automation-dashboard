# YouTube ASMR Shorts automatisering

Een dashboard dat elke dag automatisch:

1. **13:00** een ASMR-video genereert met Gemini (Veo), op basis van een gekozen strategie;
2. **16:00** die video uploadt naar YouTube als Short;
3. **elke 3 uur** weergaven en kijkgedrag ophaalt (hoeveel mensen bleven kijken of wegswipeten, gemiddeld bekeken %);
4. **elke maandag** strategieën bijstuurt: zwakke strategieën gaan uit en Gemini stelt een nieuwe voor op basis van wat goed werkt.

Alle tijden en intervallen staan in `.env`.

## Hoe de strategie wordt bijgestuurd

Elke strategie (thema + promptsjabloon + titelstijl + hashtags) krijgt per video een **score van 0–1**:

| Signaal | Gewicht | Bron |
|---|---|---|
| Bleef kijken (= 100% − weggeswiped) | 45% | `engagedViews / views` (YouTube Analytics) |
| Gemiddeld bekeken % (loops tellen mee, max 150%) | 35% | `averageViewPercentage` |
| Bereik (weergaven, log-schaal, 10k = max) | 20% | `viewCount` |

- Elke dag kiest het systeem een strategie met een *multi-armed bandit* (UCB1): wat goed scoort wordt vaker gekozen, maar nieuwe strategieën krijgen ook een kans.
- Video's tellen pas mee na 48 uur, omdat YouTube Analytics ongeveer 2 dagen achterloopt.
- Elke week gaan strategieën met minimaal 3 video's die onder 70% van de beste scoren uit (er blijven er altijd minimaal 2 over). Gemini analyseert de cijfers en voegt een nieuwe strategie toe (maximaal 6 actief).
- Je kunt strategieën ook zelf toevoegen of aan- en uitzetten in het dashboard.

> **Wegswipen:** de API geeft het exacte "Viewed vs. swiped away" uit YouTube Studio niet. `engagedViews` (weergaven die verder kwamen dan de eerste seconden) is de beste benadering. Als die metriek ontbreekt, gebruikt het dashboard het gemiddeld bekeken %.

## Installatie

Je hebt Python 3.11+ en (alleen bij `CLIPS_PER_VIDEO > 1`) `ffmpeg` nodig.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 1. Gemini API-key
Maak een key aan op <https://aistudio.google.com/apikey> en zet die in `.env` als `GEMINI_API_KEY`.
Voor Veo-videogeneratie heb je een betaald (billing-enabled) project nodig. Controleer in AI Studio welke Veo-modelnaam je kunt gebruiken en zet die in `VEO_MODEL`.

### 2. YouTube-koppeling
1. Ga naar <https://console.cloud.google.com/>, maak een project en zet deze API's aan: **YouTube Data API v3** en **YouTube Analytics API**.
2. Stel het *OAuth consent screen* in (type External). Voeg jezelf toe als testgebruiker.
3. Maak onder *Credentials* een **OAuth client ID** van het type **Desktop app**, download de JSON en sla die op als `client_secret.json` in deze map.
4. Log eenmalig in:
   ```bash
   python -m scripts.youtube_auth
   ```
   Kies het kanaal waarop je uploadt. Het token komt in `token.json`.

> Zolang je OAuth-app in "Testing" staat, verloopt het token na 7 dagen. Zet de app op **In production** (verificatie is voor eigen gebruik niet nodig) om dat te voorkomen.
> Video's die je uploadt via een niet-geverifieerd API-project kunnen door YouTube op privé worden gezet. Vraag in dat geval een [API-audit](https://support.google.com/youtube/contact/yt_api_form) aan.

### 3. Starten
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open <http://localhost:8000>. Laat dit proces **continu draaien** (bijv. op een VPS, Raspberry Pi of je pc met `pm2`, `systemd` of Docker), anders worden de geplande taken niet uitgevoerd.

## Kosten en limieten
- **Veo** rekent per seconde gegenereerde video. Met `CLIPS_PER_VIDEO=1` maak je één clip van ongeveer 8 seconden per dag.
- **YouTube API-quota**: een upload kost ongeveer 1600 van de standaard 10.000 eenheden per dag. Statistieken ophalen kost bijna niets.
- Uploads worden gemarkeerd als **AI-gegenereerd** (`containsSyntheticMedia`). YouTube verplicht dat voor realistische AI-content.

## Projectstructuur
```
app/
  main.py            dashboard (FastAPI) + knoppen
  scheduler.py       dagelijkse planning
  pipeline.py        genereren → uploaden → statistieken → bijsturen
  strategy.py        score en strategiekeuze (bandit)
  gemini_client.py   Veo-video's + prompts/titels/strategievoorstellen
  youtube_client.py  upload + Data/Analytics API
  templates/         dashboard-HTML
scripts/youtube_auth.py  eenmalig inloggen bij YouTube
tests/               pytest
```

Tests draaien: `pip install pytest httpx && pytest`
