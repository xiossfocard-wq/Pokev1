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
    python3 scripts/etapes_demarrage.py noms-fr    [url]
    python3 scripts/etapes_demarrage.py prix       [url]
    python3 scripts/etapes_demarrage.py visuels    [url]
    python3 scripts/etapes_demarrage.py annonces   [url]
    python3 scripts/etapes_demarrage.py bilan      [url]
"""
import json
import math
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


def _series(base: str, cle: str) -> dict:
    """Les séries à charger pour une source. {} si elle est injoignable."""
    try:
        return _appeler(f"{base}/api/admin/fr-series", delai=300).get(cle) or {}
    except Exception:
        return {}


# Vrai terminal ou sortie redirigée ? Le retour chariot n'écrase une ligne
# que sur un terminal. Redirigé vers un fichier, il n'efface rien et les 37
# étapes s'empilent sur une seule ligne illisible.
_TERMINAL = sys.stdout.isatty()


def _progression(faites: int, total: int, libelle: str) -> None:
    """Dit où on en est, sans noyer le terminal sous 37 lignes.

    Le compte ET le nom de la série : le compte dit où on en est, le nom
    dit que ça avance vraiment plutôt que de tourner sur place.
    """
    texte = f"     [{faites:2}/{total}] {libelle[:46]}"
    if _TERMINAL:
        print(f"\r{texte:<62}", end="", flush=True)
    else:
        print(texte, flush=True)


def _fin_progression() -> None:
    """Efface la ligne de progression, là où elle s'efface."""
    if _TERMINAL:
        print("\r" + " " * 62 + "\r", end="")


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


def passer_aux_noms_francais(base: str) -> None:
    """Remplace les noms anglais par les noms FRANÇAIS officiels.

    L'instantané du dépôt vient d'un relevé de la liste ANGLAISE : pour les
    personnages cela passe, mais « Buggy » s'appelle « Baggy » en français,
    « Hive » s'appelle « Ruche », et les cartes Événement sont intégralement
    traduites. Sans cette étape, un vendeur français qui écrit « Baggy » ne
    rencontre jamais la fiche.

    Chargé SÉRIE PAR SÉRIE pour afficher la progression : tout demander
    d'un coup laissait le terminal muet de longues minutes, ce qui se lit
    comme un plantage et pas comme du travail.
    """
    series = _series(base, "officielles")
    if not series:
        print("   liste officielle injoignable : les cartes gardent leur nom anglais.")
        return

    total = len(series)
    renommees = creees = visuels = 0
    echecs = []
    exemples = []

    for i, (valeur, libelle) in enumerate(series.items(), start=1):
        _progression(i, total, libelle)
        try:
            r = _appeler(f"{base}/api/admin/load-fr-names?series={valeur}",
                         methode="POST", delai=600)
        except Exception as erreur:
            echecs.append((libelle, str(erreur)[:60]))
            continue
        renommees += r.get("renommees", 0)
        creees += r.get("creees", 0)
        visuels += r.get("visuels", 0)
        for e in (r.get("exemples") or []):
            if len(exemples) < 5:
                exemples.append(e)

    _fin_progression()
    print(f"   {renommees} renommée(s), {creees} créée(s), {visuels} visuel(s)")
    for e in exemples:
        print(f"     {e['avant']} → {e['apres']}")
    for libelle, raison in echecs[:3]:
        print(f"     série « {libelle[:34]} » en échec : {raison}")
    if len(echecs) > 3:
        print(f"     … et {len(echecs) - 3} autre(s) série(s) en échec")


def charger_les_prix(base: str) -> None:
    """Écrit les prix de référence en euros, depuis OPECards.fr.

    C'est ce qui allume les marges et les scores d'affaire : sans prix, une
    annonce peut être identifiée mais pas jugée.

    L'étape la plus longue de toutes — des centaines de pages, avec une
    pause entre chacune pour ne pas marteler un site communautaire. D'où la
    progression affichée : sans elle, l'attente est indiscernable d'un
    blocage.
    """
    series = _series(base, "prix")
    if not series:
        print("   source de prix injoignable.")
        print("   Les cartes restent sans prix : le catalogue est consultable,")
        print("   mais aucune marge n'est calculée.")
        return

    total = len(series)
    chiffrees = 0
    opposees = 0
    echecs = []
    suspects = []
    conflits = []
    depart = time.monotonic()

    for i, (valeur, libelle) in enumerate(series.items(), start=1):
        _progression(i, total, libelle)
        try:
            r = _appeler(f"{base}/api/admin/load-fr-prices?series={valeur}",
                         methode="POST", delai=1800)
        except Exception as erreur:
            echecs.append((libelle, str(erreur)[:60]))
            continue
        chiffrees += r.get("chiffrees", 0)
        opposees += r.get("raretes_opposees", 0)
        suspects.extend(r.get("ecarts_suspects") or [])
        conflits.extend(r.get("conflits") or [])

    _fin_progression()
    print(f"   {chiffrees} carte(s) chiffrée(s)")
    # Une protection qui joue en silence empêche de voir que la source a
    # changé de forme. Celle-ci écarte le prix d'une carte de rareté
    # différente — le gros prix d'une illustration manga qui visait la
    # fiche de la commune — et le nombre doit rester petit.
    if opposees:
        print(f"   {opposees} prix écarté(s) : rareté différente de la fiche visée")
    for c in conflits[:5]:
        print(f"     {c['code']} réclamé à {c['concurrents'][1]}€ ET "
              f"{c['concurrents'][0]}€ — le plus bas retenu")
    for e in suspects[:5]:
        print(f"     écart ×{e['facteur']} sur {e['code']} "
              f"({e['avant']}€ → {e['apres']}€) — à vérifier")
    for libelle, raison in echecs[:3]:
        print(f"     série « {libelle[:34]} » en échec : {raison}")
    if len(echecs) > 3:
        print(f"     … et {len(echecs) - 3} autre(s) série(s) en échec")

    _balayer_les_prix_perimes(base, depart, chiffrees, echecs)


def _balayer_les_prix_perimes(base: str, depart: float, chiffrees: int,
                              echecs: list) -> None:
    """Oublie les prix que la source vient de passer sans reconfirmer.

    Recharger ne suffit pas à réparer un mauvais rapprochement : un prix
    écrit par erreur peut n'avoir plus aucune candidature légitime, donc
    plus rien pour l'écraser. Ce balayage est la seule chose qui l'enlève.

    IL NE SE LANCE QUE SI TOUT A ETE LU.
    Une série non lue, c'est un paquet de cartes que la source n'a pas eu
    l'occasion de confirmer : les effacer les prendrait pour périmées alors
    qu'elles sont seulement manquées. On préfère garder un prix douteux une
    nuit de plus que d'en détruire des centaines de valides.
    """
    if echecs:
        print(f"   balayage reporté : {len(echecs)} série(s) non lue(s)")
        print("   (effacer maintenant retirerait des prix encore valides)")
        return
    if not chiffrees:
        return

    # La borne doit COUVRIR la durée du rechargement : tout ce qui a été
    # touché pendant est gardé. On arrondit vers le haut, ce qui recule la
    # borne — donc garde davantage. L'erreur conservatrice est de ce côté.
    minutes = math.ceil((time.monotonic() - depart) / 60) + 1
    try:
        r = _appeler(f"{base}/api/admin/sweep-fr-prices?minutes={minutes}",
                     methode="POST", delai=300)
    except Exception as erreur:
        print(f"   balayage impossible : {str(erreur)[:60]}")
        return

    oubliees = r.get("oubliees", 0)
    if oubliees:
        print(f"   {oubliees} prix périmé(s) oublié(s) : la source ne les")
        print("   confirme plus. Une carte sans prix vaut mieux qu'un faux.")


def premiere_collecte(base: str) -> None:
    """Déclenche un premier passage de collecte d'annonces.

    Sans elle, le planificateur attend son intervalle — vingt minutes par
    défaut — avant d'aller voir quoi que ce soit. On ouvrirait donc
    l'application sur un tableau de bord vide, sans rien qui distingue
    « ça n'a pas encore commencé » de « c'est cassé ».

    Un échec n'est pas grave : le planificateur repassera tout seul. On le
    dit, et on continue.
    """
    try:
        avant = _appeler(f"{base}/api/listings?limit=1", delai=30)
        deja = len(avant) if isinstance(avant, list) else 0
    except Exception:
        deja = 0
    if deja:
        print(f"   {deja} annonce(s) déjà en base, passage non déclenché")
        return

    try:
        _appeler(f"{base}/api/admin/run-check-now", methode="POST", delai=900)
    except Exception as erreur:
        print(f"   collecte impossible pour l'instant : {erreur}")
        print("   le planificateur réessaiera tout seul dans quelques minutes.")
        return

    try:
        apres = _appeler(f"{base}/api/listings?limit=200", delai=60)
        nombre = len(apres) if isinstance(apres, list) else 0
    except Exception:
        nombre = 0

    if nombre:
        print(f"   {nombre} annonce(s) collectée(s)")
    else:
        # Vinted est nettement plus hostile aux adresses de centre de
        # données qu'à une connexion résidentielle. Dire les deux causes
        # possibles vaut mieux qu'un « 0 » muet.
        print("   aucune annonce pour l'instant.")
        print("   Soit il n'y a rien en vente qui corresponde, soit la")
        print("   collecte a été refusée. Le planificateur réessaiera.")


def bilan(base: str) -> None:
    """Dit où en est le catalogue, en une poignée de lignes.

    Sans ce récapitulatif, « 3 868 cartes » se lirait comme un catalogue
    français complet et chiffré, alors que la couverture dépend de ce qui a
    réellement pu être chargé.
    """
    try:
        v = _appeler(f"{base}/api/cards/filters", delai=60)
    except Exception as erreur:
        print(f"   bilan indisponible : {erreur}")
        return

    total = v.get("total_cards", 0)
    print(f"   {total} cartes au catalogue")

    for langue in v.get("languages") or []:
        part = (100 * langue["count"] / total) if total else 0
        print(f"     {langue['label']:10} {langue['count']:6}  ({part:.0f} %)")

    try:
        chiffrees = _appeler(f"{base}/api/cards?limite=1&price_min=0", delai=60)
        print(f"     avec un prix {chiffrees.get('total', 0):6}")
    except Exception:
        pass

    print(f"     séries      {len(v.get('series') or []):6}")


def main() -> int:
    etape = sys.argv[1] if len(sys.argv) > 1 else ""
    base = (sys.argv[2] if len(sys.argv) > 2 else API_PAR_DEFAUT).rstrip("/")

    if etape == "attendre":
        return 0 if attendre_api(base) else 1
    if etape == "catalogue":
        return 0 if remplir_catalogue(base) > 0 else 1
    if etape == "noms-fr":
        passer_aux_noms_francais(base)
        return 0
    if etape == "prix":
        charger_les_prix(base)
        return 0
    if etape == "annonces":
        premiere_collecte(base)
        return 0
    if etape == "bilan":
        bilan(base)
        return 0
    if etape == "visuels":
        remplir_visuels(base)
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
