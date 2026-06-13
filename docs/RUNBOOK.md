# Chimera Runbook

Operational procedures and troubleshooting for Chimera production deployment.

### Démarrer les services
Au boot ou après un arrêt manuel. Les trois unités sont `enabled` (survivent au reboot).
```bash
systemctl start chimera-bridge chimera-worker chimera-cron
```

### Arrêter proprement
Avant une maintenance. Arrête le bridge HTTP, le worker RQ et le cron de scraping.
```bash
systemctl stop chimera-bridge chimera-worker chimera-cron
```

### Mise à jour du code
Après un `git push`. Le cron n'a pas besoin de restart (il relit le code à chaque tick).
```bash
git pull && systemctl restart chimera-bridge chimera-worker
```

### Vérifier les logs
`journalctl` pour le flux systemd, le fichier pour les logs applicatifs structurés.
```bash
journalctl -u chimera-bridge -f --since "1 hour ago"
tail -f /workspaces/chimera/logs/bridge.log
```

### Renouveler le certificat SSL
Let's Encrypt, renouvelé 2x/jour par `certbot.timer`. Le dry-run valide sans consommer de quota.
```bash
certbot renew --dry-run
systemctl status certbot.timer
```

### Lancer un scrape manuel
Force un scrape agrégé et l'ingestion des stats ePID hors planning cron.
```bash
export TOKEN=$(grep BRIDGE_AUTH_TOKEN scraper.env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8080/aggregate/search?q=wacom+cintiq+16&ingest=true"
```

### Lancer un run Stealth manuel
Pour les sources protégées (Cloudflare). Synchrone (~40s), proxy résidentiel BE.
```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.vinted.fr/catalog?search_text=wacom","query":"wacom","source":"vinted","config":{"proxy_country":"BE","ingest":true}}' \
  https://shovelos.com/api/chimera/stealth/run
```

### Vérifier l'état du système
`/health` donne le statut par sous-système ; `audit.py` exécute 11 contrôles de cohérence.
```bash
curl -s https://shovelos.com/api/chimera/health | python3 -m json.tool
.venv/bin/python3 scripts/audit.py
```

### Débugger un endpoint qui retourne 0 items
Du moins coûteux au plus coûteux — escalader seulement si l'étape précédente est saine.
1. Vérifier /probe/{domain} → risk_score et recommendation
2. Vérifier logs/bridge.log | grep "error"
3. Tester avec outil manuel : crawl4ai si scrapy échoue
4. Si blocked=True → utiliser /stealth/run avec proxy BE

### Port 8080 bloqué au redémarrage
Quand un uvicorn orphelin retient le port. Tuer le process, nettoyer les PID, relancer.
```bash
pkill -f "uvicorn bridge.app"
rm -f .bridge.pid .worker.pid
systemctl restart chimera-bridge
```

### Récupérer après crash complet
Reprise à froid : code à jour, units rechargées, redis inclus, puis vérification santé.
```bash
git pull
systemctl daemon-reload
systemctl restart chimera-bridge chimera-worker chimera-cron redis
curl https://shovelos.com/api/chimera/health
```
