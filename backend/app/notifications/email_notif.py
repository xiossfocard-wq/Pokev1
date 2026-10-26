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


def format_deal_alert_html(listing, mode: str = "collection", budget: dict = None) -> str:
    from html import escape

    from app.notifications.contenu import lignes_de_l_affaire

    lignes = "".join(f"<li>{intitule} : {escape(valeur)}</li>"
                     for intitule, valeur in lignes_de_l_affaire(listing, mode, budget))
    score = f" (score {listing.deal_score:.0f}/100)" if listing.deal_score is not None else ""
    entete = "★ Carte de ta liste dans ton budget" if budget else "🔥 Bonne affaire détectée"
    return f"""
    <h2>{entete}{score}</h2>
    <p><strong>{escape(listing.title)}</strong></p>
    <ul>{lignes}</ul>
    <p><a href="{escape(listing.url, quote=True)}">Voir l'annonce</a></p>
    """
