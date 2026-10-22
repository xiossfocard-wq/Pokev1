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
from datetime import datetime
from typing import Dict, List

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


def appliquer_prix(db: Session, prix: List[PrixCarte],
                   ecart_suspect: float = ECART_SUSPECT) -> dict:
    """Écrit les prix de référence. Rend un compte rendu.

    Une carte absente du catalogue n'est PAS créée : cette source dit ce que
    valent les cartes, pas lesquelles existent. La créer ici donnerait une
    fiche sans série ni visuel, construite à partir d'un nom de boutique —
    exactement le genre de demi-fiche qui pollue un catalogue.
    """
    chiffrees, inchangees, sans_fiche = 0, 0, 0
    suspects: List[dict] = []
    exemples: List[dict] = []

    index: Dict[tuple, MarketCardPrice] = {}
    for ligne in db.query(MarketCardPrice).all():
        cle = ((ligne.card_code or "").upper(), rang_de_parallele(ligne.name_slug))
        # Si deux fiches partagent la clé (reliquat d'un ancien import), on
        # garde la première et on laisse l'autre tranquille plutôt que de
        # la chiffrer au hasard.
        index.setdefault(cle, ligne)

    for carte in prix:
        code = code_canonique(carte.card_code)
        if not code:
            continue

        cible = index.get((code.upper(), carte.rang_variante))
        if cible is None:
            sans_fiche += 1
            continue

        ancien = cible.price_eur
        if ancien is not None and ancien > 0:
            rapport = max(carte.price_eur / ancien, ancien / max(carte.price_eur, 0.01))
            if rapport >= ecart_suspect:
                suspects.append({
                    "code": code, "nom": cible.display_name,
                    "avant": round(ancien, 2), "apres": round(carte.price_eur, 2),
                    "facteur": round(rapport, 1),
                })

        if ancien == carte.price_eur:
            inchangees += 1
        else:
            chiffrees += 1
            if len(exemples) < 25:
                exemples.append({
                    "code": code, "nom": cible.display_name,
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
                "%d ecart(s) suspect(s)",
                chiffrees, inchangees, sans_fiche, len(suspects))

    restantes = (db.query(MarketCardPrice)
                 .filter(MarketCardPrice.price_eur.is_(None)).count())

    return {
        "lus": len(prix),
        "chiffrees": chiffrees,
        "inchangees": inchangees,
        # Une carte vue chez la boutique mais absente du catalogue : le plus
        # souvent une serie que la liste officielle n'a pas encore chargee.
        "sans_fiche": sans_fiche,
        "exemples": exemples,
        # Les ecarts enormes sont RENDUS, pas tus. Ils sont souvent reels sur
        # ce marche, mais ils sont aussi la signature d'un mauvais
        # rapprochement, et une marge fausse ne se voit pas.
        "ecarts_suspects": suspects,
        "sans_prix_restantes": restantes,
    }
