# Chimera — Dette technique

Source de suivi unique. Chaque item liste son **step cible de résolution**.
À mettre à jour à chaque step report (entrée nouvelle / item résolu).

---

## Inventaire

| # | Fichier:Ligne | Description | Step cible | Statut |
|---|---|---|---|---|
| 1 | `bridge/queue.py:72` | `fetch_job()` : `except Exception` trop large masque `redis.ConnectionError` en `not_found`. Resserrer sur `rq.exceptions.NoSuchJobError` et laisser remonter les erreurs réseau. | **Step 1.5** (robustesse / systemd) | ✅ Résolu |
| 2 | `bridge/workers.py:128` | `setup_logging()` appelé à chaque `dispatch_job()`. Idempotent grâce à `cache_logger_on_first_use=True` mais fragile si modèle de concurrence évolue. Hisser à l'init du worker process. | **Step 1.5** (robustesse / systemd) | ✅ Résolu |
| 3 | `bridge/workers.py:43,54,67,80,93` | `time.sleep()` synchrone dans les stubs. OK pour RQ (fork par job). À remplacer par `asyncio.sleep` uniquement si migration worker async (arq/taskiq). | **Conditionnel** : si migration async | 🟡 Veille |
| 4 | `bridge/workers.py:62` | `screenshot_path` hardcodé relatif (`storage/screenshots/{job_id}.png`). Doit passer par `get_settings().screenshots_dir` dans le runner réel. | **Step 3.2** (screenshot runner réel) | ⏳ Ouvert |
| 5 | `bridge/app.py:115` | `time.strftime("%Y-%m-%dT%H:%M:%SZ")` pour audit `run_tool_accepted` : perd les µs, format incohérent avec `workers.py` (`%Y-%m-%dT%H:%M:%S.%fZ`). Unifier via helper partagé. | **Cosmétique** (à grouper avec prochaine touche audit) | ⏳ Ouvert |
| 6 | `scripts/bridge_dev.sh:22-43` | `start()` ne détecte pas qu'un autre process écoute déjà sur le port — exit 1 trompeur si PID file pourri + port occupé. Ajouter check `ss -ltn` indépendant du PID file. | **Step 1.5** (robustesse / systemd) | ⏳ Ouvert |
| 7 | `tools/scrapy_runner/run_scrapy.py:128` | `job_id` utilisateur non validé → path traversal possible dans `_persist_result()`. Fixé par regex `^[a-f0-9]{1,64}$` dans `_validate()`. | **Step 1.4** | ✅ Résolu |
| 8 | `tools/scrapy_runner/project/middlewares/human_delay.py:31` | `time.sleep()` synchrone dans le thread du `AsyncioSelectorReactor`. Bloque le reactor sous concurrence > 1. Remplacer par `DOWNLOAD_DELAY` Scrapy pur ou `reactor.callLater`. | **Step S2/S3** (montée en charge) | ⏳ Ouvert |
| 9 | `tool_manifest.json:24-29` | Entrée `tools.scrapy` reste `status: "planned"` et `params: {}` alors que le runner est implémenté avec interface documentée (spider, selectors, item_selector, headers, settings, respect_robots, proxy, session_id). Cameleon ne peut pas introspecter. | **Step 1.5** (câblage bridge↔runner) | ✅ Résolu |
| 11 | `infra/systemd/chimera.env` | `chmod 0640 root:chimera` documenté en commentaire mais non enforced. Un opérateur pressé peut laisser le fichier en 0644 → fuite future de `BRIDGE_AUTH_TOKEN`. Ajouter un `install.sh` ou un `ExecStartPre=/usr/bin/install -m 0640 ...`. | **Step déploiement prod** (S4 ou avant cutover) | ⏳ Ouvert |
| 12 | `bridge/workers.py:_run_scrapy_subprocess` | Subprocess Scrapy hérite du `PrivateTmp=true` du worker systemd. Comportement non testé E2E sur prod (tmpfs privé partagé avec le forké). À valider lors du premier run réel sur Ubuntu. | **Step E2E prod** | ⏳ Ouvert |
| 10 | `tools/scrapy_runner/run_scrapy.py:140-141` | `_build_settings()` accepte n'importe quelle clé Scrapy depuis `config["settings"]` (DOWNLOADER_MIDDLEWARES, ITEM_PIPELINES, EXTENSIONS…). Vecteur de chargement de code arbitraire si l'input devient non-fiable. Whitelister les clés autorisées. | **Step 2.1** (exposition réseau) | ✅ Résolu |
| 13 | `tools/probe/security_probe.py` | Probe HTTP+TLS sans cap global : TLS timeout=5s + HTTP timeout=10s = 15s maximum théorique, mais pas de deadline unique wrappant les deux appels. Peut dépasser 15s si network lent. Implémenter via `concurrent.futures.wait(timeout=15)` ou `signal.alarm`. | **Step 2.3** (robustesse réseau) | ✅ Résolu |
| 14 | `tools/probe/security_probe.py:218` | HSTS `max_age > 31536000` (strict supérieur) : une valeur exacte de 31536000 (1 an standard) ne déclenche pas `hsts_strict`. Clarifier si `>=` était voulu. Impact : léger sous-scoring sur les sites avec exactement max-age=31536000. | **Cosmétique** (grouper avec prochaine touche scoring) | ⏳ Ouvert |
| 15 | `tools/probe/scoring.py` | Fallback scoring : quand `FingerprintLoader` échoue, `compute_risk_score()` utilise le profil hardcodé `"chrome127-win"`. Fonctionnel mais non testé explicitement. Ajouter un test pytest vérifiant le comportement de fallback. | **Step 2.4** (tests coverage) | ✅ Résolu |
| 16 | `bridge/app.py` | **[Résolu S2.3.1]** `_FQDN_RE` trop permissive (IPs, single-labels, localhost). Remplacée par `validate_fqdn()` dans `tools/common/domain_validator.py` avec blocklist explicite, rejet IP via `ipaddress`, rejet TLD réservés. | **Step 2.3 hotfix** | ✅ Résolu |
| 17 | `tools/common/domain_validator.py` | IDN TLDs (xn-- en position TLD) non supportés — regex force `[a-zA-Z]{2,63}`. Labels xn-- avec TLD ASCII acceptés. Non-support intentionnel à cette étape. | **Step prod / internationalisation** | 🟡 Veille |
| 18 | `tools/scrapy_runner/run_scrapy.py:277` | `job_id` non transmis dans `spider_kwargs` → `risk_events.job_id` NULL pour toutes les lignes insérées par le middleware. Fix : ajout `"job_id": job_id` dans le dict `spider_kwargs`. | **Step 2.5** | ✅ Résolu |

---

## Conventions

- **Step cible** : step où la dette sera adressée. Ne pas anticiper hors contexte.
- **Statut** : `⏳ Ouvert` · `🟡 Veille` (conditionnel) · `✅ Résolu` (référencer commit/step report)
- Tout nouvel item doit être créé avec un step cible explicite. Pas de "à voir plus tard" sans step.

---

## Historique de résolution

- **TD-7** — résolu au Step 1.4. Validation `^[a-f0-9]{1,64}$` du `job_id` dans `_validate()`. Test pytest dédié : `tests/test_scrapy_runner.py::test_validate_rejects_path_traversal_job_id`.
- **TD-10** — résolu au Step 2.1. `_SCRAPY_SETTINGS_WHITELIST` module-level dans `run_scrapy.py`; clés non-whitelistées rejetées avec `logger.warning`. Tests : `tests/test_scrapy_settings_whitelist.py`.
- **TD-13** — résolu au Step 2.3. Hard-cap global 15s implémenté dans `probe_domain()` via `concurrent.futures.ThreadPoolExecutor(timeout=15)`. Test dédié : `tests/test_probe_timeout.py`.
- **TD-16** — résolu au Step 2.3.1 (hotfix). `_FQDN_RE` remplacée par `validate_fqdn()` dans `tools/common/domain_validator.py`. Bloque IPv4/IPv6, single-labels, TLDs réservés. Tests : `tests/test_domain_validator.py` (30 cas) + `tests/test_probe_ssrf_e2e.py` (10 cas e2e).
- **TD-15** — résolu au Step 2.4. Test `test_fallback_fingerprint_on_loader_error` dans `tests/test_scoring.py` : monkeypatch `FingerprintLoader` → `RuntimeError`, vérifie `recommendation["fingerprint"] == "chrome127-win"`.
- **TD-18** — résolu au Step 2.5. `job_id` non passé aux spiders dans `spider_kwargs` de `run_scrapy.py:277`. Fix : ajout `"job_id": job_id`. Tests : `test_job_id_propagated_to_persist` et `test_job_id_none_when_spider_has_no_attribute` dans `tests/test_risk_middleware.py`.
