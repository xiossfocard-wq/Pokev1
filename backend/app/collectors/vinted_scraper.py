"""
Scraper "respectueux" pour les annonces Vinted (pas d'API officielle).

Principes suivis (voir README > "Limites légales") :
- Aucune connexion à un compte Vinted : on ne lit que des pages publiques.
- Fréquence limitée et configurable (VINTED_REQUEST_DELAY_SECONDS), avec
  jitter aléatoire pour ne pas taper à intervalle parfaitement régulier.
- User-Agent honnête de navigateur standard (nécessaire pour obtenir une
  réponse correcte), mais AUCUNE impersonation de fingerprint TLS, AUCUNE
  rotation de proxy, AUCUN contournement d'anti-bot (Datadome). Si Vinted
  bloque (403/429), le scraper recule et alerte — il n'insiste pas.
- Un cooldown prolongé s'active automatiquement après plusieurs blocages
  consécutifs, pour ne pas s'acharner sur une IP qui semble flaggée.

Stratégie technique : les pages Vinted (catalogue + fiche article) sont
rendues côté serveur avec un état JSON embarqué dans le HTML (pattern
classique des apps Nuxt/Next). On essaie d'extraire ce JSON plutôt que de
parser le texte visible, ce qui est plus robuste... mais reste dépendant
de la structure réelle de la page au moment de l'exécution.

Vérification faite pendant le développement (août 2026, via un outil de
fetch web, PAS depuis ce conteneur qui n'a pas d'accès réseau sortant) :
- L'endpoint JSON interne "/api/v2/catalog/items" est bloqué d'emblée par
  la protection anti-bot (Datadome) même pour une requête ponctuelle et
  bien formée : on ne l'utilise donc PAS.
- Les pages HTML "humaines" du catalogue répondent normalement et
  affichent bien les annonces (prix, état, vendeur...). C'est donc cette
  famille d'URL "catalogue humain" qui est utilisée ci-dessous, combinée à
  `search_text` pour filtrer sur "carte pokemon".
- Le contenu exact du JSON embarqué (__NEXT_DATA__ / __NUXT__) n'a en
  revanche pas pu être inspecté brut avant le premier lancement réel, d'où
  la méthode diagnostic_fetch() ajoutée ci-dessous pour lever le doute
  directement en production sans avoir besoin de fouiller les logs.
- Les ID de catégorie/marque Vinted peuvent changer : à revérifier
  ponctuellement si le scraper cesse de remonter des résultats.
"""
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from app.core import robots_compliance

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Motifs de scripts susceptibles de contenir l'état JSON hydraté de la page.
_JSON_BLOB_PATTERNS = [
    re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL),
    re.compile(r'window\.__NUXT__\s*=\s*(\{.*?\});?\s*</script>', re.DOTALL),
    re.compile(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.DOTALL),
]

CONSECUTIVE_BLOCK_THRESHOLD = 3   # après ce nb de 403/429 d'affilée, on met en pause
COOLDOWN_SECONDS_AFTER_BLOCK = 30 * 60

# Catégorie Vinted FR "Cartes à collectionner à l'unité". Historique : une
# première valeur (1502) s'est révélée incorrecte lors du tout premier essai
# en production (03/08/2026). Reconfirmée le 04/08/2026 via plusieurs pages
# réelles trouvées par recherche web : la sous-catégorie "cartes à l'unité"
# (par opposition aux lots) est 4875. À revérifier si le scraper cesse à
# nouveau de remonter des résultats pertinents.
TRADING_CARDS_SINGLES_CATALOG_ID = 4875
POKEMON_BRAND_ID = 191646


@dataclass
class VintedListing:
    item_id: str
    title: str
    price: float
    currency: str
    url: str
    photo_urls: list = field(default_factory=list)
    description: str = ""
    seller_username: Optional[str] = None
    seller_review_count: Optional[int] = None
    seller_average_rating: Optional[float] = None
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "raw"}
        return d


class VintedBlockedError(Exception):
    """Levée quand Vinted bloque de façon répétée — le scheduler doit reculer."""


class VintedScraper:
    def __init__(
        self,
        base_url: str = "https://www.vinted.fr",
        request_delay_seconds: float = 8.0,
        jitter_seconds: float = 3.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.request_delay_seconds = request_delay_seconds
        self.jitter_seconds = jitter_seconds
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request_ts = 0.0
        self._consecutive_blocks = 0
        self._cooldown_until = 0.0

    def _wait_for_slot(self):
        now = time.time()
        if now < self._cooldown_until:
            wait = self._cooldown_until - now
            logger.info("Vinted: en cooldown, attente %.0fs supplémentaires", wait)
            time.sleep(wait)

        elapsed = time.time() - self._last_request_ts
        min_wait = self.request_delay_seconds + random.uniform(0, self.jitter_seconds)
        if elapsed < min_wait:
            time.sleep(min_wait - elapsed)

    def _get(self, path: str) -> Optional[requests.Response]:
        url = path if path.startswith("http") else f"{self.base_url}{path}"

        if not robots_compliance.is_allowed(url, session=self.session):
            logger.error(
                "Vinted: robots.txt interdit %s — requête annulée (voir "
                "app/core/robots_compliance.py). Ce n'est pas contournable "
                "depuis la config de ce scraper, par choix.", url,
            )
            return None

        self._wait_for_slot()

        try:
            resp = self.session.get(url, timeout=20)
        except requests.RequestException as exc:
            logger.warning("Vinted: erreur réseau sur %s (%s)", url, exc)
            self._last_request_ts = time.time()
            return None

        self._last_request_ts = time.time()

        if resp.status_code in (403, 429):
            self._consecutive_blocks += 1
            logger.warning(
                "Vinted: statut %s sur %s (blocages consécutifs: %d)",
                resp.status_code, url, self._consecutive_blocks,
            )
            if self._consecutive_blocks >= CONSECUTIVE_BLOCK_THRESHOLD:
                self._cooldown_until = time.time() + COOLDOWN_SECONDS_AFTER_BLOCK
                raise VintedBlockedError(
                    f"Bloqué {self._consecutive_blocks} fois de suite par Vinted "
                    f"(HTTP {resp.status_code}). Pause de "
                    f"{COOLDOWN_SECONDS_AFTER_BLOCK // 60} min. On ne tente PAS de "
                    f"contourner ce blocage (pas de proxy, pas de spoofing)."
                )
            return None

        self._consecutive_blocks = 0

        if resp.status_code != 200:
            logger.warning("Vinted: statut inattendu %s sur %s", resp.status_code, url)
            return None

        return resp

    @staticmethod
    def _extract_json_blob(html: str) -> Optional[dict]:
        for pattern in _JSON_BLOB_PATTERNS:
            match = pattern.search(html)
            if not match:
                continue
            raw = match.group(1).strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _walk_for_items(node) -> list:
        """
        Cherche récursivement une liste de dicts qui ressemble à des items
        Vinted (clés 'id', 'title', 'price' présentes) dans l'état JSON.
        Volontairement générique car la forme exacte de l'état hydraté n'a
        pas pu être confirmée hors-ligne.
        """
        found = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "items" and isinstance(value, list):
                    if all(isinstance(v, dict) and "id" in v for v in value[:1]):
                        found.extend(value)
                found.extend(VintedScraper._walk_for_items(value))
        elif isinstance(node, list):
            for value in node:
                found.extend(VintedScraper._walk_for_items(value))
        return found

    def diagnostic_fetch(self, search_text: str = "carte pokemon") -> dict:
        """
        v2 : cherche autour des liens /items/... plutot qu'un blob JSON
        hydrate, qui n'existe pas sur cette page (confirme en prod).
        """
        path = self._search_path(search_text)
        resp = self._get(path)
        if resp is None:
            return {
                "ok": False,
                "reason": "Requete bloquee ou echouee - voir logs Render.",
                "url_tentee": f"{self.base_url}{path}",
            }

        html = resp.text

        def sample_around(needle, before=150, after=900, occurrence=0):
            positions = [m.start() for m in re.finditer(re.escape(needle), html)]
            if len(positions) <= occurrence:
                return None
            idx = positions[occurrence]
            return html[max(0, idx - before): idx + after]

        items_positions = [m.start() for m in re.finditer(r'"/items/\d+', html)]

        return {
            "ok": True,
            "status_code": resp.status_code,
            "url_tentee": f"{self.base_url}{path}",
            "html_length": len(html),
            "contains___NEXT_DATA__": "__NEXT_DATA__" in html,
            "contains___NUXT__": "__NUXT__" in html,
            "script_tag_count": html.count("<script"),
            "application_json_script_count": html.count('type="application/json"'),
            "items_link_count": len(items_positions),
            "sample_around_first_items_link": sample_around('"/items/', occurrence=0),
            "sample_around_second_items_link": sample_around('"/items/', occurrence=1),
            "sample_around_first_euro_sign": sample_around("€", before=400, after=400),
        }

    def _search_path(self, search_text: str) -> str:
        return (
            f"/catalog/{TRADING_CARDS_SINGLES_CATALOG_ID}"
            f"?search_text={requests.utils.quote(search_text)}"
            f"&brand_ids[]={POKEMON_BRAND_ID}"
            "&order=newest_first"
        )

    def search_pokemon_listings(self, search_text: str = "carte pokemon", per_page: int = 48) -> list:
        """
        Récupère les annonces du catalogue de recherche Vinted pour les
        cartes Pokémon. Retourne une liste vide (avec log d'avertissement)
        si l'extraction JSON échoue plutôt que de faire planter le pipeline.
        """
        resp = self._get(self._search_path(search_text))
        if resp is None:
            return []

        blob = self._extract_json_blob(resp.text)
        if blob is None:
            logger.error(
                "Vinted: impossible d'extraire l'état JSON de la page de "
                "recherche — la structure de page a probablement changé. "
                "Ce module nécessite un ajustement avec un vrai échantillon "
                "de HTML récupéré en conditions réelles."
            )
            return []

        raw_items = self._walk_for_items(blob)[:per_page]
        listings = []
        for raw_item in raw_items:
            try:
                listings.append(self._parse_raw_item(raw_item))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Vinted: item ignoré (parsing échoué: %s)", exc)
        return listings

    @staticmethod
    def _parse_raw_item(raw: dict) -> VintedListing:
        price_field = raw.get("price", {})
        price_value = (
            price_field.get("amount") if isinstance(price_field, dict) else price_field
        )
        photo = raw.get("photo") or {}
        user = raw.get("user") or {}

        return VintedListing(
            item_id=str(raw.get("id")),
            title=raw.get("title", ""),
            price=float(price_value or 0),
            currency=(price_field.get("currency_code") if isinstance(price_field, dict) else "EUR") or "EUR",
            url=raw.get("url", ""),
            photo_urls=[photo.get("url")] if photo.get("url") else [],
            seller_username=user.get("login"),
            seller_review_count=user.get("feedback_count"),
            seller_average_rating=user.get("feedback_reputation"),
            raw=raw,
        )

    def fetch_item_detail(self, item_url: str) -> Optional[VintedListing]:
        """
        Récupère la fiche détaillée d'une annonce (description complète,
        toutes les photos) pour l'analyse qualité. Appelé seulement pour
        les annonces déjà jugées intéressantes après le scan de catalogue,
        pas pour chaque item du catalogue, afin de limiter le volume de
        requêtes.
        """
        resp = self._get(item_url)
        if resp is None:
            return None
        blob = self._extract_json_blob(resp.text)
        if blob is None:
            logger.warning("Vinted: état JSON introuvable sur la fiche %s", item_url)
            return None
        items = self._walk_for_items(blob)
        if not items:
            return None
        return self._parse_raw_item(items[0])
