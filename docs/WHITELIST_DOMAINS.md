# Chimera — Whitelist des domaines autorisés

> Référence opérationnelle. Décisions légales dans `LEGAL.md`. Mis à jour à chaque ajout de domaine.

## Processus d'ajout

1. Vérifier que le domaine est dans `LEGAL.md` allowlist (section 4)
2. Identifier le tier maximum autorisé (0-4, voir LEGAL.md section 3)
3. Ajouter l'entrée ci-dessous avec la date et le responsable
4. Bumper `manifest_version` dans `tool_manifest.json` si le profil de risque change

## Tiers d'escalade (rappel)

| Tier | Tool | Condition de déclenchement |
|------|------|---------------------------|
| 0 | scrapy datacenter | risk_score < 0.2 |
| 1 | scrapy residential | 0.2 ≤ risk_score < 0.5 |
| 2 | crawl4ai | 0.5 ≤ risk_score < 0.8 |
| 3 | screenshot | risk_score ≥ 0.8 |
| 4 | bypass_waf | Cloudflare challenge explicite — autorisation manuelle requise |

## Domaines autorisés

| Domaine | Tier max | Usage | Autorisé par | Date | Notes |
|---------|----------|-------|-------------|------|-------|
| httpbin.org | 4 | Tests / CI | Mike | 2026-05-23 | Service public de test |
| books.toscrape.com | 4 | Tests / CI | Mike | 2026-05-23 | Site dédié à la pratique du scraping |

## Domaines bloqués

| Domaine | Raison | Bloqué le | Notes |
|---------|--------|-----------|-------|
| (aucun pour l'instant) | — | — | |

## Règles d'utilisation

- **Tier 0-1 (scrapy)** : pas de pré-autorisation requise pour les domaines hors blocklist.
- **Tier 2 (crawl4ai)** : déclenchement automatique par la politique d'escalade — pas d'autorisation manuelle requise si risk_score ≥ 0.5 d'après `risk_events`.
- **Tier 3 (screenshot)** : déclenchement automatique si risk_score ≥ 0.8. Pour les domaines de production (eBay, 2ememain, etc.), documenter l'incident dans `LEGAL.md` section 8.
- **Tier 4 (bypass_waf)** : **toujours manuel** — ajouter le domaine dans ce fichier avec justification avant tout appel à `/run-tool` avec `tool=bypass_waf`.

## Vérification rapide

Pour consulter les domaines récemment ciblés avec un score élevé :

```bash
sqlite3 storage/risk_db.sqlite \
  "SELECT domain, MAX(risk_score), COUNT(*) FROM risk_events GROUP BY domain ORDER BY MAX(risk_score) DESC LIMIT 20;"
```
