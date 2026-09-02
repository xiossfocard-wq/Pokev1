# Pokémon Deal Hunter

Surveillance des annonces Vinted et eBay (cartes Pokémon FR), comparées à
des prix de référence (Cardmarket + ZebraDex), avec un score de "bonne
affaire" combinant marge estimée, qualité indicative (photos + texte) et
fiabilité vendeur. Notifications Telegram/email au-dessus d'un seuil
configurable, dashboard web trié par score/marge/date.

## ⚠️ À lire avant de lancer : limites légales du scraping

Ce projet accède à des données Vinted, Cardmarket et ZebraDex sans API
officielle (Vinted et ZebraDex n'en proposent pas ; Cardmarket en a une
mais elle est contractuellement réservée à la gestion de son propre stock —
voir `backend/app/collectors/cardmarket_prices.py`). Pour ces trois
sources :

- **Aucune connexion à un compte** : seules des pages publiques sont lues.
- **Fréquence volontairement basse** (configurable), avec pause automatique
  en cas de blocage.
- **robots.txt vérifié automatiquement avant chaque requête** (voir
  `app/core/robots_compliance.py`) : si un site l'interdit, la requête est
  annulée, pas de contournement.
- **Aucun contournement d'anti-bot** : pas de rotation de proxy, pas de
  résolution de CAPTCHA. Si un site bloque, le scraper recule et te
  notifie plutôt que d'insister.

Malgré ces précautions, les CGU de Vinted interdisent probablement
l'extraction automatisée de données hors de l'interface prévue par le site
(clause courante chez la plupart des plateformes de ce type) : c'est un
usage à tes risques, en usage personnel et à faible volume, pas une
autorisation formelle de leur part. Le risque concret le plus probable est
un blocage temporaire de ton IP, pas une poursuite — mais sois-en conscient.
Cardmarket a rendu son "Price Guide" librement consultable précisément pour
ce genre d'usage ; ZebraDex n'a pas de politique connue là-dessus.

## Architecture

```
backend/   FastAPI + SQLAlchemy + APScheduler (Python)
frontend/  Next.js 14 (App Router) + Tailwind
```

- **Collecte** : `app/collectors/` — eBay Browse API (officielle, OAuth2),
  scraper Vinted (respectueux), Cardmarket (page produit ou price guide en
  masse), ZebraDex (pages série).
- **Matching carte** : `app/matching/card_matcher.py` — devine le nom de
  carte à partir du titre de l'annonce (best-effort, voir limites dans le
  fichier). Rattrapage possible via OCR photo si le titre ne suffit pas.
- **Scoring** : `app/scoring/` — marge, qualité texte, fiabilité vendeur,
  score final combiné (poids configurables).
- **Vision/OCR** : `app/vision/quality_vision.py` — un seul appel à l'API
  Anthropic (Claude) par annonce fait à la fois l'estimation d'état
  (centrage/coins/rayures, **indicative, pas un grading pro**) et la
  lecture du nom/numéro imprimés sur la carte.
- **Notifications** : `app/notifications/` — Telegram et/ou email.
- **Orchestration** : `app/pipeline.py` (logique) + `app/scheduler.py`
  (déclenchement périodique) + endpoint `POST /api/admin/run-check-now`
  pour déclencher un cycle manuellement (utile en debug, et pour
  l'hébergement 100% gratuit — voir plus bas).

**Tests** : `backend/tests/` — 217 tests. Lancer avec :

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt --break-system-packages
python3 -m unittest discover -s tests -v
```

Ils couvrent deux niveaux :

- **la logique pure** (marge, score, matching, parsing
  eBay/Vinted/Cardmarket/ZebraDex, robots.txt, filtre de langue,
  corrections manuelles, vision/OCR avec l'appel API mocké) ;
- **l'API elle-même** (`tests/test_api_routes.py`) : le serveur démarre
  pour de vrai, les routes sont montées aux bons chemins, les annonces se
  sérialisent en JSON, et les codes d'erreur sont ceux annoncés (404 sur
  annonce inconnue, 400 sur action de correction invalide). Ce module a
  besoin de `httpx` (dans `requirements-dev.txt`) ; sans lui il est sauté
  proprement et le reste de la suite tourne quand même.

**Vérifié à la main le 02/09/2026**, en plus de la suite : le backend
démarre (`init_db` + rattrapage de colonnes + scheduler), les 18 routes
répondent, et le frontend compile (`next build`, vérification de types
comprise, 3 pages générées).

Ce qui reste **non testé en conditions réelles** : tout ce qui touche au
réseau sortant — collecte eBay et Vinted, Cardmarket, ZebraDex,
notifications — et le déclenchement périodique du scheduler. Ces
chemins-là ne peuvent être validés que sur ton installation, avec de
vraies clés : je reste disponible pour déboguer à partir des erreurs que
tu me copieras-colleras.

## Lancer en local

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # puis remplir au moins EBAY_CLIENT_ID/SECRET si tu veux du eBay réel
uvicorn app.main:app --reload
```

Par défaut `DATABASE_URL=sqlite:///./dev.db` (rien à installer). L'API
répond sur http://localhost:8000 — vérifier avec `curl http://localhost:8000/api/health`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000 par défaut
npm run dev
```

Dashboard sur http://localhost:3000.

## Déploiement (100% gratuit possible)

| Composant | Service | Pourquoi |
|---|---|---|
| Frontend (Next.js) | **Vercel** (plan Hobby, gratuit) | Fait pour Next.js, déploiement automatique depuis GitHub |
| Backend (FastAPI) | **Render** (plan Free) | Gratuit, mais se met en veille après 15 min d'inactivité (cold start ~30-60s au réveil) |
| Base de données | **Neon** (plan Free, 0,5 Go / 100h de calcul par mois) | Postgres serverless, gratuit en continu (pas d'expiration), scale-to-zero |
| Code | **GitHub** | Gratuit, connecte Vercel et Render en déploiement continu |
| Notifications | **Telegram** (bot gratuit) | — |

### 1. Pousser le code sur GitHub

Le dépôt git est déjà initialisé en local avec un premier commit. Il ne reste qu'à créer le repo distant et pousser :

```bash
# Crée d'abord un repo vide sur https://github.com/new (sans README ni .gitignore, ils existent déjà)
git remote add origin https://github.com/<ton-compte>/pokemon-deal-hunter.git
git branch -M main
git push -u origin main
```

### 2. Base de données — Neon

1. Créer un compte sur https://neon.tech (gratuit, pas de carte bancaire).
2. Créer un projet → copier la "Connection string" (commence par `postgresql://`).
3. La transformer en `postgresql+psycopg2://...` (même chaîne, juste le driver précisé) → c'est la valeur de `DATABASE_URL`.

### 3. Backend — Render

1. https://render.com → New → Blueprint → sélectionner ton repo GitHub (le fichier `render.yaml` à la racine est détecté automatiquement).
2. Renseigner les variables marquées `sync: false` dans le dashboard Render : `DATABASE_URL` (Neon), `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`, et les autres clés optionnelles quand tu les auras.
3. Noter l'URL du service déployé (ex `https://pokemon-deal-hunter-backend.onrender.com`).

**Limite du plan gratuit** : le service s'endort après 15 min sans requête. Deux options :
- **Accepter la mise en veille** : configurer le secret GitHub `BACKEND_URL` (Settings → Secrets and variables → Actions) avec l'URL Render, le workflow `.github/workflows/trigger-check.yml` réveille le backend et lance un cycle de vérification toutes les 20 min, gratuitement, via GitHub Actions.
- **Payer ~7$/mois** (plan Starter Render) pour un backend toujours actif si tu préfères la simplicité.

### 4. Frontend — Vercel

1. https://vercel.com → New Project → importer le repo GitHub → Root Directory : `frontend`.
2. Ajouter la variable d'environnement `NEXT_PUBLIC_API_URL` = URL Render du backend.
3. Déployer. Chaque push sur `main` redéploie automatiquement.

## Outils/comptes gratuits nécessaires ou utiles

| Outil | Usage | Gratuit ? |
|---|---|---|
| [GitHub](https://github.com) | Héberger le code | Oui, illimité pour un compte perso |
| [Vercel](https://vercel.com) | Héberger le frontend | Oui (plan Hobby) |
| [Render](https://render.com) | Héberger le backend | Oui (plan Free, avec mise en veille — voir plus haut) |
| [Neon](https://neon.tech) | Base de données Postgres | Oui, en continu (0,5 Go / 100h calcul/mois) |
| [eBay Developer Program](https://developer.ebay.com) | Clé Browse API | Oui, compte gratuit |
| Telegram (@BotFather) | Bot de notification | Oui |
| [Anthropic Console](https://console.anthropic.com) | Analyse qualité photo + OCR | Payant à l'usage (quelques centimes/annonce analysée) — le reste de l'app fonctionne sans |
| [UptimeRobot](https://uptimerobot.com) | Alternative à GitHub Actions pour réveiller le backend Render | Oui (50 moniteurs, intervalle 5 min) |
| [cron-job.org](https://cron-job.org) | Autre alternative de cron externe, sans code | Oui |
| Docker Desktop / Python 3.11+ / Node.js 20+ / Git | Dev local | Oui, tout open-source |
| [DBeaver](https://dbeaver.io) | Inspecter la base Postgres/SQLite visuellement | Oui (édition communautaire) |
| [Postman](https://www.postman.com) ou juste `curl` | Tester les routes de l'API à la main | Oui |

**Rien dans cette liste ne coûte quelque chose pour démarrer**, à l'exception de l'API Anthropic (vision/OCR) qui est payante à l'usage — mais optionnelle : sans elle, le score de qualité se base uniquement sur l'analyse du texte de l'annonce.

## Ce qui reste à faire de ton côté

1. Créer les comptes ci-dessus et récupérer les clés (eBay obligatoire pour avoir des annonces eBay réelles ; le reste est optionnel).
2. Lancer en local, vérifier que `/api/health` répond et que le dashboard affiche (même vide au début).
3. Configurer eBay puis relancer un cycle via le bouton "Vérifier maintenant" du dashboard (ou `POST /api/admin/run-check-now`) et vérifier que des annonces apparaissent.
4. Si le scraper Vinted ne remonte rien : c'est probablement que la structure de page a changé depuis la vérification faite pendant le développement (voir les commentaires dans `vinted_scraper.py`) — copie-colle-moi un extrait du HTML obtenu et j'ajuste le parsing.
5. Déployer selon la section ci-dessus.

Je reste disponible pour déboguer à partir de tes retours (logs, erreurs, captures d'écran).

## Sécurité des dépendances (frontend)

Next.js 14.2.5, la version d'origine, traînait des failles classées
**critiques** (contournement d'autorisation dans le middleware,
empoisonnement de cache). Le projet est passé à **Next 14.2.35**, la
dernière version corrigée de la même série : c'est un correctif de patch,
sans changement d'API, et le build passe à l'identique.

`package-lock.json` est désormais versionné. Sans lui, Vercel et Render
réinstallaient les dépendances à leur guise à chaque déploiement, et rien
ne garantissait que la version corrigée soit bien celle déployée.

Il reste des alertes classées **hautes** sur `next` (`npm audit`). Elles ne
sont corrigées qu'à partir de Next 16, soit **deux versions majeures plus
loin** — une migration à part entière, pas une mise à jour. Je ne l'ai pas
faite d'office. Voici de quoi décider, sans enjoliver :

- **La plupart ne s'appliquent pas ici** : ni middleware, ni Server
  Actions, ni rewrites, ni i18n dans ce projet (vérifié). Restent trois
  pages qui lisent une API.
- **Sauf celles sur l'optimiseur d'images, qui elles s'appliquent** :
  `components/ListingCard.tsx` utilise `next/image`, et `next.config.js`
  déclare des `remotePatterns` pour les CDN Vinted et eBay. Les alertes
  visant l'Image Optimizer (déni de service, cache disque non borné) sont
  donc dans le périmètre réel du projet.
- **Ce qui les atténue** : ces trois-là visent les déploiements
  *auto-hébergés*. Sur Vercel, l'optimisation d'images tourne sur leur
  infrastructure, pas sur un serveur à toi qu'on pourrait saturer. Si un
  jour tu héberges le frontend ailleurs, elles redeviennent à prendre au
  sérieux.
- Enfin, le dashboard n'a **aucune authentification** et n'affiche aucune
  donnée personnelle : un contournement d'autorisation n'a rien à
  contourner.

Conclusion : rien d'urgent tant que le frontend est sur Vercel, à
reconsidérer si tu changes d'hébergeur.

À refaire de temps en temps, dans `frontend/` :

```bash
npm audit            # état des alertes
npm update next      # reste dans la série 14.x, sans risque de rupture
```
