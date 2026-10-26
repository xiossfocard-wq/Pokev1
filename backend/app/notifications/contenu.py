"""
Ce que dit une alerte de bonne affaire, commun a Telegram et a l'e-mail.

Les deux messages etaient ecrits separement, et disaient la meme chose de
travers : « Prix : 5.75 € (+0.00 € port) » pour un achat Vinted qui coute
9,64 EUR une fois payé, et une « marge » de revente que le collectionneur,
qui garde la carte, ne touchera jamais. Ils disent maintenant ce que
l'achat coute vraiment, et ce qu'il fait gagner dans le mode choisi.
"""
from typing import List, Optional, Tuple


def euros(valeur: Optional[float]) -> str:
    """« 3,75 € » : le format que lit un acheteur francais."""
    if valeur is None:
        return "—"
    return f"{valeur:,.2f}".replace(",", " ").replace(".", ",") + " €"


def lignes_de_l_affaire(listing, mode: str = "collection",
                        budget: Optional[dict] = None) -> List[Tuple[str, str]]:
    """Les lignes (intitule, valeur) d'une alerte, dans l'ordre de lecture.
    `budget` : la carte est dans « Ma liste » et l'annonce tombe dans le budget."""
    detail = listing.price_detail or {}
    lignes = []
    if budget and budget.get("prix_max") is not None:
        lignes.append(("★ Ma liste", f"dans ton budget de {euros(budget['prix_max'])}"))

    prix = euros(listing.price)
    if listing.purchase_cost_eur is not None and abs(listing.purchase_cost_eur - listing.price) >= 0.01:
        prix += f" (≈ {euros(listing.purchase_cost_eur)} payé, protection et port compris)"
    lignes.append(("Prix", prix))

    cote = euros(listing.reference_price)
    etat = detail.get("etat_retenu")
    if etat:
        cote += f", ramenée à {euros(etat['reference_ajustee'])} pour l'état {etat['etat']}"
    lignes.append(("Cote", cote))

    if mode == "revente":
        lignes.append(("Marge de revente estimée", euros(listing.margin_net)))
    elif listing.savings_eur is not None:
        if listing.savings_eur >= 0:
            part = f" ({listing.savings_ratio:.0%})" if listing.savings_ratio is not None else ""
            lignes.append(("Économie", f"{euros(listing.savings_eur)} sous la cote{part}"))
        else:
            lignes.append(("Économie", f"aucune : {euros(-listing.savings_eur)} au-dessus de la cote"))

    if detail.get("alerte"):
        lignes.append(("⚠ Attention", detail["alerte"]))
    source = listing.source.value if hasattr(listing.source, "value") else listing.source
    lignes.append(("Source", str(source)))
    return lignes
