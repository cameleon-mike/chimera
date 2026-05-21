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
| 10 | `tools/scrapy_runner/run_scrapy.py:140-141` | `_build_settings()` accepte n'importe quelle clé Scrapy depuis `config["settings"]` (DOWNLOADER_MIDDLEWARES, ITEM_PIPELINES, EXTENSIONS…). Vecteur de chargement de code arbitraire si l'input devient non-fiable. Whitelister les clés autorisées. | **Step 2.1** (exposition réseau) | ⏳ Ouvert |

---

## Conventions

- **Step cible** : step où la dette sera adressée. Ne pas anticiper hors contexte.
- **Statut** : `⏳ Ouvert` · `🟡 Veille` (conditionnel) · `✅ Résolu` (référencer commit/step report)
- Tout nouvel item doit être créé avec un step cible explicite. Pas de "à voir plus tard" sans step.

---

## Historique de résolution

- **TD-7** — résolu au Step 1.4. Validation `^[a-f0-9]{1,64}$` du `job_id` dans `_validate()`. Test pytest dédié : `tests/test_scrapy_runner.py::test_validate_rejects_path_traversal_job_id`.
