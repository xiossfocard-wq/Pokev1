"""Analyse indicative de l'état d'une carte + OCR (nom, numéro, langue), via l'API Anthropic."""
import base64
import json
import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = (
    "Tu es un assistant d'estimation INDICATIVE de l'état visuel de cartes "
    "Pokémon à partir de photos d'annonces de seconde main. Ce n'est pas un "
    "grading professionnel (PSA/BGS/CGC) et tu dois le rappeler implicitement "
    "en restant prudent dans tes formulations (\"semble\", \"peut suggérer\"). "
    "Analyse le centrage, l'état des coins, la présence de rayures ou "
    "d'éclats visibles, et la netteté/brillance de la surface si visible. "
    "En plus de l'analyse d'état, lis aussi le texte imprimé visible sur la "
    "carte elle-même (pas le titre/la description de l'annonce, qui peuvent "
    "être imprécis) : le nom du Pokémon tel qu'imprimé, le numéro de set "
    "au format 'X/Y' s'il est visible, et la LANGUE du texte imprimé sur la "
    "carte (français, anglais, japonais, allemand, etc. — déduite du texte "
    "visible sur la carte elle-même, ex 'Dresseur'/'Énergie' = français vs "
    "'Trainer'/'Energy' = anglais). Si ce n'est pas lisible (photo floue, "
    "coupée, texte caché), laisse ces champs vides plutôt que de deviner. "
    "Réponds UNIQUEMENT en JSON valide, sans texte avant/après, au format : "
    '{"score": <0-100>, "centering": "<commentaire court>", '
    '"corners": "<commentaire court>", "surface": "<commentaire court>", '
    '"confidence": "<low|medium|high>", "caveats": "<ce qui limite l\'analyse, '
    'ex: photo floue, mauvais éclairage, une seule face visible>", '
    '"printed_name": "<nom exact lu sur la carte, ou vide si illisible>", '
    '"printed_set_number": "<ex \'4/102\', ou vide si illisible>", '
    '"printed_language": "<français|anglais|japonais|allemand|italien|'
    'espagnol|coréen|chinois|autre|vide si illisible>", '
    '"ocr_confidence": "<low|medium|high>"}'
)


@dataclass
class VisionQualityResult:
    score: float
    centering: str
    corners: str
    surface: str
    confidence: str
    caveats: str
    printed_name: str = ""
    printed_set_number: str = ""
    printed_language: str = ""
    ocr_confidence: str = "low"
    raw_response: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "centering": self.centering,
            "corners": self.corners,
            "surface": self.surface,
            "confidence": self.confidence,
            "caveats": self.caveats,
            "printed_name": self.printed_name,
            "printed_set_number": self.printed_set_number,
            "printed_language": self.printed_language,
            "ocr_confidence": self.ocr_confidence,
            "disclaimer": (
                "Estimation indicative générée automatiquement à partir des "
                "photos de l'annonce — ne remplace pas un grading professionnel."
            ),
        }


def _fetch_image_as_base64(url: str, timeout: int = 15) -> Optional[tuple]:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Vision: impossible de récupérer l'image %s (%s)", url, exc)
        return None

    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    if content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        content_type = "image/jpeg"

    return base64.b64encode(resp.content).decode(), content_type


def analyze_card_photos(
    api_key: str,
    photo_urls: list,
    title: str,
    description: str,
    model: str = "claude-sonnet-4-6",
    max_photos: int = 4,
) -> Optional[VisionQualityResult]:
    if not photo_urls:
        return None

    content_blocks = []
    fetched = 0
    for url in photo_urls[:max_photos]:
        result = _fetch_image_as_base64(url)
        if result is None:
            continue
        b64_data, media_type = result
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64_data},
        })
        fetched += 1

    if fetched == 0:
        logger.warning("Vision: aucune photo n'a pu être récupérée pour l'analyse")
        return None

    content_blocks.append({
        "type": "text",
        "text": f"Titre de l'annonce : {title}\nDescription : {description or '(vide)'}",
    })

    payload = {
        "model": model,
        "max_tokens": 500,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content_blocks}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    try:
        resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Vision: appel API Anthropic échoué (%s)", exc)
        return None

    data = resp.json()
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    if not text_blocks:
        logger.error("Vision: réponse API sans bloc texte exploitable")
        return None

    try:
        parsed = json.loads(text_blocks[0])
        return VisionQualityResult(
            score=float(parsed["score"]),
            centering=parsed.get("centering", ""),
            corners=parsed.get("corners", ""),
            surface=parsed.get("surface", ""),
            confidence=parsed.get("confidence", "medium"),
            caveats=parsed.get("caveats", ""),
            printed_name=(parsed.get("printed_name") or "").strip(),
            printed_set_number=(parsed.get("printed_set_number") or "").strip(),
            printed_language=(parsed.get("printed_language") or "").strip().lower(),
            ocr_confidence=parsed.get("ocr_confidence", "low"),
            raw_response=parsed,
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.error("Vision: réponse JSON inattendue (%s) — contenu: %.200s", exc, text_blocks[0])
        return None
