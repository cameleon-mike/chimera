# Account Factory — Guide opérationnel

> Step 3.6 · Chimera Session 3

---

## 1. Philosophie — Pourquoi vieillir les profils

Un navigateur crédible se construit dans le temps, pas uniquement par la technique.
Les sites difficiles (eBay, Vinted, Amazon) analysent l'historique de cookies, la
cohérence des empreintes browser, et la régularité du comportement. Un profil "neuf"
déclenche des challenges CAPTCHA quasi-systématiquement.

### Tableau de maturité

| Statut    | Age       | Comportement                                   |
|-----------|-----------|------------------------------------------------|
| creating  | 0-24 h    | UA + extensions configurés, aucune session     |
| warming   | 1-7 j     | Warm-up quotidien, collecte de cookies         |
| ready     | 7-30 j    | Utilisable en production sur la plupart des sites |
| senior    | 30-90 j   | Trust maximal, sites difficiles (eBay, Vinted) |
| recycle   | 90 j+     | Profil a rafraichir ou remplacer               |

### Regle d'or — Coherence geographique

**1 profil = 1 pays = 1 proxy country = TOUJOURS**

Un profil BE-Brussels utilise TOUJOURS un proxy belge. Melanger les pays est le
signal d'alarme le plus detecte par les systemes anti-bot.

---

## 2. Demarrage rapide

### Prerequis

```bash
make start             # demarre le bridge
export TOKEN=$(grep BRIDGE_AUTH_TOKEN scraper.env | cut -d= -f2)
```

### Creer des profils

```bash
# 1 profil BE (Bruxelles)
curl -s -X POST http://127.0.0.1:8080/factory/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"geo_id": "be-brussels", "proxy_country": "BE", "count": 1}' | python3 -m json.tool

# 1 profil DE (Berlin)
curl -s -X POST http://127.0.0.1:8080/factory/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"geo_id": "de-berlin", "proxy_country": "DE", "count": 1}' | python3 -m json.tool
```

### Lancer un warm-up manuel

```bash
# Remplacer <profile_id> par l'ID retourne par /factory/create
curl -s -X POST http://127.0.0.1:8080/factory/warm/<profile_id> \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### Consulter l'etat des profils

```bash
# Tous les profils
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/factory/profiles | python3 -m json.tool

# Seulement les profils ready
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8080/factory/profiles?status=ready" | python3 -m json.tool

# Statistiques globales
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/factory/stats | python3 -m json.tool

# Meilleur profil pour ebay.de
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8080/factory/recommend?domain=ebay.de" | python3 -m json.tool
```

### Activer le cron automatique

Dans `scraper.env` :
```
FACTORY_CRON_ENABLED=true
FACTORY_NEW_PROFILES_PER_DAY=2
```
Redemarrer le bridge. Le cron s'execute a 09:00 UTC chaque jour.

---

## 3. Comptes eBay / Vinted (operations manuelles)

### Pourquoi creer de vrais comptes

L'AccountFactory cree des **profils navigateur** (cookies, empreintes, historique).
Les **comptes marchands** (eBay, Vinted, Facebook Marketplace) doivent etre crees
manuellement — nous ne les creons jamais automatiquement.

### Procedure de creation d'un compte eBay

1. Depuis un navigateur correspondant au profil (meme IP, meme pays)
2. Utiliser une adresse email dediee (format : `prenom.nom.XXXX@domain.tld`)
3. Numero de telephone du pays cible pour la verification SMS
4. Adresse de livraison coherente avec le pays
5. Attendre 48 h avant la premiere annonce (reduction du risque de suspension)

### Lier un compte a un profil

Via SQLite directement :
```bash
sqlite3 storage/risk_db.sqlite "
UPDATE profiles
SET linked_account_json = '{\"platform\": \"ebay\", \"username\": \"YOUR_USERNAME\", \"email\": \"YOUR_EMAIL\"}'
WHERE profile_id = 'PROFILE_ID';
"
```

**Ne jamais stocker de mot de passe** dans `linked_account_json`.
Utiliser un gestionnaire de mots de passe externe (Bitwarden, 1Password).

### Nombre recommande de comptes par marketplace

| Marketplace         | Comptes recommandes | Profils associes |
|---------------------|---------------------|------------------|
| eBay.be             | 2-3                 | 1 par compte     |
| eBay.de             | 2-3                 | 1 par compte     |
| Vinted.be           | 2-3                 | 1 par compte     |
| Facebook Marketplace| 1-2                 | 1 par compte     |

---

## 4. Cookies et warm-up

### Sequence de sites par pays

Le warm-up visite en sequence :
1. Sites de collecte de cookies communs (Google, YouTube, Facebook)
2. Sites locaux du pays du profil

| Pays | Sites locaux visites                                        |
|------|-------------------------------------------------------------|
| BE   | rtbf.be, lesoir.be, hln.be, immoweb.be                     |
| FR   | lemonde.fr, lefigaro.fr, leboncoin.fr                      |
| DE   | spiegel.de, heise.de, ebay.de                              |
| GB   | bbc.co.uk, theguardian.com, gumtree.com                    |
| NL   | nu.nl, marktplaats.nl, tweakers.net                        |

### Extensions pre-installees

- **uBlock Origin** : bloque les trackers publicitaires (comportement utilisateur normal)
- **Honey** : extension populaire de reductions (augmente le "human score")

### Ce que collectent les cookies

- Cookies de session Google/YouTube : signaux de confiance Google reCAPTCHA
- Cookies locaux : coherence de l'historique de navigation local

---

## 5. Cron quotidien

### Configuration APScheduler

Le scheduler tourne dans le processus bridge FastAPI.
Il execute `daily_factory_run()` a **09:00 UTC** chaque jour.

Sequence du run quotidien :
1. Cree `FACTORY_NEW_PROFILES_PER_DAY` nouveaux profils (pays aleatoire)
2. Lance le warm-up sur les profils status=creating
3. Lance des micro-sessions (2-3 pages) sur les profils warming/ready/senior
4. Applique les transitions de statut selon l'age
5. Reporte les profils status=recycle pour action manuelle

### Monitoring via /factory/stats

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/factory/stats | python3 -m json.tool
```

Reponse attendue :
```json
{
  "total": 8,
  "by_status": {
    "creating": 2,
    "warming": 3,
    "ready": 2,
    "senior": 1,
    "recycle": 0
  },
  "oldest_profile": "prof-a1b2c3d4",
  "newest_profile": "prof-e5f6g7h8"
}
```

### Quand recycler un profil

Un profil passe en `recycle` automatiquement a 90 jours.
Actions recommandees :
1. Verifier si un compte marchand est lie (`linked_account_json`)
2. Archiver le dossier profil : `storage/cookies/<profile_id>/`
3. Creer un profil de remplacement via `/factory/create`
4. Mettre a jour le compte marchand lie vers le nouveau profil

### Inspection SQLite directe

```bash
sqlite3 storage/risk_db.sqlite \
  "SELECT profile_id, geo_id, proxy_country, status, age_days FROM profiles ORDER BY age_days DESC;"
```

---

## 6. Depannage

### Le warm-up echoue (proxy down)

Le bridge continue les autres profils (fail-safe). Verifier :
```bash
curl -s http://127.0.0.1:24000/api/proxies  # Bright Data PM
```

### Proxy bloque en Codespace Azure

Les proxies Bright Data sont bloques depuis l'environnement Codespace.
Tester en local ou sur le serveur de production Ubuntu.

### Le cron ne demarre pas

Verifier `FACTORY_CRON_ENABLED=true` dans `scraper.env` et que `apscheduler` est installe :
```bash
pip show apscheduler
```
