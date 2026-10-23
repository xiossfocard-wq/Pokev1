"""
Application des prix de référence au catalogue.

POURQUOI UN MODULE A PART
-------------------------
Deux sources alimentent le catalogue et elles ne disent pas la même chose :

    la liste officielle    quelles cartes existent, et comment elles
                           s'appellent en français ;
    OPECards               ce qu'elles valent, en euros.

Les mélanger dans un seul import rendrait impossible de relancer l'une sans
l'autre, et surtout de garantir qu'une source ne piétine pas ce que l'autre
a établi. Ici, SEULS le prix, sa variation et la fourchette sont écrits.
Le nom, la série, la rareté et le visuel ne sont pas touchés.

LA CLE DE RAPPROCHEMENT
-----------------------
(code carte, RANG de variante). Pas le nom : il diffère d'une source à
l'autre et c'est précisément ce que l'autre module répare. Pas le code seul :
un code désigne jusqu'à quatre cartes dont les prix vont de 10 € à 695 €.

Le rang est la même numérotation des deux côtés : le suffixe « _p2 » de la
liste officielle et la mention « (Version 3) » d'OPECards désignent la même
deuxième illustration alternative.
"""
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.collectors.card_images import code_canonique
from app.collectors.cardlist_fr import rang_de_parallele
from app.collectors.opecards_prices import PrixCarte
from app.models import MarketCardPrice

logger = logging.getLogger(__name__)

SOURCE = "opecards"

# Au-delà de cet écart relatif, un changement de prix est signalé plutôt
# qu'appliqué en silence. Un prix de référence qui triple du jour au
# lendemain est peut-être réel — ces cartes bougent vite — mais c'est aussi
# la signature d'un rapprochement qui a dérapé, et une marge calculée
# dessus serait fausse sans que personne le sache.
ECART_SUSPECT = 3.0

# Les deux sources ne notent pas la rareté pareil : le jeu de données écrit
# « SEC (Secret Rare) », la boutique écrit « SEC ». Comparer les libellés
# bruts conclurait « rareté différente » pour la totalité du catalogue.
_PARENTHESE = re.compile(r"\s*\(.*\)\s*$")
_SUFFIXE_CARD = re.compile(r"\s+CARD$")


def code_rarete(brut: Optional[str]) -> Optional[str]:
    """« C (Common) » et « C » -> « C ». None si illisible.

    Rend None plutôt que de deviner : une rareté qu'on ne sait pas lire ne
    doit pas servir à écarter un prix. Le filet suivant s'en charge.
    """
    if not brut:
        return None
    texte = _PARENTHESE.sub("", str(brut)).strip().upper()
    return _SUFFIXE_CARD.sub("", texte).strip() or None


def oublier_les_prix_non_confirmes(db: Session, anterieurs_a: datetime,
                                   source: str = SOURCE) -> dict:
    """Efface les prix que la source n'a pas reconfirmés pendant ce passage.

    POURQUOI UN BALAYAGE APRES, ET PAS UNE REMISE A ZERO AVANT
    ----------------------------------------------------------
    Vider les prix puis recharger paraît plus simple, mais ça ouvre une
    fenêtre pendant laquelle le catalogue n'a plus aucun prix — donc plus
    aucune marge, plus aucun score. Et si le rechargement échoue en route,
    cette fenêtre ne se referme pas : on a détruit des données valides pour
    les remplacer par rien.

    Ici, un prix n'est effacé que parce que la source vient de passer et ne
    l'a PAS reconfirmé. On ne retire donc jamais que ce qu'on sait être
    périmé, et jamais avant d'avoir obtenu le remplacement.

    A QUOI CA SERT
    --------------
    Un prix mal rapproché par une version précédente peut n'avoir plus
    aucune candidature légitime : plus rien ne vient l'écraser, et il reste
    en base indéfiniment. C'est exactement le chiffre qui invente une
    bonne affaire. Le balayage est la seule chose qui l'enlève.

    Seuls les prix de CETTE source sont touchés. Les autres gardent les
    leurs : ce balayage répare un rapprochement, il n'arbitre pas entre les
    sources.
    """
    cibles = (db.query(MarketCardPrice)
              .filter(MarketCardPrice.source == source,
                      MarketCardPrice.price_eur.isnot(None),
                      MarketCardPrice.updated_at < anterieurs_a)
              .all())

    exemples = [{"code": l.card_code, "nom": l.display_name,
                 "prix_oublie": round(l.price_eur, 2)}
                for l in cibles[:25]]

    for ligne in cibles:
        ligne.price_eur = None
        ligne.variation_7d_eur = None
        ligne.updated_at = datetime.utcnow()
    db.commit()

    logger.info("Prix %s : %d prix non reconfirme(s) oublie(s)",
                source, len(cibles))

    return {"oubliees": len(cibles), "exemples": exemples,
            "anterieurs_a": anterieurs_a.isoformat()}


def appliquer_prix(db: Session, prix: List[PrixCarte],
                   ecart_suspect: float = ECART_SUSPECT) -> dict:
    """Écrit les prix de référence. Rend un compte rendu.

    Une carte absente du catalogue n'est PAS créée : cette source dit ce que
    valent les cartes, pas lesquelles existent. La créer ici donnerait une
    fiche sans série ni visuel, construite à partir d'un nom de boutique —
    exactement le genre de demi-fiche qui pollue un catalogue.

    EN DEUX TEMPS, ET POURQUOI
    --------------------------
    On rassemble d'abord TOUTES les candidatures de chaque fiche, et on
    tranche ensuite. Écrire au fil de la lecture paraissait plus direct,
    mais ça rendait le résultat dépendant de l'ordre de la page : chaque
    candidature écrasait la précédente, et la survivante était la dernière
    lue. Un tri d'affichage décidait donc d'un prix de référence.

    Rassembler d'abord permet aussi de VOIR qu'une fiche est revendiquée
    par plusieurs prix inconciliables — ce qu'une écriture au fil de l'eau
    ne peut constater qu'après avoir déjà écrit.
    """
    chiffrees, inchangees, sans_fiche, raretes_opposees = 0, 0, 0, 0
    suspects: List[dict] = []
    exemples: List[dict] = []
    conflits: List[dict] = []

    index: Dict[tuple, MarketCardPrice] = {}
    for ligne in db.query(MarketCardPrice).all():
        cle = ((ligne.card_code or "").upper(), rang_de_parallele(ligne.name_slug))
        # Si deux fiches partagent la clé (reliquat d'un ancien import), on
        # garde la première et on laisse l'autre tranquille plutôt que de
        # la chiffrer au hasard.
        index.setdefault(cle, ligne)

    # --- TEMPS 1 : qui revendique quelle fiche ? ---------------------------
    candidatures: Dict[tuple, List[PrixCarte]] = defaultdict(list)
    for carte in prix:
        code = code_canonique(carte.card_code)
        if not code or carte.price_eur is None:
            continue

        cle = (code.upper(), carte.rang_variante)
        cible = index.get(cle)
        if cible is None:
            sans_fiche += 1
            continue

        # LA RARETE DEPARTAGE.
        # Un même code désigne plusieurs cartes — la commune à 12 € et son
        # illustration manga à 850 — et la source les présente parfois sous
        # le même nom, donc sous le même rang. La rareté, elle, est lisible
        # des deux côtés : « C » et « SEC » ne sont pas la même carte.
        rarete_fiche = code_rarete(cible.rarity)
        rarete_prix = code_rarete(carte.rarity)
        if rarete_fiche and rarete_prix and rarete_fiche != rarete_prix:
            raretes_opposees += 1
            continue

        candidatures[cle].append(carte)

    # --- TEMPS 2 : trancher, fiche par fiche -------------------------------
    for cle, retenues in candidatures.items():
        cible = index[cle]
        ancien = cible.price_eur
        montants = sorted(round(c.price_eur, 2) for c in retenues)
        bas, haut = montants[0], montants[-1]

        # PLUSIEURS PRIX INCONCILIABLES POUR UNE SEULE FICHE.
        # On ne tranche pas, et on n'en garde AUCUN. Retenir le plus bas
        # semblait prudent — une erreur par le bas ne fait rater qu'une
        # occasion — mais appliquée plusieurs fois de suite elle pousse le
        # prix au plancher : 0,02 € pour une carte qui en vaut 600. Ce
        # chiffre n'est pas prudent, il est faux, et il retire la carte du
        # radar aussi sûrement qu'une absence de prix — sans le dire.
        #
        # Une fiche sans prix, elle, se compte dans le bilan et se voit.
        if bas > 0 and haut / bas >= ecart_suspect:
            conflits.append({
                "code": cle[0],
                "rang": cle[1],
                "nom": cible.display_name,
                "rarete_fiche": cible.rarity,
                "montants": montants,
                # L'ETAT BRUT DES CANDIDATURES, pour pouvoir constater
                # POURQUOI elles se confondent au lieu de le supposer :
                # c'est le nom et la rareté tels que la source les écrit
                # qui diront quelle distinction le rapprochement a manquée.
                "candidats": [
                    {"nom": c.display_name, "rarete": c.rarity,
                     "prix": round(c.price_eur, 2), "lien": c.detail_url}
                    for c in sorted(retenues, key=lambda c: -c.price_eur)
                ][:4],
            })
            if ancien is not None:
                cible.price_eur = None
                cible.variation_7d_eur = None
                cible.source = SOURCE
                cible.updated_at = datetime.utcnow()
            continue

        # Candidatures concordantes : la plus basse, par simple
        # déterminisme — elles sont à moins d'un facteur « ecart_suspect »
        # l'une de l'autre, donc le choix ne change rien au fond, mais il
        # ne doit pas dépendre de l'ordre de lecture.
        carte = min(retenues, key=lambda c: c.price_eur)

        # L'ECART est mesuré entre l'ancien prix et celui RETENU — pas
        # entre deux candidatures du même passage. Signaler un écart qu'on
        # vient soi-même d'écarter enverrait vérifier un chiffre qui n'a
        # jamais été appliqué.
        if ancien is not None and ancien > 0:
            facteur = max(carte.price_eur / ancien,
                          ancien / max(carte.price_eur, 0.01))
            if facteur >= ecart_suspect:
                suspects.append({
                    "code": cle[0], "nom": cible.display_name,
                    "avant": round(ancien, 2), "apres": round(carte.price_eur, 2),
                    "facteur": round(facteur, 1),
                })

        if ancien == carte.price_eur:
            inchangees += 1
        else:
            chiffrees += 1
            if len(exemples) < 25:
                exemples.append({
                    "code": cle[0], "nom": cible.display_name,
                    "avant": round(ancien, 2) if ancien is not None else None,
                    "apres": round(carte.price_eur, 2),
                })

        cible.price_eur = carte.price_eur
        cible.variation_7d_eur = carte.variation_eur
        cible.source = SOURCE
        cible.updated_at = datetime.utcnow()
        if carte.rarity and not cible.rarity:
            cible.rarity = carte.rarity

    db.commit()

    logger.info("Prix OPECards : %d chiffree(s), %d inchangee(s), %d sans fiche, "
                "%d rarete(s) opposee(s), %d conflit(s), %d ecart(s) suspect(s)",
                chiffrees, inchangees, sans_fiche, raretes_opposees,
                len(conflits), len(suspects))

    restantes = (db.query(MarketCardPrice)
                 .filter(MarketCardPrice.price_eur.is_(None)).count())

    return {
        "lus": len(prix),
        "chiffrees": chiffrees,
        "inchangees": inchangees,
        # Une carte vue chez la boutique mais absente du catalogue : le plus
        # souvent une serie que la liste officielle n'a pas encore chargee.
        "sans_fiche": sans_fiche,
        # Un prix ECARTE parce qu'il vise une carte de rarete differente.
        # C'est une protection qui a joue, pas une panne.
        "raretes_opposees": raretes_opposees,
        # Des prix inconciliables revendiquaient une meme fiche : AUCUN n'a
        # ete retenu, et l'etat brut des candidatures est joint pour qu'on
        # puisse voir quelle distinction le rapprochement a manquee.
        "conflits": conflits,
        "exemples": exemples,
        # Les ecarts enormes sont RENDUS, pas tus. Ils sont souvent reels sur
        # ce marche, mais ils sont aussi la signature d'un mauvais
        # rapprochement, et une marge fausse ne se voit pas.
        "ecarts_suspects": suspects,
        "sans_prix_restantes": restantes,
    }
