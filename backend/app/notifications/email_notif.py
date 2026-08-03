import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email_notification(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    to_address: str,
    subject: str,
    body: str,
) -> bool:
    """
    Envoie un email via SMTP (STARTTLS). Retourne True/False sans lever
    d'exception pour ne pas casser le pipeline de scoring/notification.
    """
    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_address

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [to_address], msg.as_string())
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Email: envoi échoué (%s)", exc)
        return False


def format_deal_alert_html(listing) -> str:
    margin_txt = f"{listing.margin_net:.2f} €" if listing.margin_net is not None else "N/A"
    return f"""
    <h2>🔥 Bonne affaire détectée (score {listing.deal_score:.0f}/100)</h2>
    <p><strong>{listing.title}</strong></p>
    <ul>
      <li>Prix : {listing.price:.2f} € (+{listing.shipping_price:.2f} € port)</li>
      <li>Référence marché : {listing.reference_price or 'N/A'} €</li>
      <li>Marge estimée : {margin_txt}</li>
      <li>Source : {listing.source.value if hasattr(listing.source, 'value') else listing.source}</li>
    </ul>
    <p><a href="{listing.url}">Voir l'annonce</a></p>
    """
