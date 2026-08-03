"""
Client pour l'API officielle eBay Browse (annonces actives).

On n'utilise PAS la Marketplace Insights API (ventes conclues) : elle est
en "Limited Release" et eBay n'accepte actuellement plus de nouvelles
candidatures pour la production (cf. discussion avec l'utilisateur). Le
prix de référence principal est donc Cardmarket ; ce client sert uniquement
à détecter les annonces actives à comparer à ce prix de référence.

Catégorie utilisée : 183454 ("Individual Trading Card Games"), avec un
filtre de langue si l'aspect existe pour la catégorie (à vérifier une fois
les clés en main via la Taxonomy API : get_item_aspects_for_category).

Flux d'auth : OAuth2 client credentials (scope public, pas de user token
nécessaire pour la Browse API en lecture seule sur données publiques).
"""
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PRODUCTION_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
PRODUCTION_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SANDBOX_BROWSE_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"

DEFAULT_SCOPE = "https://api.ebay.com/oauth/api_scope"
POKEMON_TCG_CATEGORY_ID = "183454"  # "Individual Trading Card Games"


@dataclass
class EbayListing:
    item_id: str
    title: str
    price: float
    currency: str
    shipping_cost: Optional[float]
    item_web_url: str
    image_url: Optional[str]
    condition: Optional[str]
    seller_username: Optional[str]
    seller_feedback_percentage: Optional[float]
    seller_feedback_score: Optional[int]
    item_location_country: Optional[str]
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "raw"}
        return d


class EbayBrowseClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        marketplace_id: str = "EBAY_FR",
        use_sandbox: bool = False,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace_id = marketplace_id
        self.token_url = SANDBOX_TOKEN_URL if use_sandbox else PRODUCTION_TOKEN_URL
        self.browse_url = SANDBOX_BROWSE_URL if use_sandbox else PRODUCTION_BROWSE_URL
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        creds = f"{self.client_id}:{self.client_secret}"
        b64_creds = base64.b64encode(creds.encode()).decode()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {b64_creds}",
        }
        data = {"grant_type": "client_credentials", "scope": DEFAULT_SCOPE}

        resp = requests.post(self.token_url, headers=headers, data=data, timeout=15)
        resp.raise_for_status()
        payload = resp.json()

        self._access_token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 7200)
        return self._access_token

    def search_pokemon_listings(
        self,
        keywords: str = "pokemon carte",
        limit: int = 50,
        offset: int = 0,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sort_by_newest: bool = True,
    ) -> list:
        """
        Recherche des annonces actives de cartes Pokémon.

        NB: la Browse API ne propose pas de tri "date de mise en ligne"
        universel documenté de façon garantie sur tous les marketplaces ;
        on trie côté serveur si l'API le permet (newlyListed), sinon on
        déduplique côté appli via item_id déjà vus en base.
        """
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
            "Content-Type": "application/json",
        }

        filters = [f"categoryIds:{{{POKEMON_TCG_CATEGORY_ID}}}"]
        price_filter_parts = []
        if min_price is not None:
            price_filter_parts.append(f"price:[{min_price}..{max_price or ''}]")
            filters.append(f"priceCurrency:EUR")

        params = {
            "q": keywords,
            "category_ids": POKEMON_TCG_CATEGORY_ID,
            "limit": str(limit),
            "offset": str(offset),
        }
        if sort_by_newest:
            params["sort"] = "newlyListed"

        resp = requests.get(self.browse_url, headers=headers, params=params, timeout=20)

        if resp.status_code == 401:
            # Token expiré/invalide malgré notre cache : on force un refresh une fois
            logger.warning("eBay: 401, on régénère le token et on retente une fois")
            self._access_token = None
            token = self._get_access_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(self.browse_url, headers=headers, params=params, timeout=20)

        resp.raise_for_status()
        payload = resp.json()

        listings = []
        for item in payload.get("itemSummaries", []):
            listings.append(self._parse_item_summary(item))
        return listings

    @staticmethod
    def _parse_item_summary(item: dict) -> EbayListing:
        price_info = item.get("price", {})
        shipping_options = item.get("shippingOptions", [])
        shipping_cost = None
        if shipping_options:
            cost_info = shipping_options[0].get("shippingCost", {})
            shipping_cost = float(cost_info["value"]) if "value" in cost_info else None

        seller = item.get("seller", {})
        image = item.get("image", {})
        item_location = item.get("itemLocation", {})

        return EbayListing(
            item_id=item.get("itemId", ""),
            title=item.get("title", ""),
            price=float(price_info.get("value", 0)),
            currency=price_info.get("currency", "EUR"),
            shipping_cost=shipping_cost,
            item_web_url=item.get("itemWebUrl", ""),
            image_url=image.get("imageUrl"),
            condition=item.get("condition"),
            seller_username=seller.get("username"),
            seller_feedback_percentage=(
                float(seller["feedbackPercentage"]) if seller.get("feedbackPercentage") else None
            ),
            seller_feedback_score=seller.get("feedbackScore"),
            item_location_country=item_location.get("country"),
            raw=item,
        )
