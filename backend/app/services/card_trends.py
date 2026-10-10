"""
Tendances de prix et projection, a partir de deux sources de nature tres
differente. La distinction est le coeur de ce module.

1. LA VARIATION 7 JOURS, publiee par ZebraDex et deja collectee pour chaque
   carte (`MarketCardPrice.variation_7d_eur`). C'est une vraie donnee de
   marche, disponible immediatement, et c'est ce qui permet de repondir des
   maintenant a « quelles cartes sont en vogue ».

2. L'HISTORIQUE QU'ON CONSTITUE NOUS-MEMES (`CardPriceSnapshot`, un releve
   par carte et par jour). Il part vide : le jour ou cette fonctionnalite
   est deployee, il n'y a rien dedans, et il se remplit au rythme d'un
   point par jour.

Pourquoi cette separation est importante
----------------------------------------
Une « prediction de marche » calculee sur un seul releve n'est pas une
prediction, c'est une invention. Tant que l'historique est court, ce module
le DIT au lieu de sortir un chiffre rassurant : `fiabilite` vaut
"insuffisant" et aucune projection n'est rendue. Il faut au minimum
MIN_POINTS releves etales sur MIN_JOURS jours pour qu'une droite soit
ajustee.

Et meme alors, ce qui est rendu est une EXTRAPOLATION LINEAIRE, pas une
prevision : elle prolonge la pente recente en supposant que rien ne change.
Sur des cartes a collectionner, ou une reimpression, une annonce de tournoi
ou une video virale peuvent tout retourner en une semaine, cette hypothese
est fragile. Le `r2` dit a quel point les points passes s'alignent
reellement sur cette droite, et `avertissement` porte cette reserve jusqu'a
l'interface. A presenter comme une tendance prolongee, jamais comme une
valeur future.
"""
import math
from dataclasses import dataclass, asdict
from datetime import date
from typing import List, Optional, Sequence, Tuple

# Seuils en deca desquels on refuse de tracer une droite.
MIN_POINTS = 5
MIN_JOURS = 7

# Bornes de ce qu'on appelle "stable" : en dessous, le bruit domine.
SEUIL_STABLE_PCT = 2.0
# Au-dela, la carte est signalee comme forte hausse / forte baisse.
SEUIL_FORT_PCT = 10.0


# --- tendance immediate (variation 7 jours ZebraDex) ---------------------


@dataclass
class Tendance7Jours:
    variation_eur: Optional[float]
    variation_pct: Optional[float]
    direction: str          # "hausse" | "baisse" | "stable" | "inconnu"
    intensite: str          # "forte" | "moderee" | "faible" | "inconnu"
    label: str

    def to_dict(self) -> dict:
        return asdict(self)


def tendance_7_jours(price_eur: Optional[float],
                     variation_7d_eur: Optional[float]) -> Tendance7Jours:
    """Classe la variation 7 jours publiee par la source.

    Le pourcentage est rapporte au prix d'il y a 7 jours (prix actuel moins
    la variation), pas au prix actuel : une carte passee de 10 a 20 EUR a
    pris 100 %, pas 50 %.
    """
    if price_eur is None or variation_7d_eur is None:
        return Tendance7Jours(
            variation_eur=None, variation_pct=None,
            direction="inconnu", intensite="inconnu",
            label="Variation inconnue",
        )

    prix_avant = price_eur - variation_7d_eur
    if prix_avant <= 0:
        # Cas degenere (variation superieure au prix) : le pourcentage
        # n'aurait aucun sens, on garde la valeur en euros.
        return Tendance7Jours(
            variation_eur=round(variation_7d_eur, 2), variation_pct=None,
            direction="hausse" if variation_7d_eur > 0 else "baisse",
            intensite="inconnu",
            label=f"{variation_7d_eur:+.2f} EUR sur 7 jours",
        )

    pct = (variation_7d_eur / prix_avant) * 100.0

    if abs(pct) < SEUIL_STABLE_PCT:
        direction, intensite = "stable", "faible"
    else:
        direction = "hausse" if pct > 0 else "baisse"
        intensite = "forte" if abs(pct) >= SEUIL_FORT_PCT else "moderee"

    if direction == "stable":
        label = "Stable sur 7 jours"
    else:
        label = f"{pct:+.1f} % sur 7 jours"

    return Tendance7Jours(
        variation_eur=round(variation_7d_eur, 2),
        variation_pct=round(pct, 2),
        direction=direction,
        intensite=intensite,
        label=label,
    )


# --- tendance de fond (historique constitue) -----------------------------


@dataclass
class TendanceHistorique:
    points: int
    jours_couverts: int
    variation_pct: Optional[float]
    pente_eur_par_jour: Optional[float]
    r2: Optional[float]
    fiabilite: str            # "insuffisant" | "faible" | "moyenne" | "bonne"
    avertissement: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Projection:
    horizon_jours: int
    prix_projete_eur: Optional[float]
    fiabilite: str
    avertissement: str

    def to_dict(self) -> dict:
        return asdict(self)


def _regression_lineaire(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float, float]:
    """Moindres carres a la main : pente, ordonnee a l'origine, r2.

    Ecrit ici plutot qu'avec numpy pour ne pas ajouter une dependance de
    plusieurs dizaines de Mo a un backend qui tourne sur un plan gratuit,
    alors que le calcul tient en quinze lignes.
    """
    n = len(xs)
    moyenne_x = sum(xs) / n
    moyenne_y = sum(ys) / n

    variance_x = sum((x - moyenne_x) ** 2 for x in xs)
    if variance_x == 0:
        # Tous les releves le meme jour : aucune pente calculable.
        return 0.0, moyenne_y, 0.0

    covariance = sum((x - moyenne_x) * (y - moyenne_y) for x, y in zip(xs, ys))
    pente = covariance / variance_x
    origine = moyenne_y - pente * moyenne_x

    variance_y = sum((y - moyenne_y) ** 2 for y in ys)
    if variance_y == 0:
        # Prix parfaitement constant : la droite est exacte (pente nulle).
        return pente, origine, 1.0

    residus = sum((y - (pente * x + origine)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - (residus / variance_y)
    return pente, origine, max(0.0, min(1.0, r2))


def _fiabilite(points: int, jours: int, r2: float) -> str:
    if points < MIN_POINTS or jours < MIN_JOURS:
        return "insuffisant"
    if points >= 20 and jours >= 30 and r2 >= 0.6:
        return "bonne"
    if points >= 10 and jours >= 14 and r2 >= 0.3:
        return "moyenne"
    return "faible"


_AVERTISSEMENT_INSUFFISANT = (
    "Historique trop court pour degager une tendance de fond : il faut au "
    f"moins {MIN_POINTS} releves etales sur {MIN_JOURS} jours. L'historique "
    "se constitue a raison d'un releve par jour, il n'existe donc pas "
    "retroactivement."
)

_AVERTISSEMENT_EXTRAPOLATION = (
    "Prolongement de la pente recente, pas une prevision : suppose que rien "
    "ne change. Une reimpression, un resultat de tournoi ou une video virale "
    "peuvent inverser la tendance en quelques jours."
)


def tendance_historique(releves: Sequence[Tuple[date, float]]) -> TendanceHistorique:
    """`releves` : liste de (jour, prix), dans n'importe quel ordre."""
    propres = sorted((j, p) for j, p in releves if j is not None and p is not None)

    if not propres:
        return TendanceHistorique(
            points=0, jours_couverts=0, variation_pct=None,
            pente_eur_par_jour=None, r2=None,
            fiabilite="insuffisant", avertissement=_AVERTISSEMENT_INSUFFISANT,
        )

    premier_jour = propres[0][0]
    jours_couverts = (propres[-1][0] - premier_jour).days

    if len(propres) < MIN_POINTS or jours_couverts < MIN_JOURS:
        return TendanceHistorique(
            points=len(propres), jours_couverts=jours_couverts,
            variation_pct=None, pente_eur_par_jour=None, r2=None,
            fiabilite="insuffisant", avertissement=_AVERTISSEMENT_INSUFFISANT,
        )

    xs = [float((j - premier_jour).days) for j, _ in propres]
    ys = [float(p) for _, p in propres]
    pente, _origine, r2 = _regression_lineaire(xs, ys)

    prix_depart, prix_arrivee = ys[0], ys[-1]
    variation_pct = ((prix_arrivee - prix_depart) / prix_depart * 100.0
                     if prix_depart > 0 else None)

    return TendanceHistorique(
        points=len(propres),
        jours_couverts=jours_couverts,
        variation_pct=round(variation_pct, 2) if variation_pct is not None else None,
        pente_eur_par_jour=round(pente, 4),
        r2=round(r2, 3),
        fiabilite=_fiabilite(len(propres), jours_couverts, r2),
        avertissement=_AVERTISSEMENT_EXTRAPOLATION,
    )


def projection(releves: Sequence[Tuple[date, float]], horizon_jours: int = 30) -> Projection:
    """Prolonge la pente recente a `horizon_jours`.

    Rend `prix_projete_eur = None` tant que l'historique est insuffisant :
    c'est le point entier de ce module. Un prix projete sur deux releves
    serait un chiffre invente, et un chiffre invente affiche a cote de vrais
    prix est pris pour un vrai prix.
    """
    fond = tendance_historique(releves)

    if fond.fiabilite == "insuffisant" or fond.pente_eur_par_jour is None:
        return Projection(
            horizon_jours=horizon_jours, prix_projete_eur=None,
            fiabilite="insuffisant", avertissement=_AVERTISSEMENT_INSUFFISANT,
        )

    propres = sorted((j, p) for j, p in releves if j is not None and p is not None)
    dernier_prix = propres[-1][1]
    projete = dernier_prix + fond.pente_eur_par_jour * horizon_jours

    # Un prix negatif n'existe pas : on plancher a zero plutot que d'afficher
    # une absurdite quand la pente est fortement descendante.
    projete = max(0.0, projete)

    return Projection(
        horizon_jours=horizon_jours,
        prix_projete_eur=round(projete, 2),
        fiabilite=fond.fiabilite,
        avertissement=_AVERTISSEMENT_EXTRAPOLATION,
    )
