"""
Calcul de la marge potentielle d'une annonce.

Toute la logique ici est volontairement pure (pas d'I/O, pas de dépendance
au framework web ni à la DB) pour rester facilement testable unitairement
et pour que les hypothèses de frais soient explicites et ajustables.

Hypothèses par défaut (à ajuster selon la réalité du marché / tes propres
frais réels) :
- Cardmarket : pas de commission vendeur pour un particulier au moment de
  la rédaction (à revérifier périodiquement, les CGU/tarifs peuvent changer).
- eBay : frais de vente finale ~13% (catégorie cartes à collectionner) +
  frais de encaissement/paiement ~1.5%.
- Vinted : pas de commission vendeur (le "frais de protection acheteur"
  est payé par l'acheteur, pas déduit du prix perçu par le vendeur).
- Un coût de réexpédition forfaitaire est ajouté (enveloppe rigide,
  suivi, etc.) car il n'est presque jamais inclus dans l'annonce.

Ces constantes sont regroupées dans FeeConfig pour pouvoir être surchargées
depuis les settings de l'app (variables d'env / table `settings` en DB)
sans toucher au code.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FeeConfig:
    # Frais du canal sur lequel on imagine revendre la carte (pourcentage du
    # prix de référence obtenu à la revente), indexés par nom de canal.
    seller_fee_ratio: dict = field(default_factory=lambda: {
        "cardmarket": 0.0,
        "ebay": 0.13,
        "vinted": 0.0,
    })
    # Frais de paiement/encaissement, appliqués en plus du seller_fee_ratio.
    payment_fee_ratio: float = 0.015
    # Coût forfaitaire de réexpédition (emballage + affranchissement) en euros.
    reshipping_cost_eur: float = 2.5
    # Marge de sécurité additionnelle sur le prix de référence, pour tenir
    # compte du fait qu'une carte ne se revend pas toujours instantanément
    # au prix affiché (on décote le prix de référence de X% par prudence).
    reference_price_haircut: float = 0.10


@dataclass
class MarginResult:
    listing_total_cost: float          # prix annonce + port payé à l'achat
    reference_price_used: float        # prix de référence après décote
    resale_fees: float                 # frais estimés à la revente
    reshipping_cost: float
    net_resale_value: float            # ce qu'on toucherait net à la revente
    net_margin: float                  # net_resale_value - listing_total_cost
    margin_ratio: float                # net_margin / listing_total_cost (peut être négatif)

    def to_dict(self) -> dict:
        return {
            "listing_total_cost": round(self.listing_total_cost, 2),
            "reference_price_used": round(self.reference_price_used, 2),
            "resale_fees": round(self.resale_fees, 2),
            "reshipping_cost": round(self.reshipping_cost, 2),
            "net_resale_value": round(self.net_resale_value, 2),
            "net_margin": round(self.net_margin, 2),
            "margin_ratio": round(self.margin_ratio, 4),
        }


def calculate_margin(
    listing_price: float,
    listing_shipping: float,
    reference_price: float,
    resale_channel: str = "cardmarket",
    fee_config: Optional[FeeConfig] = None,
) -> MarginResult:
    """
    Calcule la marge nette estimée pour une annonce donnée.

    :param listing_price: prix affiché de l'annonce (hors port)
    :param listing_shipping: frais de port de l'annonce (0 si inclus/gratuit)
    :param reference_price: prix de marché de référence (Cardmarket, etc.)
    :param resale_channel: canal envisagé pour la revente ("cardmarket",
        "ebay" ou "vinted"), détermine les frais appliqués
    :param fee_config: configuration de frais à utiliser (défaut si omis)
    """
    if listing_price < 0 or listing_shipping < 0 or reference_price < 0:
        raise ValueError("Les prix ne peuvent pas être négatifs")

    cfg = fee_config or FeeConfig()

    listing_total_cost = listing_price + listing_shipping

    reference_price_used = reference_price * (1 - cfg.reference_price_haircut)

    fee_ratio = cfg.seller_fee_ratio.get(resale_channel, 0.0) + cfg.payment_fee_ratio
    resale_fees = reference_price_used * fee_ratio

    reshipping_cost = cfg.reshipping_cost_eur

    net_resale_value = reference_price_used - resale_fees - reshipping_cost

    net_margin = net_resale_value - listing_total_cost

    margin_ratio = (
        net_margin / listing_total_cost if listing_total_cost > 0 else 0.0
    )

    return MarginResult(
        listing_total_cost=listing_total_cost,
        reference_price_used=reference_price_used,
        resale_fees=resale_fees,
        reshipping_cost=reshipping_cost,
        net_resale_value=net_resale_value,
        net_margin=net_margin,
        margin_ratio=margin_ratio,
    )


def normalize_margin_ratio(margin_ratio: float, cap_ratio: float = 1.0) -> float:
    """
    Convertit un margin_ratio (peut être négatif, ou théoriquement > 1) en
    un score 0-100 utilisable dans le score de "bonne affaire".

    - margin_ratio <= 0  -> 0
    - margin_ratio >= cap_ratio (défaut 100% de marge) -> 100
    - linéaire entre les deux
    """
    if cap_ratio <= 0:
        raise ValueError("cap_ratio doit être positif")
    clipped = max(0.0, min(margin_ratio, cap_ratio))
    return (clipped / cap_ratio) * 100.0


# ---------------------------------------------------------------------------
# CE QUE COUTE VRAIMENT UN ACHAT
# ---------------------------------------------------------------------------
# Le cout d'achat retenu etait « prix + port », avec un port a zero pour
# Vinted, qui ne l'affiche pas sur l'annonce. Or l'acheteur paie aussi la
# PROTECTION ACHETEUR — le commentaire en tete de ce module ne l'evoquait que
# pour la revente sur Vinted, alors que l'application fait ACHETER sur
# Vinted. Sur une carte a 5,75 EUR, le cout reel avoisine 9,75 EUR : toutes
# les marges etaient gonflees d'autant, et sur les petites cartes, la moitie
# des « bonnes affaires » n'en etaient pas.
#
# La formule de la protection est verifiee sur une donnee reelle de la page
# catalogue Vinted, qui affiche les deux prix (voir collectors/vinted_scraper) :
#     « …, 2.99 €, 3.84 € »   ->   2,99 x 1,05 + 0,70 = 3,84
# Quand la page donne le prix protection comprise, c'est LUI qui est retenu ;
# la formule ne sert qu'a defaut.
VINTED_PROTECTION_FIXE = 0.70
VINTED_PROTECTION_TAUX = 0.05


def cout_d_achat(source: str, prix: float, port: Optional[float] = None,
                 prix_avec_protection: Optional[float] = None,
                 port_estime_vinted: float = 2.90) -> dict:
    """Le cout reel d'un achat, poste par poste.

    Le port Vinted se choisit au panier, pas sur l'annonce : quand il n'est
    pas connu, il est ESTIME, et le resultat le dit — un chiffre estime
    presente comme certain serait un mensonge de plus.
    """
    protection, origine = 0.0, None
    port_connu = port is not None and port > 0
    if source == "vinted":
        if prix_avec_protection is not None and prix_avec_protection >= prix:
            protection, origine = prix_avec_protection - prix, "relevee sur Vinted"
        else:
            protection = VINTED_PROTECTION_FIXE + VINTED_PROTECTION_TAUX * prix
            origine = "calculee (0,70 EUR + 5 %)"
        port_retenu = port if port_connu else port_estime_vinted
    else:
        port_retenu = port or 0.0
    return {
        "article": round(prix, 2),
        "protection": round(protection, 2),
        "origine_protection": origine,
        "port": round(port_retenu, 2),
        "port_estime": source == "vinted" and not port_connu,
        "total": round(prix + protection + port_retenu, 2),
    }


# ---------------------------------------------------------------------------
# L'ETAT DE LA CARTE AJUSTE SON PRIX DE REFERENCE
# ---------------------------------------------------------------------------
# Le prix de reference est celui d'une carte en tres bon etat. L'etat etait
# detecte puis ignore : une carte « etat moyen » etait comparee au prix d'une
# carte comme neuve, et sa marge gonflee d'un tiers. Les coefficients sont
# des ordres de grandeur de l'usage du marche a l'unite — reglables, et
# appliques seulement quand l'etat est connu : un etat inconnu ne decote pas,
# pour ne pas penaliser les vendeurs qui ne precisent rien.
DECOTE_PAR_ETAT = {"NM": 1.00, "LP": 0.85, "MP": 0.70, "HP": 0.50, "DMG": 0.30}
_ORDRE_DES_ETATS = ["NM", "LP", "MP", "HP", "DMG"]

# L'etat choisi par le vendeur dans le menu Vinted, ramene a l'echelle des
# cartes. « Tres bon etat » est le choix courant d'une carte sortie de
# booster : le ramener a LP decoterait presque toutes les annonces.
_ETAT_VINTED = {
    "neuf avec etiquette": "NM",
    "neuf sans etiquette": "NM",
    "tres bon etat": "NM",
    "bon etat": "LP",
    "satisfaisant": "MP",
}


def etat_vinted(libelle: Optional[str]) -> Optional[str]:
    """« Très bon état » -> « NM ». None si le libelle est inconnu."""
    import unicodedata

    if not libelle:
        return None
    texte = "".join(c for c in unicodedata.normalize("NFKD", libelle.lower())
                    if not unicodedata.combining(c)).strip()
    return _ETAT_VINTED.get(texte)


def etat_retenu(etat_du_texte: Optional[str], etat_declare: Optional[str]) -> Optional[str]:
    """Le PIRE des deux etats connus.

    Un vendeur qui coche « Très bon état » mais ecrit « etat moyen » dans son
    titre se contredit ; on retient le plus prudent, parce qu'une marge
    surestimee fait acheter, et qu'une marge sous-estimee ne fait que rater.
    """
    connus = [e for e in (etat_du_texte, etat_declare) if e in DECOTE_PAR_ETAT]
    if not connus:
        return None
    return max(connus, key=_ORDRE_DES_ETATS.index)
