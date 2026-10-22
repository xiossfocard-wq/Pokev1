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
# On liste TOUT ce qui manque d'un coup. S'arrêter au premier manquant
# oblige à installer, relancer, découvrir le suivant, réinstaller — là où
# un seul aller-retour suffisait.
MANQUANTS=""
command -v python3 >/dev/null 2>&1 || MANQUANTS="$MANQUANTS python"
{ command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; } \
  || MANQUANTS="$MANQUANTS node"

if [ -n "$MANQUANTS" ]; then
  rouge "✗ Il manque de quoi lancer l'application."
  echo
  case "$MANQUANTS" in
    *python*) echo "  Python 3.11 ou plus  →  https://www.python.org/downloads/"
              echo "     (sous Windows, cocher « Add Python to PATH » à l'installation)" ;;
  esac
  case "$MANQUANTS" in
    *node*)   echo "  Node.js 20 ou plus   →  https://nodejs.org/" ;;
  esac
  echo
  echo "  Installer ce qui manque, fermer puis rouvrir le terminal, et relancer."
  exit 1
fi

VERSION_PY="$(python3 --version 2>&1 | awk '{print $2}')"
MAJEURE_PY="$(printf '%s' "$VERSION_PY" | cut -d. -f1)"
MINEURE_PY="$(printf '%s' "$VERSION_PY" | cut -d. -f2)"
# Une version trop ancienne échouerait plus loin, sur un message d'erreur
# Python incompréhensible. Autant le dire ici, où la cause est claire.
if [ "${MAJEURE_PY:-0}" -lt 3 ] || { [ "$MAJEURE_PY" = "3" ] && [ "${MINEURE_PY:-0}" -lt 11 ]; }; then
  rouge "✗ Python $VERSION_PY est trop ancien — il en faut 3.11 ou plus."
  echo "  https://www.python.org/downloads/"
  exit 1
fi

vert "✓ python3 $VERSION_PY · node $(node --version)"

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

# --- 4ter. Prix de référence ---------------------------------------------
# C'est ce qui allume les marges et les scores d'affaire.
bleu "→ prix de référence (peut prendre un long moment)"
python3 "$ETAPES" prix "$API"

# --- 5. Visuels ----------------------------------------------------------
# Les visuels se déduisent du code de la carte. Cette étape a besoin
# d'Internet ; si elle échoue, le reste fonctionne, les cartes s'affichent
# simplement sans image.
bleu "→ visuels (plusieurs minutes pour un catalogue complet)"
python3 "$ETAPES" visuels "$API"

# --- 5bis. Bilan ----------------------------------------------------------
bleu "→ état du catalogue"
python3 "$ETAPES" bilan "$API"

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
