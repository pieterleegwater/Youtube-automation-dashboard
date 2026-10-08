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

## Snel aan de slag: draaien op GitHub Actions (gratis, geen server nodig)

GitHub voert alles automatisch uit:

- **Dagelijks rond 12:00** maakt het de video en uploadt die als privé, ingepland voor **16:00**. YouTube zet de video op dat tijdstip zelf live, dus het tijdstip klopt altijd precies. Rond 14:00 volgt nog een tweede poging, die alleen iets doet als de eerste mislukte.
- **Elke 6 uur** haalt het de statistieken op, en **elke maandag** stuurt het de strategieën bij.
- De gegevens (`dashboard.db`) en het dashboard (`index.html`) staan op de branch **`state`**. Dat dashboard kun je via GitHub Pages openen.

Eenmalig instellen:

1. **Gemini API-key**: maak die aan op <https://aistudio.google.com/apikey>. Zet billing aan, want Veo is betaald.
2. **Google Cloud** (<https://console.cloud.google.com/>):
   1. Maak een project en zet **YouTube Data API v3** en **YouTube Analytics API** aan.
   2. Stel het *OAuth consent screen* in (type External) en zet het op **In production**. Anders verloopt de login na 7 dagen.
   3. Maak onder *Credentials* een **OAuth client ID** van het type **Desktop app**. Noteer de Client ID en het Client secret.
3. **YouTube-login**. Op een computer met Python:
   ```bash
   pip install -r requirements.txt
   YOUTUBE_OAUTH_CLIENT_ID=... YOUTUBE_OAUTH_CLIENT_SECRET=... python -m scripts.youtube_auth
   ```
   Dit maakt `token.json` aan. Zonder browser op die machine gebruik je `--start` en `--finish` (zie `scripts/youtube_auth.py`).
4. **GitHub-secrets**: ga naar *Settings → Secrets and variables → Actions → New repository secret* en voeg toe:
   - `GEMINI_API_KEY`: je Gemini-key;
   - `YOUTUBE_TOKEN_JSON`: de volledige inhoud van `token.json`.

   Optioneel kun je onder het tabblad *Variables* `VEO_MODEL`, `TEXT_MODEL` of `UPLOAD_TIME` aanpassen.
5. **Testen**: ga naar *Actions → ASMR automatisering → Run workflow*, kies `daily` en klik op Run.
6. **Dashboard online**: kies na de eerste run onder *Settings → Pages* de optie *Deploy from a branch*, branch `state`, map `/ (root)`. Je dashboard staat dan op `https://<gebruiker>.github.io/<repo>/`.

Handmatige acties gaan via *Run workflow*:

| Actie | Wat het doet |
|---|---|
| `daily` | Video van vandaag maken en inplannen |
| `generate` | Alleen een video maken |
| `upload` | Alleen uploaden |
| `stats` | Statistieken ophalen |
| `evolve` | Strategieën bijsturen |
| `toggle-strategy` | Strategie aan- of uitzetten (vul het id in) |
| `add-strategy` | Eigen strategie toevoegen (vul naam, thema en prompt in) |

> Let op: deze repository is **openbaar**. De dashboarddata op de `state`-branch (titels, prompts, weergaven) is dus voor iedereen zichtbaar. Je sleutels blijven geheim in GitHub Secrets.

## Alternatief: zelf draaien met live dashboard

### Installatie

Je hebt Python 3.11+ en (alleen bij `CLIPS_PER_VIDEO > 1`) `ffmpeg` nodig.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

#### 1. Gemini API-key
Maak een key aan op <https://aistudio.google.com/apikey> en zet die in `.env` als `GEMINI_API_KEY`.
Voor Veo-videogeneratie heb je een betaald (billing-enabled) project nodig. Controleer in AI Studio welke Veo-modelnaam je kunt gebruiken en zet die in `VEO_MODEL`.

#### 2. YouTube-koppeling
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

#### 3. Starten
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
  main.py            live dashboard (FastAPI) + knoppen
  cli.py             opdrachten voor GitHub Actions + statisch dashboard
  dashboard.py       gegevens voor het dashboard
  scheduler.py       dagelijkse planning
  pipeline.py        genereren → uploaden → statistieken → bijsturen
  strategy.py        score en strategiekeuze (bandit)
  gemini_client.py   Veo-video's + prompts/titels/strategievoorstellen
  youtube_client.py  upload + Data/Analytics API
  templates/         dashboard-HTML
scripts/youtube_auth.py  eenmalig inloggen bij YouTube
.github/workflows/automation.yml  de dagelijkse planning op GitHub Actions
tests/               pytest
```

Tests draaien: `pip install pytest httpx && pytest`
