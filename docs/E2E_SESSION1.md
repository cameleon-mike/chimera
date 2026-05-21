# Chimera — Session 1 E2E validation

Validation manuelle de bout en bout de Session 1 (Steps 1.1 → 1.5).
Cible : prouver que le câblage `bridge FastAPI → RQ → worker → subprocess Scrapy → result JSON` fonctionne sur un vrai HTTP roundtrip.

À lancer **après** que le Step Report 1.5 est validé, avant tout commit unique Session 1.

---

## 0. Pré-requis

```bash
cd /workspaces/chimera

# Redis dispo
redis-cli ping                  # → PONG

# Token bridge présent
grep -q ^BRIDGE_AUTH_TOKEN scraper.env && echo "token OK"

# 43 tests pytest verts
make test                       # → 43 passed
```

Si l'un de ces checks échoue → STOP, fix avant E2E.

---

## 1. Démarrage — schéma simple (1 commande)

`make start` lance Redis + bridge + worker en background (PID files dans `.bridge.pid` / `.worker.pid`).

```bash
cd /workspaces/chimera
make start
```

Output attendu (ordre approximatif) :
```
Redis started (or already running).
Bridge started (PID xxxx) on http://127.0.0.1:8080
  app log:     /workspaces/chimera/logs/bridge.log
  uvicorn log: /workspaces/chimera/logs/uvicorn.log
Worker started (PID yyyy) — log: /workspaces/chimera/logs/worker.log
```

Sanity health :
```bash
curl -fsS http://127.0.0.1:8080/health | jq .
```
Attendu :
```json
{"status":"ok","manifest_version":"0.3.0","bridge_version":"0.1.0"}
```

---

## 2. Démarrage — schéma 3 terminaux (debug live)

Si tu veux observer les logs en direct au lieu du mode background :

### Terminal 1 — Worker en foreground
```bash
cd /workspaces/chimera
source .venv/bin/activate
rq worker --url "$REDIS_URL" --with-scheduler high normal low
```
Garde-le ouvert pour voir chaque `job_started` / `job_finished` en direct.

### Terminal 2 — Bridge en foreground
```bash
cd /workspaces/chimera
source .venv/bin/activate
# Recharge env
set -a; . scraper.env; set +a
uvicorn bridge.app:app --host 127.0.0.1 --port 8080 --log-level info
```

### Terminal 3 — Tests curl (voir §3)

> ⚠️ **Conflit avec mode background** : si tu as déjà lancé `make start`, fais `make stop` AVANT de démarrer les processes foreground manuels — sinon collision sur le port 8080 ou conflit de PID files.

---

## 3. Tests E2E — curl /run-tool → /status → /result

Token export (une fois par terminal de tests) :
```bash
cd /workspaces/chimera
export TOKEN=$(grep ^BRIDGE_AUTH_TOKEN scraper.env | cut -d= -f2)
echo "Token loaded: ${TOKEN:0:8}..."   # vérif partielle, sans tout afficher
```

### Test 1 — POST job scrapy

```bash
curl -X POST http://127.0.0.1:8080/run-tool \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "tool":"scrapy",
    "url":"https://httpbin.org/get",
    "config":{"spider":"api_json","respect_robots":false},
    "priority":"normal"
  }'
```

Attendu (HTTP 200) :
```json
{"job_id":"<16-hex>","status":"queued"}
```

Capture le `job_id` :
```bash
JOB_ID="<colle ici les 16 hex retournés>"
```

### Test 2 — Status (polling)

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/status/$JOB_ID
```

Lance la commande plusieurs fois à 0,5–1 s d'intervalle. La séquence attendue est :
1. `{"job_id":"...","status":"queued",...}`
2. `{"job_id":"...","status":"started",...,"started_at":"..."}`
3. `{"job_id":"...","status":"finished",...,"finished_at":"..."}`

Si tu vois `{"status":"failed"}` → §6 troubleshooting.

### Test 3 — Result

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/result/$JOB_ID | jq .
```

Attendu :
```json
{
  "job_id":"...",
  "status":"finished",
  "result":{
    "tool":"scrapy",
    "url":"https://httpbin.org/get",
    "http_status":200,
    "proxy":null,
    "risk_score":0.10,
    "items":[{...}],
    "_meta":{
      "spider":"api_json",
      "job_id":"...",
      "started_at":"...",
      "finished_at":"...",
      "duration_ms":<int>,
      "item_count":1
    }
  }
}
```

`items[]` doit contenir au moins 1 élément (le payload JSON renvoyé par httpbin).

### Test 4 — Fichier disque

```bash
ls -la storage/results/${JOB_ID}.json
cat storage/results/${JOB_ID}.json | jq '.items | length'
```

Attendu :
- Fichier présent, ~quelques centaines d'octets.
- `jq` retourne un entier ≥ 1.

### Test 5 — Audit log

```bash
tail -3 logs/audit.jsonl | jq .
```

Attendu : 3 dernières lignes contiennent `run_tool_accepted`, `job_started`, `job_finished` avec le même `job_id`.

---

## 4. Capabilities — vérif manifest live

```bash
curl -fsS http://127.0.0.1:8080/capabilities | jq '.manifest_version, .tools.scrapy.status, .tools.scrapy.params | keys'
```

Attendu :
```
"0.3.0"
"available"
["headers","item_selector","proxy","respect_robots","selectors","session_id","settings","spider"]
```

---

## 5. Arrêt propre

```bash
make stop                # arrête bridge + worker (Redis reste up)
make redis-stop          # si tu veux aussi arrêter Redis
```

---

## 6. Troubleshooting

### Cibles Makefile — référence
| Cible | Effet |
|---|---|
| `make start` | Redis + bridge + worker (background, PID files) — **commande principale** |
| `make stop` | Stoppe worker puis bridge (Redis reste up) |
| `make worker-start` | Lance UN worker seul (utile si bridge déjà up et que tu veux un 2ᵉ worker) |
| `make worker-stop` | Stoppe le worker dev |
| `make worker-status` | PID + `rq info` (queues + workers connus de Redis) |
| `make bridge-status` | PID + `curl /health` |
| `make rq-info` | Snapshot RQ standalone |
| `make logs` | `tail -F` sur tous les `logs/*.log` + `logs/*.jsonl` |

> ⚠️ La cible `make worker-dev` **n'existe pas**. C'est `make worker-start`.

### Ordre de démarrage
1. Redis d'abord (Bridge **et** worker en dépendent — la connexion est paresseuse côté bridge mais le worker plante immédiatement sans Redis).
2. Bridge ensuite (peut booter sans worker — il fait juste de la pure mise en queue).
3. Worker en dernier (consomme les jobs).
`make start` respecte cet ordre.

### PID files pourris
Si `make start` dit « Bridge already running (PID xxxx) » mais aucun process ne tourne :
```bash
rm -f .bridge.pid .worker.pid
make start
```

Si le port 8080 est occupé sans qu'un PID file ne soit présent (résidu d'un crash) :
```bash
ss -ltnp | grep :8080            # identifier le process
# soit kill manuel, soit choisir un autre BRIDGE_PORT dans scraper.env
```

### Worker démarre mais ne consomme jamais le job
- Le worker écoute-t-il les bonnes queues ? `make worker-status` → vérifier que `high`, `normal`, `low` apparaissent dans `rq info`.
- Le worker a-t-il importé `bridge.workers` sans erreur ? `tail -50 logs/worker.log` — toute `ImportError` ou `NameError` ressort là.
- Bug type Step 1.5 : si `_DISPATCH["scrapy"]` pointe sur une fonction inexistante, le worker plante à l'import. Sanity check :
  ```bash
  .venv/bin/python -c "import bridge.workers; print('OK')"
  ```

### Subprocess Scrapy échoue (`/status` = failed)
```bash
# Reproduire le subprocess à la main pour voir le vrai message d'erreur
echo '{"tool":"scrapy","url":"https://httpbin.org/get","config":{"spider":"api_json","respect_robots":false},"job_id":"manualjob01"}' \
  | .venv/bin/python -m tools.scrapy_runner.run_scrapy
```
- Exit 0 + JSON sur stdout → le runner est sain ; le problème est dans le câblage worker.
- Exit 2 → input invalide (regarde stderr).
- Exit 3 → crash Twisted/Scrapy (regarde `logs/tools.log`).

### httpbin.org indisponible
Si `https://httpbin.org/get` time out (Cloudflare, DNS, etc.), remplace par un endpoint local ou par `https://www.example.com` (Test 3 retournera alors un `items[]` plus court mais non vide).

---

## 7. Critères de succès Session 1 — checklist

- [ ] `make test` → 43 passed
- [ ] `make start` démarre Redis + bridge + worker sans erreur dans les logs
- [ ] `GET /health` → 200 avec `manifest_version: "0.3.0"`
- [ ] `GET /capabilities` → `tools.scrapy.status == "available"`, 8 params
- [ ] `POST /run-tool` (Test 1) → 200 + job_id 16-hex
- [ ] `/status/{id}` traverse `queued → started → finished` en < 30 s
- [ ] `/result/{id}` retourne un dict avec `items[]` non vide et `_meta.item_count >= 1`
- [ ] `storage/results/{job_id}.json` présent sur disque, contenu identique à la réponse `/result`
- [ ] `logs/audit.jsonl` contient `run_tool_accepted` + `job_started` + `job_finished` pour le même `job_id`
- [ ] `make stop` arrête proprement bridge + worker, plus aucun process sur le port 8080
- [ ] Aucune `ConnectionError`, `NameError`, `ImportError`, `RuntimeError` non liée à un input volontairement cassé dans `logs/bridge.log` ou `logs/worker.log`

Si les 11 cases sont cochées → Session 1 validée, GO commit unique.
