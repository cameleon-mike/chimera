# CHIMERA STEALTH — Roadmap de Build
Version 1.0 — 7 juin 2026
=================================================

## PRÉREQUIS AVANT TOUT BUILD

Valider que les dépendances s'installent sur le VPS :

```bash
cd /workspaces/chimera
source .venv/bin/activate
pip install camoufox caniscrape wafw00f
python3 -c "import camoufox; print(camoufox.__version__)"
python3 -c "import caniscrape; print('ok')"
python3 -c "from wafw00f.main import WAFFleX; print('ok')"
playwright install firefox
apt-get install -y xvfb  # headless display pour Firefox sur VPS
```

Si caniscrape ou wafw00f échouent → reporter ces dépendances
et implémenter scan_security.py avec /probe/{domain} existant.

---

## STEP S1 — Scan Sécurité + SQLite stealth_runs

### Objectif
Module de scan + table SQLite. Aucun browser, aucun endpoint.

### Livrables
- tools/camoufox_runner/__init__.py
- tools/camoufox_runner/scan_security.py
    ScanSecurity class :
        scan(url) -> dict security_map
        _caniscrape_scan(url) -> dict
        _wafw00f_scan(url) -> dict
        _merge_results() -> dict
        Fallback vers /probe/{domain} si caniscrape absent
- Migration SQLite stealth_runs (dans bridge/app.py _init_risk_db)
- tests/test_scan_security.py (8 tests)

### Critère done
pytest tests/test_scan_security.py → 8 passed
make test → pas de régression

### Commit
git commit -m "Stealth S1 — Scan security + SQLite stealth_runs"

### Estimation
40-60k tokens. Haiku pour tout.

---

## STEP S2 — Camoufox Runner

### Objectif
Firefox headless qui fetche une URL et retourne HTML/markdown.
Indépendant du bridge.

### Livrables
- tools/camoufox_runner/run_camoufox.py
    CamoufoxRunner class :
        __init__(self, proxy_config, settings)
        fetch(url, wait_ms=3000) -> dict
            {html, markdown, http_status, cookies, duration_ms}
        _build_proxy_url(proxy_country) -> str
        _html_to_markdown(html) -> str (réutilise BeautifulSoup)
        Xvfb wrapper pour VPS headless
        human_delay() entre actions
        Fallback : si Camoufox échoue → retourne error dict, jamais exception

    CLI : JSON stdin → JSON stdout (même pattern que run_scrapy.py)
    echo '{"url":"https://vinted.fr/...","proxy_country":"BE"}'       | python -m tools.camoufox_runner.run_camoufox

- tests/test_camoufox_runner.py (8 tests — mocks Firefox)

### Critère done
pytest tests/test_camoufox_runner.py → 8 passed
Test live :
    echo '{"url":"https://www.vinted.fr/catalog?search_text=wacom"}'       | .venv/bin/python3 -m tools.camoufox_runner.run_camoufox       | python3 -c "import sys,json;d=json.load(sys.stdin);print('http:',d.get('http_status'),'len:',d.get('html_len'))"
    Attendu : http_status=200, html_len > 1000

### Commit
git commit -m "Stealth S2 — Camoufox Firefox runner"

### Estimation
60-80k tokens. Sonnet pour la config Xvfb + Camoufox (jugement requis).

---

## STEP S3 — Stealth Agent (orchestrateur 5 phases)

### Objectif
Assembler scan + fetch + extract + persist en une classe unique.

### Livrables
- tools/camoufox_runner/stealth_agent.py
    StealthAgent class :
        __init__(self, settings, db_path)
        run(url, query, source, config) -> dict
            Phase 1 : ScanSecurity.scan(url)
            Phase 2 : configure Camoufox selon security_map
            Phase 3 : CamoufoxRunner.fetch(url)
            Phase 4 : UniversalExtractor.extract(html, markdown)
            Phase 5 : persist dans stealth_runs + générer rapport
            Retourne dict complet (run_id, status, security, result, report)

        _configure_camoufox(security_map) -> dict config
        _persist_run(run_id, data) -> None
        _generate_report(run_id, items) -> dict {json_path, csv_path}

    Rapport CSV : title, price, source, url, decision, confidence
    Rapport JSON : run complet + items[]

- storage/stealth_reports/ (créé automatiquement)
- tests/test_stealth_agent.py (10 tests)

### Critère done
pytest tests/test_stealth_agent.py → 10 passed
make test → pas de régression
Test live :
    .venv/bin/python3 -c "
    from tools.camoufox_runner.stealth_agent import StealthAgent
    from bridge.config import get_settings
    agent = StealthAgent(get_settings(), 'storage/risk_db.sqlite')
    result = agent.run('https://www.vinted.fr/catalog?search_text=wacom',
                       query='wacom', source='vinted',
                       config={'proxy_country':'BE','ingest':True})
    print('status:', result['status'])
    print('items:', result['result']['items_count'])
    "

### Commit
git commit -m "Stealth S3 — StealthAgent orchestrateur"

### Estimation
70-90k tokens. Sonnet pour les décisions d'orchestration.

---

## STEP S4 — Endpoints Bridge + Polling

### Objectif
Exposer Stealth via le bridge HTTP. Pilotable par agent.

### Livrables
- bridge/app.py — 5 nouveaux endpoints :
    POST /stealth/run
    GET  /stealth/runs
    GET  /stealth/runs/{run_id}
    GET  /stealth/runs/{run_id}/report.json  (FileResponse)
    GET  /stealth/runs/{run_id}/report.csv   (FileResponse)
    GET  /stealth/status/{run_id}            (polling)

- bridge/schemas.py — nouveaux modèles :
    StealthRunRequest
    StealthRunResponse
    StealthRunSummary (pour la liste)
    StealthStatusResponse

- tool_manifest.json — bump + section stealth

- tests/test_stealth_endpoints.py (8 tests)

### Critère done
pytest tests/test_stealth_endpoints.py → 8 passed
make test → pas de régression
Test live :
    export TOKEN=$(grep BRIDGE_AUTH_TOKEN scraper.env | cut -d= -f2)
    curl -s -X POST -H "Authorization: Bearer $TOKEN"       -H "Content-Type: application/json"       -d '{"url":"https://www.vinted.fr/catalog?search_text=wacom",
           "query":"wacom","source":"vinted",
           "config":{"proxy_country":"BE","ingest":true}}'       http://127.0.0.1:8080/stealth/run       | python3 -c "import sys,json;d=json.load(sys.stdin);
        print('run_id:',d.get('run_id'),'status:',d.get('status'),'items:',d.get('result',{}).get('items_count'))"

    curl -s -H "Authorization: Bearer $TOKEN"       http://127.0.0.1:8080/stealth/runs       | python3 -c "import sys,json;d=json.load(sys.stdin);print('total runs:',d.get('total'))"

### Commit
git commit -m "Stealth S4 — Bridge endpoints /stealth/*"

### Estimation
60-80k tokens. Haiku pour les endpoints (pattern connu).

---

## STEP S5 — Interface UI Stealth

### Objectif
Onglet STEALTH dans l'UI existante (bridge/ui/index.html).
Page liste + page détail + téléchargement rapport.

### Livrables
- bridge/ui/index.html — enrichi avec onglet STEALTH :
    Page liste : table rows cliquables, active run bar
    Page détail : security_map + items + téléchargement
    New Run modal : form URL + query + source + proxy_country
    Alpine.js polling /stealth/status/{run_id} toutes 2s
    Progress bar pendant run actif

- tests/test_stealth_ui.py (4 tests)
    GET /ui → onglet STEALTH présent dans HTML
    GET /stealth/runs → 200 (données pour la table)
    Page détail accessible → /stealth/runs/{run_id}
    FileResponse CSV → Content-Type text/csv

### Critère done
make test → pas de régression
Test browser : https://shovelos.com/ui → onglet STEALTH visible
New Run → wacom sur vinted → progress bar → résultat
Click row → page détail → télécharger CSV

### Commit
git commit -m "Stealth S5 — UI onglet STEALTH"

### Estimation
50-70k tokens. Haiku pour le HTML/Alpine.js.

---

## STEP S6 — NopeCHA + Intégration chaîne d'escalade (optionnel)

### Objectif
Intégrer NopeCHA pour résolution CAPTCHA automatique.
Positionner Camoufox dans la chaîne d'escalade officielle.

### Condition
NopeCHA API key disponible. Step optionnel — Stealth
fonctionne sans pour le MVP.

### Livrables
- tools/camoufox_runner/captcha.py
    NopeCHASolver class :
        setup_extension(api_key, extension_dir) -> str
        is_captcha_present(page) -> bool
        wait_for_solve(page, timeout=30) -> bool

- Intégration dans la chaîne d'escalade bridge/app.py :
    risk > 0.8 + tls_fingerprint détecté → tool=camoufox
    (entre screenshot Playwright et FlareSolverr)

- tool_manifest.json — escalation_policy mise à jour

### Commit
git commit -m "Stealth S6 — NopeCHA + escalade chain integration"

### Estimation
40-60k tokens. Haiku.

---

## CALENDRIER SUGGÉRÉ

```
Jour 1 : S1 + S2 (scan sécurité + Camoufox runner)
Jour 2 : S3 + S4 (agent + endpoints)
Jour 3 : S5 (UI)
Jour 4 : S6 si NopeCHA disponible (optionnel)
```

Total : 3-4 jours de build.
Estimation tokens : 280-440k tokens total (6 steps).

---

## RÈGLES DU BUILD

1. Chaque step commence par : pip install + import test des dépendances
2. Si caniscrape absent → fallback vers /probe/{domain} existant (documenter)
3. Camoufox headless uniquement → Xvfb requis sur VPS
4. Pas de modification des tools existants
5. git push après chaque step sans exception
6. make test → pas de régression à chaque step
7. Test live obligatoire avant GO du step suivant
