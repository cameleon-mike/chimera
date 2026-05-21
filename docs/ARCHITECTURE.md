# CHIMERA — Scraper Hybride Architecture
### SecondPulse · Ubuntu Production Stack

---

## Vue d'ensemble

Architecture d'un scraper hybride orienté production, piloté par un moteur IA externe via un bridge HTTP.

**Principe de séparation des responsabilités :**

| Composant | Rôle |
|---|---|
| Scraper Pack | Exécute · Log · Retourne |
| Moteur IA | Stratégie · OCR · Décisions · Fallback |

---

## 1. Structure du dépôt

```
/opt/scraper-pack/
├── bridge/                      # API REST exposée au moteur IA
│   ├── app.py                   # FastAPI principal
│   ├── queue.py                 # Wrapper RQ/Celery
│   ├── auth.py                  # Token Bearer
│   └── schemas.py               # Pydantic models
├── tools/
│   ├── scrapy_runner/           # HTTP rapide, APIs, HTML
│   ├── firecrawl_runner/        # JS rendering, contenu lourd
│   ├── crawl4ai_runner/         # Navigateur réel, LLM-ready
│   ├── screenshot_runner/       # Fallback ultime → PNG
│   └── waf_bypass/              # FlareSolverr (Docker)
├── network/
│   ├── proxy_pool/              # Rotation IP, healthcheck
│   ├── fingerprints/            # UA pool, headers, geo profiles
│   └── tor/                     # Fallback optionnel
├── storage/
│   ├── results/                 # JSON par job_id
│   ├── screenshots/
│   ├── cookies/                 # Sessions persistantes par domaine
│   └── risk_db.sqlite           # Score réputation site/IP/profil
├── logs/
│   ├── bridge.log
│   ├── tools.log
│   └── audit.jsonl              # Immuable, append-only
└── infra/
    ├── systemd/
    ├── nginx/                   # Reverse proxy + TLS
    └── env/
```

---

## 2. Dépendances

### Système (Ubuntu 24.04 LTS)

```bash
sudo apt update && sudo apt install -y \
  python3.11 python3.11-venv python3-pip \
  nodejs npm \
  curl jq git build-essential \
  redis-server sqlite3 \
  chromium-browser firefox-esr \
  fonts-liberation fonts-noto-cjk fonts-noto-color-emoji \
  xvfb tesseract-ocr \
  docker.io docker-compose-v2
```

### Python (`pyproject.toml`)

```
scrapy>=2.11
scrapy-playwright>=0.0.34
playwright>=1.45
fastapi>=0.110
uvicorn[standard]>=0.29
pydantic>=2.6
httpx[http2]>=0.27
redis>=5.0
rq>=1.16
fake-useragent>=1.5
crawl4ai>=0.3
tenacity>=8.2
structlog>=24.1
python-dotenv>=1.0
```

### Node (`package.json`)

```
playwright + playwright-extra
puppeteer + puppeteer-extra
puppeteer-extra-plugin-stealth
fingerprint-injector + fingerprint-generator
```

---

## 3. Les 4 outils principaux

### 3.1 Scrapy — HTTP rapide

- Sites peu protégés, APIs, parsing HTML statique
- AutoThrottle activé, DOWNLOAD_DELAY ≥ 1
- Middlewares : rotate UA, rotate proxy, human delay, risk signals
- Spider adaptatif avec CSS selectors configurables par job

### 3.2 Firecrawl (self-hosted Docker)

- JS rendering, contenu dynamique, crawling multi-pages
- Modes : `scrape` / `crawl` / `map`
- Output : markdown + HTML
- Playwright microservice intégré avec support proxy

### 3.3 Crawl4AI — Navigateur réel

- Rendu navigateur Chromium/Firefox réaliste
- Extraction structurée via `JsonCssExtractionStrategy`
- Output LLM-ready (markdown propre)
- Support proxy, UA custom, JS injection

### 3.4 Screenshot Runner — Fallback ultime

- Playwright persistent context (profils navigateur sur disque)
- Output : PNG full-page
- L'OCR/extraction est faite par le moteur IA (pas dans le scraper)
- Humanisation : scroll multi-ticks, délais irréguliers

---

## 4. Bridge API (FastAPI)

### Endpoints

```
POST /run-tool          → Lance un job (enqueue RQ)
GET  /status/{job_id}   → Statut du job
GET  /result/{job_id}   → Résultat JSON
GET  /risk/{domain}     → Score réputation domaine
GET  /download/{job_id} → Téléchargement PNG
```

### Structure de requête

```json
{
  "tool": "scrapy | firecrawl | crawl4ai | screenshot | bypass_waf",
  "url": "https://...",
  "config": { "..." },
  "priority": "low | normal | high",
  "callback_url": null
}
```

### Authentification

Bearer token via `Authorization` header. Token stocké dans `scraper.env`. Pas d'exposition publique — IP whitelist nginx.

---

## 5. Paramètres contrôlables par l'IA

| Catégorie | Paramètres |
|---|---|
| **Outil** | scrapy / firecrawl / crawl4ai / screenshot / bypass_waf |
| **Cible** | url, mode, max_depth, follow_links, limit |
| **Extraction** | css selectors, JSON schema, only_main_content |
| **Navigateur** | browser type, headless, viewport, wait_for, js_code |
| **Réseau** | proxy_pool (DC / residential / ISP / mobile), geo_profile |
| **Identité** | user-agent, headers complets, locale, timezone, fingerprint |
| **Session** | session_id, cookies persistants, login strategy |
| **Comportement** | human delays, scroll, hover, random walk |
| **Risque** | respect_robots, switch outil, burn profile, change proxy |
| **Sortie** | format (json/markdown/html), screenshot, output_file |
| **Queue** | priority, callback_url |

---

## 6. Anti-scraping — Parades

### 6.1 Réseau et origine

- **Proxy rotation** par tiers : DC (90% trafic normal) → résidentiel → ISP statique → mobile 4G
- **Cohérence géo** : chaque requête = n-uplet `(IP, UA, Accept-Language, TZ, viewport)` cohérent, jamais randomisé indépendamment
- **Cap par domaine** : max 2–3 requêtes parallèles vers le même host

### 6.2 En-têtes HTTP

- Pool de ~50 profils complets capturés depuis de vrais navigateurs
- Ordre des headers respecté (certains WAF fingerprintent l'ordre)
- Persistance par `session_id` — même profil jusqu'à signal d'épuisement
- Aucun header "trahison" (`X-Forwarded-For`, `X-Requested-With` mal placés)

### 6.3 Fingerprint navigateur

```javascript
// Patches systématiques injectés à l'init
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
// Canvas noise cohérent par session (pas par requête)
// WebGL vendor/renderer cohérents avec l'UA
// navigator.plugins réaliste
```

- Anti-TLS (JA3/JA4) : `curl_cffi` pour Scrapy, Playwright pour browser
- `fingerprint-generator` + `fingerprint-injector` (Apify) pour fingerprints dataset-réels

### 6.4 Comportement humain

```python
# Délais log-normaux (réaliste vs délai constant)
def human_pause(mean=1.5, jitter=0.7):
    delay = max(0.2, random.lognormvariate(math.log(mean), jitter))
    time.sleep(delay)
```

- Mouvements souris en courbes de Bézier (pas ligne droite)
- Scroll multi-ticks irréguliers
- Hover aléatoire sur liens
- Pagination non linéaire (éviter `?page=1..N` séquentiel)
- 1 fetch sur 10 vers une page "inutile" (homepage, about) pour casser le pattern

### 6.5 Session et authentification

- Cookies + localStorage persistants par `profile_id`
- IP sticky tant que session active (ISP/résidentiel statique)
- Max N logins/jour par compte, délai > 6h entre logins
- Cookie invalidé → `risk++` sur profil, pas de re-login immédiat

---

## 7. Score de risque et escalade

### Niveaux

| Score | État | Action |
|---|---|---|
| 0.0 – 0.2 | ✅ OK | Continuer Scrapy |
| 0.2 – 0.5 | ⚠️ Suspect | Ralentir (delay ×2) + rotation UA |
| 0.5 – 0.8 | 🔶 Challenge | Switcher → Crawl4AI + proxy résidentiel |
| 0.8 – 1.0 | 🔴 Block | Screenshot + OCR externe · Marquer profil/IP "burn" |

### Détection des vendors

```python
BLOCK_INDICATORS = {
    "cloudflare":  ["__cf_chl_", "cf-mitigated", "Just a moment"],
    "akamai":      ["_abck", "akamai-bot"],
    "perimeterx":  ["px-captcha", "_px3"],
    "datadome":    ["datadome", "dd-protected"],
    "captcha":     ["g-recaptcha", "hcaptcha", "turnstile"],
}
```

---

## 8. Workflow complet

```
Moteur IA
    │
    ├── POST /run-tool  →  Bridge FastAPI  →  Redis Queue
    │                                              │
    │                                        RQ Workers
    │                                              │
    │                          ┌───────────────────┤
    │                          │                   │
    │                     Scrapy (HTTP)      Crawl4AI (browser)
    │                          │                   │
    │                      risk < 0.5         risk 0.5–0.8
    │                          │
    │                    Firecrawl (JS)
    │                          │
    │                   risk 0.5–0.8
    │                          │
    │                   Screenshot (PNG)
    │                          │
    │                   risk 0.8–1.0
    │                          │
    └── GET /result  ←  JSON structuré
```

---

## 9. Sécurité et infrastructure

### systemd units

```ini
# scraper-bridge.service
[Service]
User=scraper
ExecStart=/opt/scraper-pack/.venv/bin/uvicorn bridge.app:app \
  --host 127.0.0.1 --port 8080 --workers 2
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
```

```bash
# Workers templatés (N instances)
systemctl enable --now scraper-worker@{1..4}
```

### Nginx

- Reverse proxy + TLS Let's Encrypt
- IP whitelist moteur IA uniquement
- Pas d'exposition publique du bridge

### Audit log

```jsonl
{"ts":"2026-05-19T10:11:12Z","job_id":"a1b2","tool":"scrapy",
 "url":"https://x.com","status":200,"latency_ms":342,
 "proxy":"residential-fr-007","risk_score":0.12,"event":"ok"}
```

- Fichier `audit.jsonl` immuable (append-only)
- Rotation logrotate + archive distante
- Jamais de PII non nécessaire — storage chiffré (LUKS ou gocryptfs)

---

## 10. Best practices pour le moteur IA

1. **Commencer doux** — Scrapy en premier, escalader seulement si `risk ≥ 0.5`
2. **session_id cohérent** — même ID pour toutes les requêtes d'une même "visite"
3. **Respecter risk_score** — ne pas re-tenter un domaine "burn" dans la même heure
4. **Rotation cohérente** — si changement d'IP → changer aussi UA, locale, viewport simultanément
5. **Cap de concurrence** — max 2–3 requêtes parallèles vers le même host
6. **Actions de bruit** — homepage / about entre extractions ciblées
7. **Burn rapide** — supprimer le profil dès qu'un cookie est invalidé
8. **robots.txt** — `respect_robots: true` par défaut, override logué en audit
9. **OCR** — toujours envoyer `screenshot_path + url + context` au modèle multimodal
10. **Backpressure** — si `/status` > 50 jobs en attente, ralentir l'envoi côté IA

---

## 11. Limites connues

- **Cloudflare Turnstile / Akamai Bot Manager / DataDome** modernes : invaincus sans service payant (FlareSolverr devient lui-même détecté)
- **Screenshot + OCR** : latence 2–10s/page + coût non nul
- **Profils navigateurs neufs** : nécessitent "vieillissement" — un profil neuf est un signal
- **Actions humaines réelles** : login SMS, KYC, Arkose Labs → impossible à automatiser proprement
- **ToS** : maintenir `LEGAL.md` avec liste blanche/noire de domaines

---

## 12. Exemples de requêtes

### API JSON simple (Scrapy)

```json
{
  "tool": "scrapy",
  "url": ["https://api.example.com/v1/products?page=1"],
  "config": {
    "spider": "api_json",
    "settings": {"DOWNLOAD_DELAY": "0.5"},
    "proxy_pool": "datacenter",
    "respect_robots": true,
    "session_id": "sess_a1b2"
  },
  "priority": "normal"
}
```

### Page e-commerce dynamique (Firecrawl)

```json
{
  "tool": "firecrawl",
  "url": "https://shop.example.com/p/123",
  "config": {
    "mode": "scrape",
    "formats": ["markdown", "html"],
    "wait_for": 2500,
    "only_main": true
  }
}
```

### Extraction structurée JS-heavy (Crawl4AI)

```json
{
  "tool": "crawl4ai",
  "url": "https://news.example.com/latest",
  "config": {
    "browser": "chromium",
    "wait_for": "css:.article-list",
    "schema": {
      "name": "articles",
      "baseSelector": "article.post",
      "fields": [
        {"name": "title", "selector": "h2", "type": "text"},
        {"name": "url",   "selector": "a",  "type": "attribute", "attribute": "href"},
        {"name": "date",  "selector": "time","type": "attribute", "attribute": "datetime"}
      ]
    },
    "proxy": {"server": "http://res-fr.proxy:8000"}
  }
}
```

### Page bloquée → Screenshot pour OCR (Screenshot Runner)

```json
{
  "tool": "screenshot",
  "url": "https://protected.example.com/dashboard",
  "config": {
    "profile_id": "persona_007_fr",
    "headless": true,
    "wait_until": "networkidle",
    "wait_ms": 4000,
    "full_page": true,
    "locale": "fr-FR",
    "tz": "Europe/Paris"
  }
}
```

### Vérification de risque avant attaque

```
GET /risk/example.com

→ {
    "domain": "example.com",
    "last_24h": {
      "requests": 142, "blocks": 3, "captchas": 1,
      "avg_risk": 0.18, "vendors_seen": ["cloudflare"]
    },
    "recommendation": "start_with:crawl4ai"
  }
```

---

## Conclusion

Chimera est une architecture **incrémentale et modulaire** :

```
Phase 1  →  Scrapy + Bridge + 1 proxy pool
Phase 2  →  + Screenshot runner
Phase 3  →  + Crawl4AI
Phase 4  →  + Firecrawl self-hosted (le plus lourd)
```

Chaque outil est **isolé et remplaçable** — c'est ce qui rend le pack durable face à l'évolution des protections WAF.

> *"A tool to scrape them all"*
