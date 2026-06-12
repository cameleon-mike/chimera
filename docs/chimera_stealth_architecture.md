# CHIMERA STEALTH — Architecture Technique
Version 1.0 — 7 juin 2026
Module indépendant, pilotable par agent
=================================================

## IDENTITÉ

Chimera Stealth est un module de scraping furtif indépendant
intégré dans Chimera comme outil d'escalade ultime.

Il se distingue des autres tools par :
- Stack Firefox (Camoufox) au lieu de Chromium → TLS fingerprint différent
- Analyse de sécurité pré-scrape (caniscrape + wafw00f)
- Résolution de CAPTCHA via NopeCHA (optionnel)
- Interface utilisateur dédiée avec historique des runs
- Pilotable par agent via l'interface HTTP standard de Chimera

Position dans la chaîne d'escalade :
    scrapy (risk < 0.2)
    crawl4ai (risk 0.5)
    screenshot/Playwright Chromium (risk 0.8)
    camoufox/STEALTH (risk > 0.8 + TLS fingerprint détecté)  ← CE MODULE
    bypass_waf/FlareSolverr (Cloudflare JS challenge pur)

---

## SCHÉMA MENTAL DU PROCESSUS

### Vue de l'agent qui pilote Stealth

```
AGENT (Cameleon ou script)
    │
    ▼
POST /run-tool {"tool":"camoufox","url":"...","config":{...}}
    │
    ▼
CHIMERA BRIDGE
    │
    ├─── Phase 1 : SCAN SÉCURITÉ
    │        caniscrape.analyze_url(url)
    │        wafw00f → WAF détecté ?
    │        Retourne : security_map {waf, captcha, tls_fp, difficulty}
    │        → AGENT INFORMÉ : "Security scan complete, difficulty=7/10"
    │
    ├─── Phase 2 : CONFIGURATION CAMOUFOX
    │        Sélection proxy depuis security_map
    │        Profil Firefox (geo, locale, timezone)
    │        Extensions : NopeCHA si captcha=True
    │        → AGENT INFORMÉ : "Camoufox configured, proxy=BE residential"
    │
    ├─── Phase 3 : FETCH
    │        Camoufox Firefox headless
    │        wait_for_load + human_delay
    │        Extraction HTML/Markdown
    │        → AGENT INFORMÉ : "Page loaded, http_status=200, html_len=89234"
    │
    ├─── Phase 4 : EXTRACTION
    │        Universal Extractor (CSS → LLM → Vision)
    │        Validation items
    │        → AGENT INFORMÉ : "Extracted 42 items, 0 errors"
    │
    ├─── Phase 5 : PERSISTANCE
    │        INSERT INTO stealth_runs (SQLite)
    │        POST /epid/ingest si items avec ePID
    │        Rapport JSON + CSV généré
    │        → AGENT INFORMÉ : "Run saved, report available at /stealth/runs/{id}"
    │
    └─── RÉPONSE FINALE
             {
               "run_id": "sr-abc123",
               "status": "success",
               "security_map": {...},
               "total_items": 42,
               "report_url": "/stealth/runs/sr-abc123/report",
               "duration_ms": 12400
             }
```

### Communications détaillées entre composants

```
caniscrape/wafw00f
    → retourne dict security_map
    → stocké dans stealth_runs.security_map (JSON)
    → transmis à l'agent dans le WebSocket/polling progress

ScanSecurityAgent (interne)
    → lit security_map
    → sélectionne proxy tier (residential/datacenter/none)
    → configure Camoufox params
    → écrit dans stealth_runs.config_used (JSON)

CamoufoxRunner
    → reçoit url + config
    → lance Firefox headless (Xvfb sur VPS)
    → retourne {html, markdown, screenshot_path, cookies, http_status}
    → écrit dans stealth_runs.raw_result (JSON)

UniversalExtractor (existant, réutilisé)
    → reçoit markdown
    → cascade CSS → LLM → Vision
    → retourne items[]
    → écrit dans stealth_runs.items_json (JSON)

SQLite stealth_runs table
    → source de vérité pour l'UI historique
    → consultable via /stealth/runs (liste) et /stealth/runs/{id}

epid_stats (existant)
    → alimenté si items avec ePID
    → avg_sell_days se remplit si end_date présente
```

---

## TABLES SQLITE

### stealth_runs

```sql
CREATE TABLE stealth_runs (
    run_id          TEXT PRIMARY KEY,         -- "sr-" + uuid[:8]
    created_at      TEXT NOT NULL,            -- ISO timestamp
    url             TEXT NOT NULL,
    query           TEXT,                     -- terme recherché si applicable
    source          TEXT,                     -- "vinted"|"ebay"|"2ememain"|"custom"
    status          TEXT DEFAULT 'running',   -- running|success|error|captcha_blocked
    duration_ms     INTEGER,
    security_map    TEXT,                     -- JSON : {waf, captcha, difficulty, ...}
    config_used     TEXT,                     -- JSON : config Camoufox utilisée
    http_status     INTEGER,
    html_len        INTEGER,
    items_count     INTEGER DEFAULT 0,
    items_json      TEXT,                     -- JSON array des items extraits
    raw_markdown    TEXT,                     -- markdown page (pour debug)
    report_path     TEXT,                     -- path vers CSV/JSON report
    error_msg       TEXT,                     -- null si success
    agent_id        TEXT,                     -- "cameleon"|"manual"|"cron"
    ingest_done     INTEGER DEFAULT 0         -- 1 si POST /epid/ingest effectué
);

CREATE INDEX idx_stealth_runs_created ON stealth_runs(created_at DESC);
CREATE INDEX idx_stealth_runs_source ON stealth_runs(source);
CREATE INDEX idx_stealth_runs_status ON stealth_runs(status);
```

---

## ENDPOINTS BRIDGE

### POST /stealth/run

Lance un run Stealth complet.

```
Body :
{
  "url": "https://www.vinted.fr/catalog?search_text=wacom",
  "query": "wacom intuos pro",
  "source": "vinted",
  "config": {
    "proxy_country": "BE",       // BE|FR|DE|GB|NL
    "captcha_solver": false,     // true → NopeCHA requis
    "wait_ms": 3000,
    "max_pages": 1,
    "ingest": true               // auto-ingest vers epid_stats
  },
  "agent_id": "cameleon"         // qui appelle
}

Réponse (synchrone, polling ou WebSocket) :
{
  "run_id": "sr-abc123",
  "status": "success",
  "security": {
    "waf": "cloudflare",
    "captcha": false,
    "difficulty": 4,
    "recommendation": "camoufox + residential"
  },
  "result": {
    "http_status": 200,
    "html_len": 89234,
    "items_count": 42,
    "duration_ms": 12400
  },
  "report": {
    "json_url": "/stealth/runs/sr-abc123/report.json",
    "csv_url":  "/stealth/runs/sr-abc123/report.csv"
  }
}
```

### GET /stealth/runs

Liste l'historique des runs.

```
Query params :
  limit=20 (défaut)
  offset=0
  source=vinted|ebay|...
  status=success|error|...

Réponse :
{
  "total": 47,
  "runs": [
    {
      "run_id": "sr-abc123",
      "created_at": "2026-06-07T14:30:00Z",
      "query": "wacom intuos pro",
      "source": "vinted",
      "status": "success",
      "items_count": 42,
      "duration_ms": 12400,
      "difficulty": 4
    },
    ...
  ]
}
```

### GET /stealth/runs/{run_id}

Détail complet d'un run.

```
Réponse : tous les champs stealth_runs
+ security_map détaillé
+ items[] complets
+ liens téléchargement rapport
```

### GET /stealth/runs/{run_id}/report.json
### GET /stealth/runs/{run_id}/report.csv

Téléchargement direct du rapport (FileResponse).

### GET /stealth/status/{run_id}

Polling du statut pendant un run long.

```
{
  "run_id": "sr-abc123",
  "status": "running",
  "phase": "fetch",              // scan|configure|fetch|extract|persist
  "phase_progress": "Page loading...",
  "elapsed_ms": 4200
}
```

---

## INTERFACE UTILISATEUR — PAGE STEALTH

### Layout général

```
┌─────────────────────────────────────────────────────┐
│  CHIMERA  [Search] [Deals] [Database] [Dashboard]   │
│           [Settings] [STEALTH ←]                    │
├─────────────────────────────────────────────────────┤
│                                                     │
│  STEALTH RUNS                    [+ NEW RUN]        │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │ ACTIVE RUN — sr-abc123                       │  │
│  │ vinted.fr "wacom intuos" ████████░░ 80%      │  │
│  │ Phase: fetch · 8.4s elapsed                  │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  HISTORIQUE                                         │
│  ┌──────┬──────────┬─────────┬──────┬──────────┐  │
│  │ ID   │ Query    │ Source  │Items │ Status    │  │
│  ├──────┼──────────┼─────────┼──────┼──────────┤  │
│  │ abc1 │ wacom    │ vinted  │  42  │ ✅ BUY x3 │  │
│  │ def2 │ gopro    │ ebay    │ 176  │ ✅ BUY x8 │  │
│  │ ghi3 │ custom   │ custom  │   0  │ ❌ captcha│  │
│  └──────┴──────────┴─────────┴──────┴──────────┘  │
│  (rows cliquables → page détail run)               │
└─────────────────────────────────────────────────────┘
```

### Page détail d'un run (clic sur une row)

```
┌─────────────────────────────────────────────────────┐
│  ← RETOUR    RUN sr-abc123                          │
│  vinted.fr · 2026-06-07 14:30 · 12.4s              │
├──────────────────┬──────────────────────────────────┤
│  SÉCURITÉ        │  RÉSULTATS                       │
│  WAF: Cloudflare │  Items: 42                       │
│  CAPTCHA: ✗      │  BUY: 3 · OFFER: 8 · SKIP: 31   │
│  Difficulté: 4/10│  ePID coverage: 18%              │
│  Proxy: BE       │  Meilleur deal: 80€ →BUY conf=0.8│
│  Tool: Camoufox  │                                  │
├──────────────────┴──────────────────────────────────┤
│  ITEMS                                              │
│  ┌──────────────────────────┬───────┬──────────┐   │
│  │ Title                    │ Price │ Decision │   │
│  ├──────────────────────────┼───────┼──────────┤   │
│  │ Wacom Intuos Pro M       │  85€  │ ✅ BUY   │   │
│  │ Wacom Intuos Pro L       │ 150€  │ 🟡 OFFER │   │
│  └──────────────────────────┴───────┴──────────┘   │
├─────────────────────────────────────────────────────┤
│  [⬇ TÉLÉCHARGER JSON]  [⬇ TÉLÉCHARGER CSV]        │
└─────────────────────────────────────────────────────┘
```

---

## STRUCTURE DES FICHIERS

```
tools/camoufox_runner/
    __init__.py
    scan_security.py       ← caniscrape + wafw00f → security_map
    run_camoufox.py        ← Camoufox Firefox fetch → HTML/markdown
    captcha.py             ← NopeCHA intégration (optionnel)
    stealth_agent.py       ← orchestrateur 5 phases

bridge/
    app.py                 ← +5 endpoints /stealth/*
    schemas.py             ← StealthRunRequest, StealthRunResponse, etc.
    ui/
        index.html         ← +onglet STEALTH (Alpine.js)

storage/
    risk_db.sqlite         ← +table stealth_runs
    stealth_reports/       ← CSV + JSON par run_id
        sr-abc123/
            report.json
            report.csv
            screenshot.png (optionnel)

tests/
    test_scan_security.py  (8 tests)
    test_camoufox_runner.py (8 tests)
    test_stealth_agent.py  (10 tests)
    test_stealth_endpoints.py (8 tests)
    test_stealth_ui.py     (4 tests)
```

---

## OPTIMISATIONS POUR L'AGENT

### Ce que l'agent doit savoir pour utiliser Stealth efficacement

1. Appeler /probe/{domain} AVANT /stealth/run pour éviter
   Stealth sur des sites faciles (risk < 0.5 → utiliser
   crawl4ai, pas Stealth qui est plus lent).

2. Passer source= pour que le rapport soit contextualisé
   et que l'ingest vers epid_stats soit correct.

3. Utiliser ingest=true par défaut — chaque run Stealth
   enrichit automatiquement epid_stats.

4. Stealth est lent (10-30s par page). Ne pas l'appeler
   en boucle. Le cron ScrapingAgent l'appelle 1x/jour
   sur les sources bloquées.

5. Polling via /stealth/status/{run_id} toutes les 2s
   pour des runs > 10s. Timeout client suggéré : 120s.

6. Si status="captcha_blocked" → retry avec
   captcha_solver=true (NopeCHA requis, coût API).

### Interface agent optimale

```python
# Dans ChimeraClient (Cameleon)
async def stealth_run(self, url, query=None, source="custom",
                      proxy_country="BE", ingest=True):
    # Lance le run
    run = await self.post("/stealth/run", {
        "url": url, "query": query, "source": source,
        "config": {"proxy_country": proxy_country, "ingest": ingest},
        "agent_id": "cameleon"
    })
    run_id = run["run_id"]

    # Polling jusqu'à completion
    while True:
        status = await self.get(f"/stealth/status/{run_id}")
        if status["status"] in ["success", "error", "captcha_blocked"]:
            break
        await asyncio.sleep(2)

    # Résultat final
    return await self.get(f"/stealth/runs/{run_id}")
```

---

## DÉPENDANCES

```
camoufox          → pip install camoufox + playwright install firefox
caniscrape        → pip install caniscrape
wafw00f           → pip install wafw00f
xvfb              → apt-get install xvfb (headless display VPS)
nopecha           → optionnel, clé API requise
```

Vérification avant install :
```bash
pip install camoufox caniscrape wafw00f
python3 -c "import camoufox; print(camoufox.__version__)"
python3 -c "import caniscrape; print('caniscrape ok')"
python3 -c "from wafw00f.main import WAFFleX; print('wafw00f ok')"
playwright install firefox
```

---

## CONTRAINTES ABSOLUES

1. Module indépendant — ne pas modifier les tools existants
2. Interface HTTP identique aux autres tools (même auth Bearer)
3. Camoufox headless uniquement (VPS sans affichage → Xvfb)
4. Rapport CSV/JSON toujours généré, même si 0 items
5. stealth_runs jamais supprimé — historique permanent
6. NopeCHA optionnel — Stealth fonctionne sans
7. Pas de 500 non géré — toujours retourner status=error structuré
