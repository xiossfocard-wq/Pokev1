"""
Prix de référence complémentaire via ZebraDex (zebradex.fr), une plateforme
FR de suivi de prix Pokémon TCG. Ajouté à la demande de l'utilisateur en
complément de Cardmarket, car ZebraDex :
- est spécifiquement centré sur le marché FR (contrairement à Cardmarket,
  paneuropéen) ;
- indique filtrer sur des vendeurs fiables et des ventes réellement
  conclues plutôt que sur de simples prix affichés — un signal a priori
  complémentaire et potentiellement plus proche de ce qu'on toucherait
  vraiment à la revente.

Pas d'API publique identifiée. Vérifications faites pendant le développement
(août 2026, via un outil de fetch web, PAS depuis ce conteneur qui n'a pas
d'accès réseau sortant) :
- La page /search est utilisable côté robots.txt (elle a répondu
  normalement lors de la vérification), MAIS ses résultats de recherche
  sont injectés en JavaScript après une recherche utilisateur — le HTML
  brut obtenu par une requête simple ne contient donc aucun prix
  exploitable. Elle n'est donc pas utilisée ici, pas pour une question de
  permission mais de faisabilité technique (il faudrait un navigateur
  piloté, ex Playwright, pour l'exécuter).
- En revanche, les pages "série" (une série Pokémon = un set, avec toutes
  ses cartes et leur prix sur une seule page, ex:
  https://zebradex.fr/fr/tcg/pokemon/ecarlate-et-violet/ev03-5/151/4)
  apparaissent avec leur contenu texte (prix inclus) dans des résultats de
  recherche classiques, ce qui indique fortement qu'elles sont rendues
  côté serveur (donc lisibles sans exécuter de JS). Ceci dit, seule la
  vérification `robots_compliance.is_allowed()` faite à l'exécution fait
  foi pour savoir si un chemin donné est autorisé — elle n'a pas pu être
  testée à l'avance sur une page série précise depuis cet environnement.

Limite assumée de cette v1 : contrairement à Cardmarket (URL de carte
prévisible à partir d'un nom de carte), ZebraDex utilise un ID numérique
interne dans ses URLs de carte/série qu'on ne peut pas deviner. On ne peut
donc PAS interroger ZebraDex "à la volée" pour une carte quelconque comme
avec Cardmarket. Approche retenue : tu configures dans `ZEBRADEX_SERIES_URLS`
(.env, séparées par des virgules) les URLs des séries qui t'intéressent
(celles des annonces que tu traques le plus) ; ce module télécharge chacune
1x/jour et en extrait un dict {card_slug: prix}, utilisé en complément du
prix Cardmarket dans le pipeline (voir pipeline.py > _get_or_fetch_reference_price).
Aucune configuration = ZebraDex simplement ignoré, Cardmarket reste seul
utilisé (comportement inchangé).

Comme pour les autres sources, le parsing reste tolérant : un changement de
structure de page fait retourner un dict vide (avec log d'avertissement)
plutôt que de planter le pipeline.
"""
import logging
import re
import time
from typing import Optional

import requests

from app.core import robots_compliance
from app.matching.card_matcher import slugify_card_name

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PokemonDealHunter/1.0; "
                  "+usage personnel non-commercial)",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

MIN_DELAY_SECONDS = 5.0

# Une "carte" dans le texte extrait d'une page série ressemble à :
# "PAF 234 Dracaufeu ex 228,60 € +13€ quantité : 0" (le code et le nom sont
# répétés une première fois plus tôt dans un bloc résumé — voir docstring du
# module — d'où le petit lookahead pour ne matcher que la bonne occurrence).
_CARD_PATTERN = re.compile(
    r"([A-Z]{2,6}[\s-]?\d{1,4}[A-Z]?)\s+"       # code carte, ex "PAF 232"
    r"([A-Za-zÀ-ÿ0-9' .-]+?)\s+"                 # nom carte, ex "Dracaufeu ex"
    r"(\d[\d.,]*)\s*€"                            # prix, ex "228,60 €"
    r"(?:[^q]{0,25})?"                            # petite variation avant "quantité"
    r"quantité\s*:\s*(\d+)",
    re.IGNORECASE,
)


class ZebraDexPriceClient:
    def __init__(self, session: Optional[requests.Session] = None, min_delay: float = MIN_DELAY_SECONDS):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.min_delay = min_delay
        self._last_request_ts = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

    def fetch_series_prices(self, series_url: str) -> dict:
        """
        Télécharge une page série ZebraDex et retourne {card_slug: prix_eur}
        pour toutes les cartes qui s'y trouvent. Dict vide (+ log) si la
        requête échoue, si robots.txt l'interdit, ou si le format ne
        correspond pas à ce qui est attendu.
        """
        if not robots_compliance.is_allowed(series_url, session=self.session):
            logger.error("ZebraDex: robots.txt interdit %s — requête annulée", series_url)
            return {}

        self._throttle()
        try:
            resp = self.session.get(series_url, timeout=20)
            self._last_request_ts = time.time()
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("ZebraDex: échec réseau sur %s (%s)", series_url, exc)
            return {}

        prices = self._parse_series_text(resp.text)
        if not prices:
            logger.warning(
                "ZebraDex: aucune carte extraite de %s — la structure de "
                "page a probablement changé, vérifier manuellement.",
                series_url,
            )
        return prices

    @classmethod
    def _parse_series_text(cls, text: str) -> dict:
        """
        Parsing volontairement basé sur le texte "aplati" de la page plutôt
        que sur des sélecteurs CSS précis (la structure DOM exacte n'a pas
        pu être inspectée hors-ligne, voir docstring du module) : plus
        tolérant aux petits changements de mise en page, au prix d'être
        moins précis. À la première exécution réelle, si `fetch_series_prices`
        ne remonte rien, m'envoyer un extrait de page suffit pour l'ajuster.
        """
        prices = {}
        for match in _CARD_PATTERN.finditer(text):
            _code, name, raw_price, _qty = match.groups()
            name = name.strip()
            if not name:
                continue
            try:
                price = float(raw_price.replace(",", "."))
            except ValueError:
                continue
            prices[slugify_card_name(name)] = price
        return prices
