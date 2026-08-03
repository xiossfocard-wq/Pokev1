"""
Récupération du prix de référence Cardmarket pour une carte Pokémon FR.

IMPORTANT — pourquoi on ne passe pas par l'API OAuth Cardmarket :
L'API classique de Cardmarket est contractuellement réservée à la gestion
de son propre inventaire ; utiliser les prix pour un autre usage (comme le
nôtre) nécessite un accord écrit préalable de Cardmarket, et l'usage à
d'autres fins est explicitement interdit dans leurs CGU. En revanche,
Cardmarket a rendu son "Price Guide" (guide des prix) librement consultable
par tout visiteur sur les pages produit publiques du site — c'est cette
donnée publique que nous utilisons ici, en respectant la même prudence que
pour Vinted (fréquence limitée, cache, pas de contournement d'anti-bot).

Deux stratégies possibles, la seconde étant nettement recommandée en usage
réel (plus rapide, moins de requêtes, un seul fichier/jour) :
1. (implémenté ici, `fetch_reference_price`) Lookup carte par carte sur la
   page produit publique, avec un cache DB pour ne réinterroger une carte
   qu'une fois par jour.
2. (implémenté ici aussi, `fetch_bulk_price_guide`, mais désactivé par
   défaut) Téléchargement du fichier "Price Guide" en masse depuis
   https://www.cardmarket.com/en/Pokemon/Data/Price-Guide — Cardmarket a
   rendu ce fichier téléchargeable pour tous les jeux/tous les visiteurs
   (l'ancienne API OAuth pour ces données a même été dépréciée en
   conséquence). C'est la voie à privilégier.

   ⚠️ Vérification faite pendant le développement (août 2026, via un outil
   de fetch web, PAS depuis ce conteneur qui n'a pas d'accès réseau
   sortant) : la page /en/Pokemon/Data (et /Price-Guide) renvoie un blocage
   anti-bot lors d'un fetch automatisé simple. L'URL exacte du fichier
   téléchargeable (probablement un lien direct type
   https://downloads.s3.cardmarket.com/... vers un CSV, non confirmé) n'a
   donc pas pu être récupérée depuis ici. Étape manuelle nécessaire avant
   d'activer cette voie : ouvre https://www.cardmarket.com/en/Pokemon/Data
   dans un vrai navigateur, accepte les cookies, clique-droit sur le lien
   de téléchargement du "Price Guide" Pokémon → "Copier l'adresse du lien"
   → colle cette URL dans `CARDMARKET_BULK_PRICE_GUIDE_URL` (.env). Une
   fois cette variable renseignée, `fetch_bulk_price_guide()` est
   utilisable ; sinon le pipeline continue d'utiliser le lookup carte par
   carte (stratégie 1) qui ne nécessite aucune config.

Ce module reste volontairement tolérant aux erreurs : si la page/le fichier
a changé de structure, on log un avertissement et on retourne None/vide
plutôt que de planter tout le pipeline (une annonce sans prix de référence
est simplement ignorée pour le calcul de marge, pas bloquante).
"""
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests

from app.core import robots_compliance
from app.matching.card_matcher import slugify_card_name as _slugify_card_name

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cardmarket.com/en/Pokemon/Products/Singles"

# Cardmarket demande d'être identifié par un User-Agent standard ; on ne
# cherche pas à se faire passer pour autre chose qu'un script normal.
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PokemonDealHunter/1.0; "
                  "+usage personnel non-commercial)",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

MIN_DELAY_SECONDS = 3.0  # volume naturellement faible (1x/carte/jour), mais on reste prudent


@dataclass
class CardmarketPrice:
    card_slug: str
    trend_price_eur: Optional[float]       # "Trend" : prix de référence Cardmarket
    avg_30d_price_eur: Optional[float]      # moyenne 30 jours si disponible
    fetched_at: float                       # epoch seconds

    def to_dict(self) -> dict:
        return {
            "card_slug": self.card_slug,
            "trend_price_eur": self.trend_price_eur,
            "avg_30d_price_eur": self.avg_30d_price_eur,
            "fetched_at": self.fetched_at,
        }


class CardmarketPriceClient:
    def __init__(self, session: Optional[requests.Session] = None, min_delay: float = MIN_DELAY_SECONDS):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.min_delay = min_delay
        self._last_request_ts: float = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

    def build_product_url(self, expansion_slug: str, card_slug: str) -> str:
        """
        ex: expansion_slug="Base-Set", card_slug="Charizard"
        -> https://www.cardmarket.com/en/Pokemon/Products/Singles/Base-Set/Charizard
        """
        return f"{BASE_URL}/{expansion_slug}/{card_slug}"

    def fetch_reference_price(self, expansion_slug: str, card_slug: str) -> Optional[CardmarketPrice]:
        """
        Récupère le prix de référence ("Trend") pour une carte donnée.
        Retourne None si la page est indisponible ou si le parsing échoue
        (structure de page modifiée) plutôt que de lever une exception —
        l'appelant doit pouvoir continuer le pipeline sans ce prix.
        """
        url = self.build_product_url(expansion_slug, card_slug)

        if not robots_compliance.is_allowed(url, session=self.session):
            logger.error("Cardmarket: robots.txt interdit %s — requête annulée", url)
            return None

        self._throttle()
        try:
            resp = self.session.get(url, timeout=15)
            self._last_request_ts = time.time()
        except requests.RequestException as exc:
            logger.warning("Cardmarket: échec réseau sur %s (%s)", url, exc)
            return None

        if resp.status_code == 404:
            logger.info("Cardmarket: carte introuvable %s", url)
            return None
        if resp.status_code != 200:
            logger.warning("Cardmarket: statut inattendu %s sur %s", resp.status_code, url)
            return None

        trend = self._extract_price(resp.text, label_hints=["Trend", "Price Trend"])
        avg_30d = self._extract_price(resp.text, label_hints=["30-days average", "30 days average"])

        if trend is None and avg_30d is None:
            logger.warning(
                "Cardmarket: aucun prix trouvé sur %s — la structure de la page "
                "a probablement changé, vérifier manuellement.", url
            )
            return None

        return CardmarketPrice(
            card_slug=card_slug,
            trend_price_eur=trend,
            avg_30d_price_eur=avg_30d,
            fetched_at=time.time(),
        )

    def fetch_bulk_price_guide(self, url: str) -> dict:
        """
        Télécharge et parse le fichier "Price Guide" Cardmarket (CSV) en
        masse. Retourne {card_slug: trend_price_eur}. Retourne un dict vide
        (avec log d'erreur) si le téléchargement échoue ou si le format ne
        correspond pas à ce qui est attendu — voir docstring du module pour
        comment obtenir `url`.

        Tolérant sur le nom des colonnes (Cardmarket documente son format
        CSV avec des variantes selon la langue/version) : on cherche une
        colonne nom de produit parmi plusieurs alias possibles, et une
        colonne prix parmi plusieurs alias possibles.
        """
        self._throttle()
        if not robots_compliance.is_allowed(url, session=self.session):
            logger.error("Cardmarket: robots.txt interdit %s — téléchargement annulé", url)
            return {}
        try:
            resp = self.session.get(url, timeout=60)
            self._last_request_ts = time.time()
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Cardmarket: échec du téléchargement du price guide (%s)", exc)
            return {}

        return self._parse_bulk_csv(resp.text)

    _NAME_COLUMN_ALIASES = ["Name", "Product Name", "productName", "name"]
    _PRICE_COLUMN_ALIASES = [
        "Trend", "Price Trend", "TREND", "trend", "Trend Price",
    ]

    @classmethod
    def _parse_bulk_csv(cls, csv_text: str) -> dict:
        import csv
        import io

        # Cardmarket utilise historiquement le point-virgule comme séparateur
        # pour ses exports CSV (convention européenne) ; on retombe sur la
        # virgule si le fichier obtenu en utilise une (détection légère).
        delimiter = ";" if csv_text.count(";") > csv_text.count(",") else ","
        reader = csv.DictReader(io.StringIO(csv_text), delimiter=delimiter)

        if not reader.fieldnames:
            logger.error("Cardmarket: fichier price guide vide ou illisible")
            return {}

        name_col = next((c for c in cls._NAME_COLUMN_ALIASES if c in reader.fieldnames), None)
        price_col = next((c for c in cls._PRICE_COLUMN_ALIASES if c in reader.fieldnames), None)

        if not name_col or not price_col:
            logger.error(
                "Cardmarket: colonnes attendues introuvables dans le price "
                "guide (colonnes présentes: %s) — format probablement changé.",
                reader.fieldnames,
            )
            return {}

        prices: dict = {}
        for row in reader:
            name = (row.get(name_col) or "").strip()
            raw_price = (row.get(price_col) or "").replace(",", ".").strip()
            if not name or not raw_price:
                continue
            try:
                prices[_slugify_card_name(name)] = float(raw_price)
            except ValueError:
                continue
        return prices

    @staticmethod
    def _extract_price(html: str, label_hints: list) -> Optional[float]:
        """
        Cherche un motif "<Label>...123,45 €" dans le HTML brut. Volontairement
        permissif (plusieurs variantes de formatage FR/EN) car on n'a pas pu
        vérifier la structure DOM exacte depuis cet environnement (page
        cookie-gated au moment de la conception). À ajuster avec un vrai
        échantillon de HTML si ça ne matche pas au premier lancement réel.
        """
        for label in label_hints:
            pattern = re.escape(label) + r".{0,120}?([\d]{1,4}(?:[.,]\d{1,2})?)\s*€"
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                raw = match.group(1).replace(",", ".")
                try:
                    return float(raw)
                except ValueError:
                    continue
        return None
