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
import os
import sys
import time
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.request

API_PAR_DEFAUT = "http://localhost:8000"

# Au-delà de cet âge, les prix sont relus au démarrage ; en deçà, on ouvre le
# site tout de suite. La tâche de 02:00 les rafraîchit chaque nuit quand
# l'application tourne : un PC éteint la nuit les retrouve donc au plus
# vieux de la veille, et c'est ce cas que ce seuil rattrape.
FRAICHEUR_HEURES = 20


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
    """Pose les visuels qui se déduisent du code, en quelques secondes.

    L'ancienne étape vérifiait les cartes une à une, avec la pause qu'on
    doit au site interrogé : de dix à quarante minutes, pendant lesquelles
    le site restait fermé. Or l'adresse d'un visuel se déduit du code. Un
    échantillon vérifié suffit à établir le format, et les autres adresses
    se posent d'un coup.

    Ce qui résiste à la déduction se complète en arrière-plan, pendant que
    le site est ouvert : attendre ces dernières cartes pour l'ouvrir n'avait
    aucun sens.
    """
    try:
        d = _appeler(f"{base}/api/admin/deduce-card-images", methode="POST", delai=300)
    except Exception as erreur:
        print(f"   déduction impossible : {str(erreur)[:60]}")
        print("   les visuels se compléteront en arrière-plan.")
        return

    groupes = d.get("groupes") or []
    if not groupes:
        print("   tous les visuels connus sont déjà en place.")
        return

    poses = 0
    for g in groupes:
        n = g.get("deduites", 0) + g.get("echantillon_servi", 0)
        if g.get("format_etabli"):
            poses += n
            print(f"   {n} visuel(s) posé(s) d'un coup — {g['groupe']} "
                  f"(échantillon {g['echantillon_servi']}/{g['echantillon']})")
        else:
            print(f"   {g['groupe']} : format non établi "
                  f"(échantillon {g['echantillon_servi']}/{g['echantillon']})")

    # DIRE VRAI SUR CE QUI N'A PAS MARCHÉ. « Le site ne répond pas » et « le
    # site répond sans image » n'ont ni la même cause ni le même remède.
    if not poses:
        if d.get("http_responses", 0) == 0 and d.get("network_errors", 0):
            print("   les sites officiels ne répondent pas depuis cette machine.")
        else:
            print("   les sites répondent, mais pas au format attendu. Pour voir")
            print("   ce qu'ils répondent, adresse par adresse :")
            print(f"     {base}/api/admin/debug-card-images?code=OP01-001&anglais=true")
    print("   le reste se complète en arrière-plan, site ouvert.")


def _donnees_du_jour(base: str) -> str:
    """L'heure du dernier relevé des prix s'il est assez récent, sinon "".

    Rend "" — donc « tout recharger » — dans le doute : prix jamais relevés,
    API qui ne répond pas, ou rechargement complet demandé. Se tromper dans
    ce sens coûte une attente ; dans l'autre, des prix périmés.
    """
    if os.environ.get("DEMARRAGE_COMPLET"):
        return ""
    try:
        etat = _appeler(f"{base}/api/admin/price-index-status")
        brut = etat.get("prices_updated_at")
        if not brut:
            return ""
        releve = datetime.fromisoformat(brut)
    except Exception:
        return ""
    if datetime.utcnow() - releve > timedelta(hours=FRAICHEUR_HEURES):
        return ""
    # L'heure est en UTC côté serveur ; on l'affiche en heure locale.
    return (releve.replace(tzinfo=timezone.utc).astimezone()
            .strftime("%d/%m à %H:%M"))


def _deja_a_jour(base: str) -> bool:
    """Saute une étape longue si les données sont du jour, et le dit."""
    releve = _donnees_du_jour(base)
    if not releve:
        return False
    print(f"   déjà à jour (prix relevés le {releve}) — étape sautée.")
    print("   Pour tout recharger : ajouter -Complet à la commande de démarrage.")
    return True


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
    sans_rang = 0
    marqueurs = {}
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
        sans_rang += r.get("variantes_sans_rang", 0)
        suspects.extend(r.get("ecarts_suspects") or [])
        conflits.extend(r.get("conflits") or [])
        for v in r.get("variantes_vues") or []:
            marqueurs[v.get("variante") or "?"] = \
                marqueurs.get(v.get("variante") or "?", 0) + 1

    _fin_progression()
    print(f"   {chiffrees} carte(s) chiffrée(s)")
    # Une protection qui joue en silence empêche de voir que la source a
    # changé de forme. Celle-ci écarte le prix d'une carte de rareté
    # différente — le gros prix d'une illustration manga qui visait la
    # fiche de la commune — et le nombre doit rester petit.
    if opposees:
        print(f"   {opposees} prix écarté(s) : rareté différente de la fiche visée")
    # Les variantes que la source ne sait pas situer. On montre le
    # VOCABULAIRE — les libellés distincts et leur nombre — plutôt que des
    # centaines de lignes identiques : c'est la liste des mentions qui dit
    # quelle correspondance reste à établir.
    if sans_rang:
        print(f"   {sans_rang} variante(s) non rattachée(s) : la source ne dit pas")
        print("   quelle alternative elles désignent, leur prix n'est appliqué")
        print("   à aucune fiche. Mentions rencontrées :")
        for marque, nombre in sorted(marqueurs.items(), key=lambda c: -c[1])[:8]:
            print(f"     « {marque} » ×{nombre}")

    # Le détail BRUT des candidatures, pas seulement leur nombre. Ce qui
    # manque pour corriger la cause, c'est de voir le nom et la rareté tels
    # que la source les écrit : c'est ça qui dit quelle distinction le
    # rapprochement a manquée, au lieu de la supposer.
    if conflits:
        print(f"   {len(conflits)} fiche(s) laissée(s) sans prix : plusieurs prix")
        print("   inconciliables les revendiquaient. Détail, pour diagnostic :")
        for c in conflits[:4]:
            print(f"     {c['code']} rang {c.get('rang', 0)} — fiche "
                  f"« {c['nom']} » [{c.get('rarete_fiche') or 'rareté inconnue'}]")
            for cand in c.get("candidats") or []:
                print(f"        {cand['prix']}€  {cand['rarete'] or '—'}  "
                      f"« {cand['nom']} »")
        if len(conflits) > 4:
            print(f"     … et {len(conflits) - 4} autre(s)")
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
        if not _deja_a_jour(base):
            passer_aux_noms_francais(base)
        return 0
    if etape == "prix":
        if not _deja_a_jour(base):
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
