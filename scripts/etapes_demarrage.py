#!/usr/bin/env python3
"""
Les étapes du démarrage local qui demandent plus qu'un appel curl.

Séparé du script shell pour une raison pratique : ces étapes réclament des
boucles, des conditions d'arrêt et des messages lisibles, et tout cela
écrit en ligne dans du bash devient illisible et fragile à citer.

Rien ici n'est spécifique au démarrage : chaque fonction peut être appelée
seule, et le module n'a besoin que de la bibliothèque standard.

    python3 scripts/etapes_demarrage.py attendre   [url]
    python3 scripts/etapes_demarrage.py catalogue  [url]
    python3 scripts/etapes_demarrage.py visuels    [url]
"""
import json
import sys
import time
import urllib.error
import urllib.request

API_PAR_DEFAUT = "http://localhost:8000"

# Taille de lot pour les visuels. La route plafonne à 200 : c'est délibéré,
# pour ne pas marteler la source des images.
LOT_VISUELS = 200

# Garde-fou de la boucle des visuels. Le catalogue compte ~3900 cartes, donc
# ~20 tours suffisent ; au-delà, c'est que quelque chose ne progresse pas et
# il vaut mieux rendre la main que tourner en rond.
MAX_TOURS = 30


def _appeler(url: str, methode: str = "GET", delai: int = 120):
    requete = urllib.request.Request(url, method=methode)
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def attendre_api(base: str, secondes: int = 45) -> bool:
    """Rend True dès que l'API répond, False après `secondes`."""
    for _ in range(secondes):
        try:
            _appeler(f"{base}/api/health", delai=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def nombre_de_cartes(base: str) -> int:
    try:
        return int(_appeler(f"{base}/api/cards?limite=1", delai=15).get("total", 0))
    except Exception:
        return 0


def remplir_catalogue(base: str) -> int:
    """Charge le catalogue s'il est vide. Rend le nombre de cartes final.

    C'est l'étape qu'on ne devine pas : sans elle l'application démarre
    correctement, n'affiche aucune carte, et rien n'indique que c'est normal.
    """
    deja = nombre_de_cartes(base)
    if deja > 0:
        print(f"   catalogue déjà rempli ({deja} cartes)")
        return deja

    try:
        rapport = _appeler(f"{base}/api/admin/load-opcg-catalog",
                           methode="POST", delai=300)
    except Exception as erreur:
        print(f"   échec du chargement : {erreur}")
        return 0

    if rapport.get("erreur"):
        print(f"   {rapport['erreur']}")
        return 0

    creees = rapport.get("creees", 0)
    rejets = rapport.get("rejetees", 0)
    sans_prix = rapport.get("sans_prix", 0)
    print(f"   {creees} cartes créées, {rejets} rejet(s)")
    if sans_prix:
        print(f"   {sans_prix} sans prix de référence : cette source dit quelles")
        print("   cartes existent, pas ce qu'elles valent.")
    return nombre_de_cartes(base)


def remplir_visuels(base: str) -> None:
    """Boucle sur l'enrichissement des visuels jusqu'à ce qu'il n'avance plus.

    La condition d'arrêt mérite une explication. La route sélectionne les
    cartes dont l'image manque, en remettant en queue de file celles déjà
    tentées — mais sans jamais les exclure. Donc tant qu'une seule carte
    reste sans image, `examined` ne tombe jamais à zéro : s'arrêter là-dessus
    bouclerait indéfiniment.

    On s'arrête donc sur l'ABSENCE DE PROGRÈS : un lot qui ne trouve plus
    aucune image nouvelle signifie soit que tout est récupéré, soit que la
    source est hors d'atteinte. Dans les deux cas, insister ne sert à rien.
    """
    total = 0
    for tour in range(1, MAX_TOURS + 1):
        try:
            r = _appeler(
                f"{base}/api/admin/enrich-card-images?limit={LOT_VISUELS}",
                methode="POST", delai=600)
        except Exception as erreur:
            print(f"   interrompu au tour {tour} : {erreur}")
            break

        trouvees = r.get("found", 0)
        examinees = r.get("examined", 0)
        total += trouvees

        if examinees == 0:
            break
        if trouvees == 0:
            if total == 0:
                print("   aucune image récupérée — la source est probablement")
                print("   injoignable depuis cette machine. Le reste fonctionne :")
                print("   les cartes s'afficheront sans visuel.")
            break
        print(f"   tour {tour} : +{trouvees} (total {total})")

    if total:
        print(f"   {total} visuels récupérés")


def main() -> int:
    etape = sys.argv[1] if len(sys.argv) > 1 else ""
    base = (sys.argv[2] if len(sys.argv) > 2 else API_PAR_DEFAUT).rstrip("/")

    if etape == "attendre":
        return 0 if attendre_api(base) else 1
    if etape == "catalogue":
        return 0 if remplir_catalogue(base) > 0 else 1
    if etape == "visuels":
        remplir_visuels(base)
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
