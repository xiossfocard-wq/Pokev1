"""
Vérification du robots.txt, partagée par tous les collecteurs qui accèdent
à des pages publiques sans API officielle (Vinted, Cardmarket, ZebraDex).

Pourquoi ce module existe : en développant le scraper ZebraDex, une
vérification (via un outil de fetch web, pas depuis ce conteneur qui n'a
pas d'accès réseau sortant) a montré que zebradex.fr publie un robots.txt
qui bloque explicitement certains chemins pour les robots. C'est le signal
le plus clair et le plus objectif qu'un site puisse donner sur ce qu'il
autorise ou non pour un accès automatisé — bien plus fiable que "ça
répond 200 donc c'est permis". On applique donc désormais cette
vérification de façon systématique et automatique, AVANT chaque requête,
sur les trois sources sans API (Vinted, Cardmarket, ZebraDex) : si
robots.txt interdit un chemin, on ne le requête pas, point final — ce
n'est pas quelque chose à contourner.

Le fichier robots.txt est mis en cache par host pendant `CACHE_TTL_SECONDS`
pour ne pas le retélécharger à chaque annonce traitée.
"""
import logging
import time
import urllib.robotparser
from typing import Dict, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 6 * 3600  # 6h : robots.txt change rarement

DEFAULT_USER_AGENT = "PokemonDealHunter/1.0 (+usage personnel non-commercial)"


class _RobotsCacheEntry:
    def __init__(self, parser: Optional[urllib.robotparser.RobotFileParser], fetched_at: float):
        self.parser = parser
        self.fetched_at = fetched_at


_cache: Dict[str, _RobotsCacheEntry] = {}


def _fetch_robots_txt(base_url: str, session: Optional[requests.Session] = None) -> Optional[str]:
    robots_url = base_url.rstrip("/") + "/robots.txt"
    http = session or requests
    try:
        resp = http.get(robots_url, timeout=10)
    except requests.RequestException as exc:
        logger.warning("robots.txt: échec réseau sur %s (%s) — accès bloqué par prudence", robots_url, exc)
        return None
    if resp.status_code == 404:
        # Absence de robots.txt = pas de restriction déclarée (comportement
        # standard du protocole d'exclusion des robots).
        return ""
    if resp.status_code != 200:
        logger.warning(
            "robots.txt: statut %s sur %s — accès bloqué par prudence en attendant de comprendre",
            resp.status_code, robots_url,
        )
        return None
    return resp.text


def is_allowed(
    url: str,
    user_agent: str = DEFAULT_USER_AGENT,
    session: Optional[requests.Session] = None,
) -> bool:
    """
    True si robots.txt autorise `user_agent` à accéder à `url` (ou si
    robots.txt est absent/invalide — dans ce dernier cas on log et on
    refuse par prudence plutôt que de supposer une autorisation).
    """
    parsed = urlparse(url)
    host_key = f"{parsed.scheme}://{parsed.netloc}"

    cached = _cache.get(host_key)
    if cached is None or time.time() - cached.fetched_at > CACHE_TTL_SECONDS:
        raw = _fetch_robots_txt(host_key, session=session)
        parser: Optional[urllib.robotparser.RobotFileParser] = None
        if raw is not None:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(raw.splitlines())
        cached = _RobotsCacheEntry(parser=parser, fetched_at=time.time())
        _cache[host_key] = cached

    if cached.parser is None:
        # robots.txt inaccessible (erreur réseau/serveur) : on refuse par
        # prudence plutôt que de foncer en supposant que c'est autorisé.
        return False

    allowed = cached.parser.can_fetch(user_agent, url)
    if not allowed:
        logger.warning("robots.txt: accès à %s interdit pour '%s' — requête annulée", url, user_agent)
    return allowed


def reset_cache_for_tests():
    _cache.clear()
