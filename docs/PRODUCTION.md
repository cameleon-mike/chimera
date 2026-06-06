# Chimera — Production Operations

VPS: 212.227.185.195
Domain: https://shovelos.com
Manifest: v0.8.3

## Services systemd

| Service | Description |
|---|---|
| chimera-bridge | FastAPI uvicorn :8080 |
| chimera-worker | RQ worker queue chimera |
| chimera-cron | Scraping agent cron |
| redis-server | Redis :6379 |
| nginx | Reverse proxy HTTPS |

### Commandes de base

```bash
# Statut
systemctl status chimera-bridge chimera-worker chimera-cron

# Démarrer / Arrêter / Redémarrer
systemctl start chimera-bridge
systemctl stop chimera-bridge
systemctl restart chimera-bridge

# Logs temps réel
journalctl -u chimera-bridge -f
journalctl -u chimera-worker -f
journalctl -u chimera-cron -f

# Logs fichiers
tail -f /workspaces/chimera/logs/bridge.log
tail -f /workspaces/chimera/logs/worker.log
```

## Nginx

```bash
# Tester la config
nginx -t

# Recharger (sans downtime)
systemctl reload nginx

# Config site
/etc/nginx/sites-available/shovel
```

## SSL / TLS

Certificat Let's Encrypt, expire Aug 31 2026.
Renouvellement automatique via certbot.timer (2x/jour).

```bash
# Vérifier le timer
systemctl status certbot.timer

# Test renouvellement
certbot renew --dry-run

# Date expiration
openssl x509 -enddate -noout -in /etc/letsencrypt/live/shovelos.com/fullchain.pem
```

## Déploiement

```bash
# Mettre à jour le code
cd /workspaces/chimera
git pull

# Redémarrer le bridge
systemctl restart chimera-bridge

# Vérifier santé
curl http://127.0.0.1:8080/health
```

## Endpoints live

- Health: https://shovelos.com/api/chimera/health
- UI: https://shovelos.com/ui
- API docs: https://shovelos.com/api/chimera/docs

## Tests

```bash
cd /workspaces/chimera
make test
```
