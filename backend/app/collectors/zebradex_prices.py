"""
Collecteur de prix de référence ZebraDex (zebradex.fr) — source PRINCIPALE
de prix pour ce projet.

Pourquoi ZebraDex plutôt que Cardmarket : l'URL produit Cardmarket exige de
connaître l'extension exacte de la carte (impossible à deviner de façon
fiable depuis un titre d'annonce Vinted), alors que ZebraDex expose des
pages "série" listant TOUTES les cartes d'un set avec leur prix — ce qui
permet de construire un index complet, puis de faire le matching en local
sans requête par carte.

Vérifications faites le 04/08/2026 sur de VRAIES pages (pas des suppositions) :
- https://zebradex.fr/series liste 169 séries FR, de "Set de Base" (1999)
  à "Nuit Noire" (ME05), chacune avec une URL de la forme
  /fr/tcg/pokemon/{bloc}/{code}/{slug-serie}/{id}
- Une page série (ex Destinees de Paldea) liste ses 245 items, chacun avec :
  code carte (ex "PAF 232"), nom ("Mew ex"), prix ("419,31 EUR"), variation
  7 jours ("+9EUR"), et RARETE OFFICIELLE ("Special Illustration Rare").
  La rarete vient donc de la source, pas d'une devinette sur le titre.
- Chaque carte a un lien de fiche detaillee de la forme
  .../{code-slug}/{nom-slug}/{item-id}

Strategie de parsing (lecon tiree du scraper Vinted) : le HTML brut n'a pas
pu etre inspecte depuis l'environnement de dev, seulement sa version texte.
On implemente donc DEUX strategies complementaires, essayees dans l'ordre :
1. `_parse_by_links` : s'appuie sur les href des fiches carte (structure la
   plus stable en HTML brut), puis cherche le prix dans une fenetre autour.
2. `_parse_by_text` : s'appuie sur les lignes de texte aplati
   "CODE Nom prix EUR variation quantite : N Rarete" (filet de secours).
Si les deux echouent, `diagnostic_fetch()` (expose via
GET /api/admin/debug-zebradex) permet de recuperer un echantillon reel
pour ajuster sans deviner.
"""
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

import requests

from app.core import robots_compliance

logger = logging.getLogger(__name__)

BASE_URL = "https://zebradex.fr"
SERIES_INDEX_URL = f"{BASE_URL}/series"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

MIN_DELAY_SECONDS = 6.0  # respectueux : 1 requete / 6s max

_SERIES_LINK_PATTERN = re.compile(
    r'href="(?:https://zebradex\.fr)?(/fr/tcg/pokemon/([a-z0-9-]+)/([a-z0-9.-]+)/([a-z0-9-]+)/(\d+))"',
    re.IGNORECASE,
)

_CARD_LINK_PATTERN = re.compile(
    r'href="(?:https://zebradex\.fr)?/fr/tcg/pokemon/[a-z0-9-]+/[a-z0-9.-]+/[a-z0-9-]+/'
    r'([a-z0-9-]+)/([a-z0-9-]+)/(\d+)"',
    re.IGNORECASE,
)

# Lookbehind (?<![+-]) : sinon la variation "+4,66EUR" serait prise pour un
# prix (bug detecte en testant sur de vraies donnees ZebraDex le 04/08/2026).
_PRICE_PATTERN = re.compile(r"(?<![+-])(\d{1,3}(?:[\s\u202f]?\d{3})*,\d{2})\s*\u20ac")
_VARIATION_PATTERN = re.compile(r"([+-]\d+(?:,\d+)?)\s*\u20ac")

KNOWN_RARITIES = [
    "Special Illustration Rare", "Secret Illustration Rare", "Hyper Rare",
    "Illustration Rare", "Shiny Ultra Rare", "Shiny Rare", "Ultra Rare",
    "Double Rare", "Rare Holo", "Rare", "Uncommon", "Common",
]
_RARITY_PATTERN = re.compile("(" + "|".join(re.escape(r) for r in KNOWN_RARITIES) + ")")

_TEXT_CARD_PATTERN = re.compile(
    r"([A-Z]{2,6}[\s-]?\d{1,4}[A-Za-z]?)\s+"
    r"([^\n]{1,60}?)\s+"
    r"(\d{1,3}(?:[\s\u202f]?\d{3})*,\d{2})\s*\u20ac"
    r"[^\n]{0,20}?"
    r"quantit\u00e9\s*:\s*\d+\s*"
    r"(" + "|".join(re.escape(r) for r in KNOWN_RARITIES) + r")?"
)


def slugify_name(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-")
    return normalized.lower()


@dataclass
class ZebraDexSeries:
    name: str
    code: str
    bloc: str
    url: str
    series_id: str


@dataclass
class ZebraDexCardPrice:
    card_code: str
    name: str
    name_slug: str
    price_eur: float
    variation_7d_eur: Optional[float] = None
    rarity: Optional[str] = None
    series_name: Optional[str] = None

    @property
    def price_low(self) -> float:
        """
        Borne basse indicative. ZebraDex publie un prix marche et sa
        variation sur 7 jours, PAS une fourchette min/max des ventes
        conclues. On derive donc une fourchette a partir de l'amplitude
        observee sur 7 jours (a defaut, +/-8% par convention) : c'est une
        estimation de volatilite recente, pas un historique reel de
        transactions. A presenter comme tel dans l'UI.
        """
        spread = abs(self.variation_7d_eur) if self.variation_7d_eur else self.price_eur * 0.08
        return max(0.0, self.price_eur - spread)

    @property
    def price_high(self) -> float:
        spread = abs(self.variation_7d_eur) if self.variation_7d_eur else self.price_eur * 0.08
        return self.price_eur + spread


class ZebraDexClient:
    def __init__(self, session: Optional[requests.Session] = None, min_delay: float = MIN_DELAY_SECONDS):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.min_delay = min_delay
        self._last_request_ts = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

    def _get(self, url: str) -> Optional[str]:
        if not robots_compliance.is_allowed(url, session=self.session):
            logger.error("ZebraDex: robots.txt interdit %s - requete annulee", url)
            return None
        self._throttle()
        try:
            resp = self.session.get(url, timeout=30)
            self._last_request_ts = time.time()
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("ZebraDex: echec sur %s (%s)", url, exc)
            return None
        return resp.text

    def discover_series(self) -> List[ZebraDexSeries]:
        """
        Recupere la liste COMPLETE des series depuis /series (169 series FR
        au 04/08/2026). Aucune configuration manuelle : si ZebraDex ajoute
        une serie, elle est decouverte au prochain rafraichissement.
        """
        html = self._get(SERIES_INDEX_URL)
        if html is None:
            return []
        series = self.parse_series_index(html)
        if not series:
            logger.error(
                "ZebraDex: aucune serie extraite de %s - structure changee ? "
                "Verifier via /api/admin/debug-zebradex.", SERIES_INDEX_URL
            )
        return series

    @staticmethod
    def parse_series_index(html: str) -> List[ZebraDexSeries]:
        seen = set()
        out: List[ZebraDexSeries] = []
        for match in _SERIES_LINK_PATTERN.finditer(html):
            path, bloc, code, slug, series_id = match.groups()
            if series_id in seen:
                continue
            # Les "produits scelles" ne sont pas des cartes a l'unite.
            if "produits-scelles" in slug or slug.endswith("sld"):
                continue
            seen.add(series_id)
            out.append(ZebraDexSeries(
                name=slug.replace("-", " ").title(),
                code=code.upper(),
                bloc=bloc.replace("-", " ").title(),
                url=f"{BASE_URL}{path}",
                series_id=series_id,
            ))
        return out

    def fetch_series_cards(self, series_url: str, series_name: str = "") -> List[ZebraDexCardPrice]:
        html = self._get(series_url)
        if html is None:
            return []
        cards = self.parse_series_page(html, series_name=series_name)
        if not cards:
            logger.warning(
                "ZebraDex: 0 carte extraite de %s - structure changee ? "
                "Verifier via /api/admin/debug-zebradex.", series_url
            )
        return cards

    @classmethod
    def parse_series_page(cls, html: str, series_name: str = "") -> List[ZebraDexCardPrice]:
        cards = cls._parse_by_links(html, series_name)
        if cards:
            return cards
        return cls._parse_by_text(html, series_name)

    @staticmethod
    def _nearest_match(pattern, window: str, anchor: int):
        """
        Retourne la correspondance la PLUS PROCHE de `anchor` dans `window`,
        pas la premiere. Correction d'un bug detecte en testant sur de
        vraies donnees ZebraDex (04/08/2026) : la fenetre autour d'un lien
        carte deborde sur la carte precedente, donc `search()` renvoyait le
        prix de la carte d'avant (PAF 234 heritait du prix de PAF 232).
        """
        best = None
        best_distance = None
        for m in pattern.finditer(window):
            distance = min(abs(m.start() - anchor), abs(m.end() - anchor))
            if best_distance is None or distance < best_distance:
                best, best_distance = m, distance
        return best

    @classmethod
    def _parse_by_links(cls, html: str, series_name: str = "") -> List[ZebraDexCardPrice]:
        out: List[ZebraDexCardPrice] = []
        seen = set()
        for match in _CARD_LINK_PATTERN.finditer(html):
            code_slug, name_slug, item_id = match.groups()
            if item_id in seen:
                continue
            seen.add(item_id)

            start = max(0, match.start() - 600)
            window = html[start: match.end() + 600]
            anchor = match.start() - start  # position du lien dans la fenetre

            price_match = cls._nearest_match(_PRICE_PATTERN, window, anchor)
            if not price_match:
                continue
            price = cls._to_float(price_match.group(1))
            if price is None:
                continue

            variation = None
            var_match = cls._nearest_match(_VARIATION_PATTERN, window, anchor)
            if var_match:
                variation = cls._to_float(var_match.group(1))

            # La rarete n'apparait que dans la ligne recapitulative situee
            # APRES le lien : chercher avant ferait heriter de la rarete de
            # la carte precedente (bug detecte sur donnees reelles).
            rarity_match = _RARITY_PATTERN.search(window, anchor)

            out.append(ZebraDexCardPrice(
                card_code=code_slug.replace("-", " ").upper(),
                name=name_slug.replace("-", " ").title(),
                name_slug=name_slug,
                price_eur=price,
                variation_7d_eur=variation,
                rarity=rarity_match.group(1) if rarity_match else None,
                series_name=series_name or None,
            ))
        return out

    @classmethod
    def _parse_by_text(cls, html: str, series_name: str = "") -> List[ZebraDexCardPrice]:
        out: List[ZebraDexCardPrice] = []
        seen = set()
        for match in _TEXT_CARD_PATTERN.finditer(html):
            code, name, raw_price, rarity = match.groups()
            code = re.sub(r"\s+", " ", code).strip().upper()
            name = name.strip()
            if not name or code in seen:
                continue
            price = cls._to_float(raw_price)
            if price is None:
                continue
            seen.add(code)
            out.append(ZebraDexCardPrice(
                card_code=code,
                name=name,
                name_slug=slugify_name(name),
                price_eur=price,
                rarity=rarity,
                series_name=series_name or None,
            ))
        return out

    @staticmethod
    def _to_float(raw: str) -> Optional[float]:
        cleaned = raw.replace("\u202f", "").replace(" ", "").replace("\xa0", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def diagnostic_fetch(self, series_url: Optional[str] = None) -> dict:
        url = series_url or SERIES_INDEX_URL
        html = self._get(url)
        if html is None:
            return {"ok": False, "url": url, "reason": "requete bloquee/echouee - voir logs"}

        by_links = self._parse_by_links(html)
        by_text = self._parse_by_text(html)
        idx = html.find("\u20ac")
        return {
            "ok": True,
            "url": url,
            "html_length": len(html),
            "series_links_found": len(self.parse_series_index(html)),
            "cards_found_by_links": len(by_links),
            "cards_found_by_text": len(by_text),
            "first_card_by_links": by_links[0].__dict__ if by_links else None,
            "first_card_by_text": by_text[0].__dict__ if by_text else None,
            "sample_around_first_euro": html[max(0, idx - 500): idx + 500] if idx != -1 else None,
        }
