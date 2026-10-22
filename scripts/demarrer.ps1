# Démarrage local sous Windows, tout en un.
#
# POURQUOI CE SCRIPT EXISTE À CÔTÉ DE demarrer.sh
# -----------------------------------------------
# Le script bash suppose Git Bash ou WSL. Sous Windows, ça veut dire
# installer un deuxième terminal, y coller des commandes qui s'y collent
# mal, et distinguer une fenêtre MINGW64 d'une fenêtre UCRT64 — trois
# obstacles avant la première ligne utile.
#
# Celui-ci tourne dans le terminal fourni avec Windows. Il fait exactement
# les mêmes étapes, dans le même ordre, avec les mêmes messages.
#
# Usage, dans PowerShell, depuis le dossier du projet :
#
#     powershell -ExecutionPolicy Bypass -File scripts\demarrer.ps1
#
# Le « -ExecutionPolicy Bypass » n'affaiblit rien durablement : il vaut
# pour ce lancement seulement. Sans lui, Windows refuse par défaut
# d'exécuter un script téléchargé, et le refus n'explique pas pourquoi.
#
# Arrêt : Ctrl+C.

$ErrorActionPreference = "Stop"

$Racine   = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $Racine "backend"
$Frontend = Join-Path $Racine "frontend"
$Etapes   = Join-Path $PSScriptRoot "etapes_demarrage.py"
$PortApi  = 8000
$PortWeb  = 3000
$Api      = "http://localhost:$PortApi"

function Bleu  ($t) { Write-Host $t -ForegroundColor Cyan }
function Vert  ($t) { Write-Host $t -ForegroundColor Green }
function Rouge ($t) { Write-Host $t -ForegroundColor Red }

# --- 1. Outils requis ----------------------------------------------------
# On cherche python sous ses trois noms possibles sous Windows. L'installeur
# officiel pose « python », le lanceur pose « py », et seules certaines
# installations posent « python3 » : exiger un seul de ces noms, c'est
# refuser de démarrer chez une partie des gens pour une question d'étiquette.
function Trouver-Python {
    foreach ($candidat in @("python", "python3", "py")) {
        $chemin = Get-Command $candidat -ErrorAction SilentlyContinue
        if (-not $chemin) { continue }
        try { $v = & $candidat --version 2>&1 } catch { continue }
        if ("$v" -match "Python (\d+)\.(\d+)") {
            $majeure = [int]$Matches[1]; $mineure = [int]$Matches[2]
            if ($majeure -gt 3 -or ($majeure -eq 3 -and $mineure -ge 11)) {
                return [pscustomobject]@{ Commande = $candidat; Version = "$majeure.$mineure" }
            }
            # Trouvé mais trop ancien : on le retient pour le dire
            # précisément plutôt que « python introuvable », qui enverrait
            # réinstaller ce qui est déjà là.
            $script:PythonTropVieux = "$majeure.$mineure"
        }
    }
    return $null
}

$script:PythonTropVieux = $null
$py = Trouver-Python
$node = Get-Command node -ErrorAction SilentlyContinue
$npm  = Get-Command npm  -ErrorAction SilentlyContinue

if (-not $py -or -not $node -or -not $npm) {
    Rouge "X Il manque de quoi lancer l'application."
    Write-Host ""
    if (-not $py) {
        if ($script:PythonTropVieux) {
            Write-Host "  Python $($script:PythonTropVieux) est installé, mais il en faut 3.11 ou plus"
        } else {
            Write-Host "  Python 3.11 ou plus"
        }
        Write-Host "     -> https://www.python.org/downloads/"
        Write-Host "     (cocher « Add Python to PATH » pendant l'installation)"
    }
    if (-not $node -or -not $npm) {
        Write-Host "  Node.js 20 ou plus"
        Write-Host "     -> https://nodejs.org/"
    }
    Write-Host ""
    Write-Host "  Installer ce qui manque, FERMER puis ROUVRIR ce terminal, et relancer."
    Write-Host "  (un terminal déjà ouvert ne voit pas un programme installé après lui)"
    exit 1
}

Vert "OK  python $($py.Version) · node $(& node --version)"

# --- 1bis. Le port est-il libre ? ---------------------------------------
# Ctrl+C n'exécute pas toujours le bloc de nettoyage sous PowerShell : une
# API du lancement précédent peut encore tourner. Sans ce contrôle, le
# démarrage échoue plus loin sur « address already in use », une phrase qui
# ne dit pas quoi faire.
$occupe = Get-NetTCPConnection -LocalPort $PortApi -State Listen -ErrorAction SilentlyContinue
if ($occupe) {
    Rouge "X Le port $PortApi est déjà utilisé."
    Write-Host ""
    Write-Host "  C'est sans doute l'application d'un lancement précédent."
    Write-Host "  Pour l'arrêter :"
    Write-Host ""
    Write-Host "     Stop-Process -Id $($occupe[0].OwningProcess) -Force"
    Write-Host ""
    Write-Host "  Puis relancer ce script."
    exit 1
}

# --- 2. Dépendances du backend ------------------------------------------
Set-Location $Backend
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Bleu "-> création de l'environnement Python (une seule fois)"
    & $py.Commande -m venv (Join-Path $Backend ".venv")
    if (-not (Test-Path $VenvPython)) {
        Rouge "X La création de l'environnement Python a échoué."
        exit 1
    }
}

# On appelle le python de l'environnement directement, sans « activer ».
# L'activation passe par un script .ps1 que Windows peut refuser d'exécuter,
# et ce refus n'a rien à voir avec le projet.
Bleu "-> installation des dépendances Python (c'est long, et sans affichage)"
& $VenvPython -m pip install --quiet --upgrade pip
& $VenvPython -m pip install --quiet -r (Join-Path $Backend "requirements.txt")
if ($LASTEXITCODE -ne 0) { Rouge "X L'installation des dépendances a échoué."; exit 1 }
Vert "OK  backend prêt"

# --- 3. Démarrage du backend --------------------------------------------
Bleu "-> démarrage de l'API sur le port $PortApi"
$journal = Join-Path $Backend "api.log"
$processusApi = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "$PortApi" `
    -WorkingDirectory $Backend -PassThru -NoNewWindow `
    -RedirectStandardOutput $journal -RedirectStandardError "$journal.err"

# Quoi qu'il arrive ensuite, l'API s'arrête avec le script : la laisser
# tourner en arrière-plan occuperait le port 8000 et ferait échouer le
# lancement suivant, sans que la cause soit visible nulle part.
try {
    # Le code de RETOUR, pas la sortie : cette étape n'affiche rien, et
    # tester sa sortie reviendrait à la déclarer toujours en échec.
    & $VenvPython $Etapes attendre $Api
    if ($LASTEXITCODE -ne 0) {
        Rouge "X L'API ne répond pas. Dernières lignes de backend\api.log :"
        if (Test-Path $journal) { Get-Content $journal -Tail 20 }
        if (Test-Path "$journal.err") { Get-Content "$journal.err" -Tail 20 }
        exit 1
    }
    Vert "OK  API en ligne — $Api"

    # --- 4. Catalogue : L'ÉTAPE QU'ON NE DEVINE PAS ---------------------
    Bleu "-> catalogue"
    & $VenvPython $Etapes catalogue $Api
    if ($LASTEXITCODE -eq 0) { Vert "OK  catalogue prêt" }
    else { Rouge "X Le catalogue est resté vide — voir backend\api.log" }

    # --- 4bis. Noms français --------------------------------------------
    Bleu "-> noms français (liste officielle)"
    & $VenvPython $Etapes noms-fr $Api

    # --- 4ter. Prix de référence ----------------------------------------
    Bleu "-> prix de référence (très long : des centaines de pages)"
    & $VenvPython $Etapes prix $Api

    # --- 5. Visuels ------------------------------------------------------
    Bleu "-> visuels"
    & $VenvPython $Etapes visuels $Api

    # --- 5ter. Première collecte d'annonces -----------------------------
    Bleu "-> première collecte d'annonces"
    & $VenvPython $Etapes annonces $Api

    # --- 5bis. Bilan -----------------------------------------------------
    Bleu "-> état du catalogue"
    & $VenvPython $Etapes bilan $Api

    # --- 6. Frontend -----------------------------------------------------
    Set-Location $Frontend
    if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
        Bleu "-> installation des dépendances web (une seule fois, c'est long)"
        & npm install --silent
        if ($LASTEXITCODE -ne 0) { Rouge "X npm install a échoué."; exit 1 }
    }

    Write-Host ""
    Vert "================================================"
    Vert "  Tableau de bord : http://localhost:$PortWeb"
    Vert "  Explorateur     : http://localhost:$PortWeb/explorer"
    Vert "  Ctrl+C pour tout arrêter"
    Vert "================================================"
    Write-Host ""

    & npm run dev
}
finally {
    if ($processusApi -and -not $processusApi.HasExited) {
        Bleu "-> arrêt du backend"
        Stop-Process -Id $processusApi.Id -Force -ErrorAction SilentlyContinue
    }
}
