import logging

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """
    Envoie un message Telegram via l'API Bot officielle. Retourne True/False
    plutôt que de lever une exception, pour ne jamais faire planter le
    pipeline de scoring à cause d'une notif qui échoue.
    """
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Telegram: envoi échoué (%s)", exc)
        return False


def format_deal_alert(listing) -> str:
    """Construit le texte du message d'alerte à partir d'un objet Listing."""
    margin_txt = f"{listing.margin_net:.2f} €" if listing.margin_net is not None else "N/A"
    return (
        f"🔥 <b>Bonne affaire détectée</b> (score {listing.deal_score:.0f}/100)\n\n"
        f"<b>{listing.title}</b>\n"
        f"Prix : {listing.price:.2f} € (+{listing.shipping_price:.2f} € port)\n"
        f"Référence marché : {listing.reference_price or 'N/A'} €\n"
        f"Marge estimée : {margin_txt}\n"
        f"Source : {listing.source.value if hasattr(listing.source, 'value') else listing.source}\n\n"
        f"{listing.url}"
    )
