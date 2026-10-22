#!/usr/bin/env bash
#
# Démarrage local, tout en un.
#
# POURQUOI CE SCRIPT EXISTE
# -------------------------
# Les étapes prises une par une sont simples, mais il y en a une qu'on ne
# devine pas : le catalogue ne se remplit pas tout seul au premier
# démarrage. Sans elle, l'application se lance correctement, ne montre
# aucune carte, et rien n'indique que c'est normal. Ce script fait la
# séquence complète dans l'ordre, et dit à chaque étape ce qu'il a obtenu.
#
# Usage :   bash scripts/demarrer.sh
# Arrêt :   Ctrl+C
#
# Sous Windows : lancer depuis Git Bash ou WSL. Sinon, suivre les étapes
# manuelles du README, qui sont les mêmes.

set -u

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT_API=8000
PORT_WEB=3000
PID_API=""

bleu()  { printf '\033[36m%s\033[0m\n' "$*"; }
vert()  { printf '\033[32m%s\033[0m\n' "$*"; }
rouge() { printf '\033[31m%s\033[0m\n' "$*"; }

DEJA_NETTOYE=""
nettoyer() {
  # Idempotent : le trap se déclenche sur INT *puis* sur EXIT, et sans ce
  # garde-fou le message d'arrêt s'affiche deux fois.
  [ -n "$DEJA_NETTOYE" ] && return
  DEJA_NETTOYE=1
  if [ -n "$PID_API" ] && kill -0 "$PID_API" 2>/dev/null; then
    bleu "→ arrêt du backend"
    kill "$PID_API" 2>/dev/null
  fi
}
trap nettoyer EXIT INT TERM

# --- 1. Outils requis ----------------------------------------------------
for outil in python3 node npm; do
  if ! command -v "$outil" >/dev/null 2>&1; then
    rouge "✗ $outil est introuvable."
    echo "  Installer Python 3.11+ et Node.js 20+, puis relancer."
    exit 1
  fi
done
vert "✓ python3 $(python3 --version 2>&1 | awk '{print $2}') · node $(node --version)"

# --- 2. Dépendances du backend ------------------------------------------
cd "$RACINE/backend"
if [ ! -d .venv ]; then
  bleu "→ création de l'environnement Python (une seule fois)"
  python3 -m venv .venv || { rouge "✗ création impossible"; exit 1; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate
bleu "→ installation des dépendances Python"
pip install -q -r requirements.txt || { rouge "✗ installation échouée"; exit 1; }
vert "✓ backend prêt"

# --- 3. Démarrage du backend --------------------------------------------
bleu "→ démarrage de l'API sur le port $PORT_API"
python3 -m uvicorn app.main:app --port "$PORT_API" > "$RACINE/backend/api.log" 2>&1 &
PID_API=$!

API="http://localhost:$PORT_API"
ETAPES="$RACINE/scripts/etapes_demarrage.py"

if ! python3 "$ETAPES" attendre "$API"; then
  rouge "✗ l'API ne répond pas. Dernières lignes de backend/api.log :"
  tail -20 "$RACINE/backend/api.log"
  exit 1
fi
vert "✓ API en ligne — $API"

# --- 4. Catalogue : L'ÉTAPE QU'ON NE DEVINE PAS -------------------------
bleu "→ catalogue"
if python3 "$ETAPES" catalogue "$API"; then
  vert "✓ catalogue prêt"
else
  rouge "✗ le catalogue est resté vide — voir backend/api.log"
fi

# --- 4bis. Noms français -------------------------------------------------
bleu "→ noms français (liste officielle)"
python3 "$ETAPES" noms-fr "$API"

# --- 5. Visuels ----------------------------------------------------------
# Les visuels se déduisent du code de la carte. Cette étape a besoin
# d'Internet ; si elle échoue, le reste fonctionne, les cartes s'affichent
# simplement sans image.
bleu "→ visuels (plusieurs minutes pour un catalogue complet)"
python3 "$ETAPES" visuels "$API"

# --- 6. Frontend ---------------------------------------------------------
cd "$RACINE/frontend"
if [ ! -d node_modules ]; then
  bleu "→ installation des dépendances web (une seule fois, c'est long)"
  npm install --silent || { rouge "✗ npm install a échoué"; exit 1; }
fi

echo
vert "════════════════════════════════════════════════"
vert "  Tableau de bord : http://localhost:$PORT_WEB"
vert "  Explorateur     : http://localhost:$PORT_WEB/explorer"
vert "  Ctrl+C pour tout arrêter"
vert "════════════════════════════════════════════════"
echo

npm run dev
