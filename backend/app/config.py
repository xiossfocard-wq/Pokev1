"""
Configuration centralisée, lue depuis les variables d'environnement (avec
.env chargé automatiquement en local via python-dotenv). Aucune valeur par
défaut n'est fournie pour les secrets (clés API, tokens) : l'app démarre
mais les modules concernés restent inactifs tant qu'ils ne sont pas fournis,
avec un avertissement clair au démarrage plutôt qu'un crash.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # --- Base de données ---
    database_url: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///./dev.db")
    )

    # --- Scheduler ---
    check_interval_minutes: int = field(
        default_factory=lambda: _get_int("CHECK_INTERVAL_MINUTES", 20)
    )

    # --- eBay (Browse API) ---
    ebay_client_id: Optional[str] = field(default_factory=lambda: os.environ.get("EBAY_CLIENT_ID"))
    ebay_client_secret: Optional[str] = field(default_factory=lambda: os.environ.get("EBAY_CLIENT_SECRET"))
    ebay_marketplace_id: str = field(default_factory=lambda: os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_FR"))
    ebay_use_sandbox: bool = field(default_factory=lambda: _get_bool("EBAY_USE_SANDBOX", False))

    # --- Vinted (scraping) ---
    vinted_enabled: bool = field(default_factory=lambda: _get_bool("VINTED_ENABLED", True))
    vinted_request_delay_seconds: float = field(
        default_factory=lambda: _get_float("VINTED_REQUEST_DELAY_SECONDS", 8.0)
    )
    vinted_search_text: str = field(
        default_factory=lambda: os.environ.get("VINTED_SEARCH_TEXT", "carte pokemon")
    )

    # --- Filtre langue (active par defaut : cartes francaises uniquement) ---
    french_only: bool = field(
        default_factory=lambda: os.environ.get("FRENCH_ONLY", "true").lower() != "false"
    )

    # --- Cardmarket (prix de référence public, pas de clé API) ---
    # Voir app/collectors/cardmarket_prices.py pour comment obtenir cette URL
    # manuellement. Non renseigné -> fallback automatique sur le lookup
    # carte par carte (fonctionne sans aucune config).
    cardmarket_bulk_price_guide_url: Optional[str] = field(
        default_factory=lambda: os.environ.get("CARDMARKET_BULK_PRICE_GUIDE_URL")
    )

    # --- ZebraDex (prix de référence FR complémentaire, optionnel) ---
    # Liste d'URLs de pages "série" ZebraDex séparées par des virgules (voir
    # app/collectors/zebradex_prices.py pour le format d'URL et pourquoi on
    # ne peut pas interroger ZebraDex "à la volée" comme Cardmarket). Vide
    # par défaut -> ZebraDex simplement ignoré, aucun impact sur le reste.
    zebradex_series_urls: list = field(
        default_factory=lambda: [
            u.strip() for u in os.environ.get("ZEBRADEX_SERIES_URLS", "").split(",") if u.strip()
        ]
    )

    # --- Anthropic (scoring qualité par vision) ---
    anthropic_api_key: Optional[str] = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))
    vision_model: str = field(default_factory=lambda: os.environ.get("VISION_MODEL", "claude-sonnet-4-6"))

    # --- Notifications ---
    telegram_bot_token: Optional[str] = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: Optional[str] = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID"))

    smtp_host: Optional[str] = field(default_factory=lambda: os.environ.get("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: _get_int("SMTP_PORT", 587))
    smtp_user: Optional[str] = field(default_factory=lambda: os.environ.get("SMTP_USER"))
    smtp_password: Optional[str] = field(default_factory=lambda: os.environ.get("SMTP_PASSWORD"))
    notification_email_to: Optional[str] = field(default_factory=lambda: os.environ.get("NOTIFICATION_EMAIL_TO"))

    # --- Seuil de notification par défaut (modifiable ensuite via /settings) ---
    default_deal_score_threshold: float = field(
        default_factory=lambda: _get_float("DEFAULT_DEAL_SCORE_THRESHOLD", 70.0)
    )

    def missing_required_for_startup(self) -> list:
        """Retourne les modules qui resteront inactifs faute de config, à
        afficher comme avertissement au démarrage (pas bloquant)."""
        missing = []
        if not self.ebay_client_id or not self.ebay_client_secret:
            missing.append("eBay Browse API (EBAY_CLIENT_ID / EBAY_CLIENT_SECRET manquants)")
        if not self.anthropic_api_key:
            missing.append("Analyse qualité par vision (ANTHROPIC_API_KEY manquant)")
        if not self.telegram_bot_token or not self.telegram_chat_id:
            missing.append("Notifications Telegram (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID manquants)")
        if not self.smtp_host or not self.notification_email_to:
            missing.append("Notifications email (SMTP_HOST / NOTIFICATION_EMAIL_TO manquants)")
        return missing


settings = Settings()
