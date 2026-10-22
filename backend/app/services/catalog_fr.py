"""
Passage du catalogue aux noms FRANÇAIS.

POURQUOI CE N'EST PAS UN IMPORT
-------------------------------
Le catalogue est indexe sur (code carte, slug du nom). Importer les noms
francais par ce chemin creerait DEUX fiches pour la meme carte :

    P-084  « Buggy »   (slug « buggy »,  venu de la liste anglaise)
    P-084  « Baggy »   (slug « baggy »,  venu de la liste francaise)

Deux fiches, deux prix a tenir, deux endroits ou chercher — et un
utilisateur qui voit la meme carte deux fois sans comprendre pourquoi.

Ce qu'il faut, ce n'est pas ajouter : c'est RENOMMER. La cle de
rapprochement est donc (code, est-ce une parallele), la seule qui soit vraie
dans les deux langues, et la fiche existante est reecrite sur place — son
prix de reference intact.

CE QUE L'OPERATION APPORTE EN PLUS
----------------------------------
La liste francaise publie l'adresse exacte de chaque illustration. On la
range au passage : c'est une adresse OBSERVEE et non deduite, donc plus sure
que celle que l'enrichissement reconstruit a partir du code, et elle evite
un aller-retour reseau par carte.
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.collectors.card_images import code_canonique
from app.collectors.cardlist_fr import CarteFR, rang_de_parallele
from app.models import MarketCardPrice
from app.services.card_themes import (
    cle_de_recherche, encoder_themes, themes_de_la_carte,
)
from app.services.catalog_import import slug_de_nom

logger = logging.getLogger(__name__)

SOURCE = "cardlist-fr"

def appliquer_noms_francais(db: Session, cartes: List[CarteFR]) -> dict:
    """Reecrit le catalogue avec les noms francais. Rend un compte rendu.

    Une fiche existante est renommee ; une carte inconnue est creee. Le prix
    de reference n'est JAMAIS touche : cette source dit comment la carte
    s'appelle, pas ce qu'elle vaut.
    """
    renommees, creees, inchangees = 0, 0, 0
    visuels = 0
    rejets: List[dict] = []
    exemples: List[dict] = []

    # Une seule requete pour tout le lot, puis un index en memoire : une
    # requete par carte ferait plusieurs milliers d'allers-retours.
    index: Dict[str, List[MarketCardPrice]] = {}
    for ligne in db.query(MarketCardPrice).all():
        index.setdefault((ligne.card_code or "").upper(), []).append(ligne)

    for carte in cartes:
        code = code_canonique(carte.card_code)
        if not code:
            rejets.append({"code": carte.card_code,
                           "raison": "code de carte non reconnu"})
            continue

        rang = carte.rang_variante
        nom = carte.display_name
        slug = slug_de_nom(nom)
        if not slug:
            rejets.append({"code": code, "raison": f"nom inexploitable ({nom!r})"})
            continue

        existantes = index.get(code.upper(), [])
        # La cle est (code, RANG de variante). Pas (code, nom) : les noms
        # different d'une langue a l'autre, c'est tout l'objet de
        # l'operation. Pas (code) seul : un code designe jusqu'a quatre
        # cartes dont les prix vont de 10 € a 695 €.
        cible = next(
            (l for l in existantes if rang_de_parallele(l.name_slug) == rang),
            None,
        )

        derives = dict(
            theme_slugs=encoder_themes(themes_de_la_carte(nom, carte.rarity)),
            search_key=cle_de_recherche(nom, code),
        )

        if cible is None:
            cible = MarketCardPrice(
                card_code=code, name_slug=slug, display_name=nom,
                series_name=carte.series_name, rarity=carte.rarity,
                source=SOURCE, image_url=carte.image_url,
                image_source=SOURCE if carte.image_url else None,
                **derives,
            )
            db.add(cible)
            index.setdefault(code.upper(), []).append(cible)
            creees += 1
            if carte.image_url:
                visuels += 1
            continue

        ancien = cible.display_name
        change = ancien != nom

        if change:
            if len(exemples) < 25:
                exemples.append({"code": code, "avant": ancien, "apres": nom})
            renommees += 1
        else:
            inchangees += 1

        cible.display_name = nom
        cible.name_slug = slug
        cible.series_name = carte.series_name or cible.series_name
        cible.rarity = carte.rarity or cible.rarity
        for cle, valeur in derives.items():
            setattr(cible, cle, valeur)

        # Le visuel observe prime sur celui qui serait deduit : c'est une
        # adresse lue sur la page, pas reconstruite.
        if carte.image_url and cible.image_url != carte.image_url:
            cible.image_url = carte.image_url
            cible.image_source = SOURCE
            visuels += 1

        # price_eur n'apparait nulle part ci-dessus, et c'est voulu.

    db.commit()

    logger.info(
        "Noms FR : %d renommee(s), %d creee(s), %d inchangee(s), %d visuel(s), %d rejet(s)",
        renommees, creees, inchangees, visuels, len(rejets),
    )
    return {
        "lues": len(cartes),
        "renommees": renommees,
        "creees": creees,
        "inchangees": inchangees,
        "visuels": visuels,
        "rejetees": len(rejets),
        "rejets": rejets,
        # Montrer ce qui a change : « 412 renommees » ne veut rien dire tant
        # qu'on n'a pas vu que « Buggy » est devenu « Baggy ».
        "exemples": exemples,
        "prix": (
            "Les prix de reference n'ont pas ete touches : cette source dit "
            "comment les cartes s'appellent, pas ce qu'elles valent."
        ),
    }
