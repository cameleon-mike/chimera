# CHIMERA — Roadmap Claude Code
### SecondPulse · 6 Sessions · 5 Steps chacune
### Protocole : Step Report obligatoire avant chaque passage

---

## PROTOCOLE GÉNÉRAL

### Règle absolue
**Aucun passage au step suivant sans step report approuvé par Mike.**

### À chaque fin de step, Claude Code fournit :

```
═══════════════════════════════════════════════════
STEP REPORT — Session X · Step Y
═══════════════════════════════════════════════════
✅ COMPLÉTÉ
  - Liste précise de ce qui a été fait
  - Fichiers créés / modifiés
  - Commandes testées et résultats

⚠️  POINTS D'ATTENTION
  - Ce qui n'est pas parfait
  - Choix techniques faits et pourquoi

🧪 TESTS À EFFECTUER PAR MIKE
  - Commandes exactes à lancer
  - Output attendu
  - Comment confirmer que ça fonctionne

❓ QUESTIONS / DÉCISIONS REQUISES
  - Ce qui nécessite une décision avant le step suivant

🔜 STEP SUIVANT (aperçu)
  - Ce qui sera fait au prochain step

AUTORISATION : en attente de validation Mike
═══════════════════════════════════════════════════
```

### Mike répond avec son Step Report :

```
═══════════════════════════════════════════════════
STEP REPORT MIKE — Session X · Step Y
═══════════════════════════════════════════════════
✅ TESTS EFFECTUÉS
  - Résultats des tests demandés

🐛 BUGS / ÉCARTS
  - Ce qui ne fonctionne pas comme attendu

✔️  DÉCISIONS
  - Réponses aux questions posées

▶️  AUTORISATION : GO Step Y+1
   (ou : STOP — corrections requises)
═══════════════════════════════════════════════════
```

---

## SESSION 1 — FONDATIONS
### Objectif : environnement Ubuntu + bridge FastAPI + Scrapy opérationnel

### Step 1.1 — Setup Ubuntu + environnement Python
- Vérification Ubuntu 24.04 LTS + packages système
- Création structure `/opt/scraper-pack/` complète
- Création virtualenv Python 3.11 + installation dépendances de base
- Setup Redis (service systemd)
- Création `scraper.env` avec variables d'environnement
- Création `Makefile` avec commandes de base

**Livrables :** structure complète, pyproject.toml avec toutes deps, `redis-cli ping` → PONG, `make check-env` valide.

### Step 1.2 — Bridge FastAPI — squelette + auth
- `bridge/app.py`, `bridge/auth.py`, `bridge/schemas.py`, `bridge/logging_setup.py`
- Tests démarrage uvicorn + auth Bearer token

**Livrables :** bridge `127.0.0.1:8080`, `/health` OK, `/run-tool` sans token → 401, avec token → 200.

### Step 1.3 — Redis Queue (RQ) + Worker de base
- `bridge/queue.py` wrapper RQ 3 priorités, `bridge/workers.py` dispatch
- `/status/{job_id}` et `/result/{job_id}` fonctionnels

**Livrables :** worker RQ démarre, job queued → started → finished, result récupérable.

### Step 1.4 — Scrapy Runner — spider adaptatif
- Projet Scrapy complet `tools/scrapy_runner/project/`
- Spiders : `adaptive.py`, `api_json.py`
- Middlewares : `rotate_ua.py`, `human_delay.py`
- `run_scrapy.py` wrapper CLI JSON→JSON

**Livrables :** test sur `https://httpbin.org/get` → JSON valide + fichier dans `storage/results/`.

### Step 1.5 — Intégration Bridge ↔ Scrapy + systemd
- Connexion bridge → `run_scrapy.py` via worker dispatch
- Units systemd : `scraper-bridge.service`, `scraper-worker@.service`
- Première ligne `audit.jsonl`

**Livrables :** test end-to-end HTTP, services systemd valides, audit log écrit.

---

## SESSION 2 — RECONNAISSANCE + RÉSEAU + ANTI-DÉTECTION
### Objectif : security probe → proxy rotation → fingerprint cohérent → risk scoring

### Step 2.1 — Security Probe + Proxy Pool foundation

> **Principe : reconnaître avant d'agir.** La probe tourne en premier sur
> chaque domaine cible. Son output alimente directement la sélection du
> proxy tier, le fingerprint profile et la politique d'escalade tool.

**Security Probe**
- `tools/probe/security_probe.py` — script probe complet
- Collecte par domaine : headers HTTP, certificat TLS, cookies, risk_score,
  vendors WAF détectés (Cloudflare/Akamai/DataDome/PerimeterX/hCaptcha…),
  features de sécurité (CSP, HSTS, X-Frame-Options…)
- `GET /probe/{domain}` dans le bridge — déclenche une probe, retourne JSON
- Résultat écrit dans `risk_db.sqlite` (table `domain_probe`)
- `probe` ajouté comme 6e tool dans `tool_manifest.json` avec ses params
- **Cameleon appelle `/probe/{domain}` avant tout `/run-tool`** pour
  récupérer la recommandation de tool et de proxy tier

**Proxy Pool foundation**
- `network/proxy_pool/pool.json` — tiers (DC/residential/ISP/mobile)
- `network/proxy_pool/rotator.py` — `ProxyRotator` avec `risk_db.sqlite`
- `network/proxy_pool/healthcheck.py` — vérification proxies actifs
- Middleware Scrapy `rotate_proxy.py`
- **La probe alimente le rotator** : Cloudflare détecté → tier résidentiel
  recommandé automatiquement dans la réponse `/probe`

**Livrables**
- `GET /probe/ebay.com` → JSON avec risk_score, vendors_detected, tls,
  features, `recommendation.tool` + `recommendation.proxy_tier`
- `GET /probe/httpbin.org` → risk_score < 0.2, tool recommandé = "scrapy"
- Les 2 recommandations sont différentes (tool + proxy tier)
- `rotator.pick("ebay.com")` retourne proxy résidentiel basé sur probe
- `rotator.report(proxy, host, status)` écrit dans risk_db
- `/risk/{domain}` retourne l'historique probe

### Step 2.2 — Fingerprint cohérent
- 20+ profils UA réels, headers complets, geo profiles
- Validation cohérence UA/Sec-CH-UA/Accept-Language/TZ/viewport

### Step 2.3 — Risk Scoring Middleware
- Détection Cloudflare/Akamai/DataDome/PerimeterX
- Score 0→1 calculé par réponse, écrit dans `risk_db.sqlite`
- `GET /risk/{domain}` retourne historique agrégé

### Step 2.4 — Human behavior module
- Délais log-normaux, `SessionManager` Redis
- Même `session_id` → même UA + même proxy

### Step 2.5 — Politique d'escalade automatique
- Table d'escalade dans le bridge (risk ≥ 0.5 → crawl4ai, ≥ 0.8 → screenshot)
- `LEGAL.md` initial

---

## SESSION 3 — OUTILS BROWSER
### Objectif : Crawl4AI + Screenshot Runner opérationnels

### Step 3.1 — Playwright setup + stealth patches
- Patches webdriver, canvas noise, WebGL, plugins, languages
- Installation `fingerprint-generator` Node

### Step 3.2 — Screenshot Runner complet
- `run_screenshot.py` complet, profils persistants par `profile_id`
- Humanisation : scroll Bézier, hover, rotation viewport

### Step 3.3 — Crawl4AI Runner
- `run_crawl4ai.py` avec `JsonCssExtractionStrategy`
- Test extraction `books.toscrape.com`, intégration bridge

### Step 3.4 — Firecrawl self-hosted (Docker)
- `docker-compose.yml` Firecrawl + Playwright microservice + Redis
- `run_firecrawl.py` + intégration bridge

### Step 3.5 — WAF Bypass (FlareSolverr)
- Docker FlareSolverr + `run_bypass.py`
- Intégration bridge `"tool":"bypass_waf"`, mise à jour `LEGAL.md`

---

## SESSION 4 — SECONDPULSE INTEGRATION
### Objectif : connecter le scraper au pipeline SecondPulse existant

### Step 4.1 — eBay scraper via Chimera
- Spider `ebay_browse.py` remplace curl_cffi, support pagination Browse API
- Migration `secondpulse_v9.py` pour appeler le bridge

### Step 4.2 — WatchCount via Screenshot
- Spider `watchcount.py`, escalade auto Scrapy → Screenshot si reCAPTCHA
- Extraction dates via Groq vision, peuplement `end_date`

### Step 4.3 — 2ememain.be scraper
- Spider `vinted_2ememain.py`, intégration `secondpulse_v9.py` menu `1.2`
- CSV compatible eBay scraper

### Step 4.4 — Multi-source aggregator
- `bridge/aggregator.py` parallèle eBay + 2ememain
- Déduplication fuzzy, CSV unifié avec colonne `source`
- Menu `1.3` dans `secondpulse_v9.py`

### Step 4.5 — Temps de vente moyen (sold dates pipeline)
- Activation `avg_sell_days` dans `epid_stats`
- Calcul `end_date - start_date`, quartiles
- Affichage fiche ePID

---

## SESSION 5 — LANGGRAPH INTEGRATION
### Objectif : Chimera comme tool natif du pipeline LangGraph SecondPulse

### Step 5.1 — ops_agent → Chimera bridge
- Tool LangGraph `chimera_tool` wrapper HTTP, polling `/status` async

### Step 5.2 — vision_agent ↔ screenshot pipeline
- `vision_agent` → screenshot → Claude API vision
- Cache 24h des screenshots, intégration deal evaluation

### Step 5.3 — scraping_agent hebdomadaire
- `scraping_agent` LangGraph lance multi-source weekly via aggregator
- Stockage direct SQLite, scheduler cron/APScheduler

### Step 5.4 — decision_agent pricing
- Décision buy/offer/skip vs médiane ePID, seuils par catégorie
- Marge auto, raisonnement référence quartiles

### Step 5.5 — navigator_agent ↔ risk awareness
- `navigator_agent` consulte `/risk/{domain}` avant chaque scrape
- Sélection auto tool selon historique, backpressure si queue > 50
- Dashboard React UI onglet "Chimera"

---

## SESSION 6 — PRODUCTION ET HARDENING
### Objectif : sécurité, monitoring, résilience, déploiement final

### Step 6.1 — Nginx + TLS + IP whitelist
- Reverse proxy `infra/nginx/scraper.conf`, TLS Let's Encrypt, rate limiting
- IP whitelist moteur IA uniquement

### Step 6.2 — Audit log + storage chiffrement
- Rotation logrotate, audit.jsonl 100 lignes valides
- gocryptfs/LUKS sur `storage/`

### Step 6.3 — Monitoring + alerting
- Dashboard RQ (rq-dashboard), `/metrics` Prometheus
- Alertes : queue > 100, risk moyen > 0.6, worker down

### Step 6.4 — Résilience et chaos testing
- Tests : Redis down, worker crash, proxy pool vide, Firecrawl down
- Comportement gracieux documenté pour 4 failure modes

### Step 6.5 — Documentation finale + Makefile complet
- README installation < 30 commandes
- Makefile complet : start/stop/test/logs/reset
- LEGAL.md final, CHANGELOG.md, archivage `roadmap_completed.md`

**Livrables :** `make start` tout démarre, `make test` passe, `make logs` temps réel, doc complète.

---

## RÉCAPITULATIF DES SESSIONS

| Session | Focus       | Livrables clés                                        |
|---------|-------------|-------------------------------------------------------|
| S1      | Fondations  | Bridge FastAPI + Scrapy + systemd                     |
| S2      | Réseau      | Proxy rotation + fingerprint + risk score             |
| S3      | Browser     | Crawl4AI + Screenshot + Firecrawl                     |
| S4      | SecondPulse | eBay + 2ememain + sold dates + avg_sell_days          |
| S5      | LangGraph   | Chimera tool + agents intégrés + pricing              |
| S6      | Production  | TLS + audit + monitoring + chaos + docs               |

**Total : 30 steps · 30 step reports Mike · Progression 100% contrôlée**

---

## NOTES POUR CLAUDE CODE

1. **Ne jamais passer au step suivant** de sa propre initiative.
2. **Chaque step report doit être exhaustif** — Mike doit pouvoir reproduire sans assistance.
3. Si un step prend plus de temps que prévu → le dire dans le report, pas de raccourcis silencieux.
4. **Sécurité** : jamais de tokens/passwords hardcodés — toujours via `.env`.
5. **Tests** : chaque livrable a une commande de vérification explicite.
6. **Compatibilité** : chaque session doit laisser le système dans un état fonctionnel — pas de "en cours".
7. **`secondpulse_v9.py` reste opérationnel** à chaque session — pas de régression.
8. **Cameleon est le cerveau, Chimera est l'outil** : chaque setting, option, aspect configurable du scraper doit être facilement identifiable par cameleon (introspection via `/openapi.json`, `/capabilities`, `tool_manifest.json`).
