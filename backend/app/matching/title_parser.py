"""
Analyse pure d'un titre d'annonce : extraction du code carte, du numero de
set et des noms de carte candidats.

Volontairement SANS dependance a SQLAlchemy ni au reseau, pour que cette
logique - la plus delicate et la plus susceptible de regresser - reste
testable en isolation (voir tests/test_title_parser.py). Le service
price_index.py se contente d'interroger la base avec ces candidats.

Mesures faites le 25/08/2026 sur 500 annonces reelles de la prod, qui ont
guide cette version :
- les noms de cartes francais font souvent 3 mots ("Epine de Fer", "Paume
  de Fer", "Stade en Ruines") : la version precedente ne construisait que
  des paires de mots et les ratait toutes ;
- les variantes et initiales ecrites avec une seule lettre ("Monkey D.
  Luffy", "Portgas D. Ace") etaient purement et simplement effacees par le filtre
  `len(mot) > 1`, si bien qu'une carte V recevait le prix de la carte de
  base (7,48 EUR au lieu du prix reel) ;
- les codes modernes de type "sv8a 215" n'etaient pas reconnus.
"""
import re
import unicodedata
from typing import List, Optional, Tuple

# "4/102", "232/193", "19/98"...
SET_NUMBER_PATTERN = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")

# Codes carte. Formats reels observes dans les annonces et dans l'index :
#   "PAF 232", "PAF 5", "EV01-045", "sv8a 215", "sv7 108", "SVP 161", "TG08"
# D'ou le prefixe = 2 a 4 lettres, suivi optionnellement de 1-2 chiffres
# puis d'une lettre de variante ("SV8A", "EV01").
CARD_CODE_PATTERN = re.compile(r"\b([A-Z]{2,4}\d{0,2}[A-Z]?)[\s-]?(\d{1,3})\b")

# Meme chose, mais collee a un numero de set : "sv8a 215/187", "sv1v 082/078".
# On n'accepte ce cas que si le prefixe contient un chiffre (SV8A, SV1V,
# EV04), ce qui distingue un vrai code de bloc d'un simple mot du titre :
# "Epine de Fer 062/162" ne doit surtout pas produire le code "FER 062".
CARD_CODE_BEFORE_SET_PATTERN = re.compile(
    r"\b([A-Z]{2,4}\d{1,2}[A-Z]?)[\s-]?(\d{1,3})\s*/\s*\d{1,3}\b"
)

# Prefixes qui ressemblent a un code mais n'en sont pas : langue, etat,
# gradings. Sans ca "FR 232" ou "PSA 10" passeraient pour des codes carte
# et produiraient un faux match en confiance "haute".
NOT_CODE_PREFIXES = {
    "FR", "VF", "EN", "IT", "DE", "ES", "JP", "JPN", "PSA", "BGS", "CGC",
    "NM", "LP", "MP", "HP", "DMG", "ED", "PER", "MEP", "LOT", "TBE",
}

# Mots frequents dans les titres d'annonces qui ne sont pas des noms de
# carte. Servent a deux choses : exclure un mot isole comme candidat, et
# interdire qu'un groupe de mots COMMENCE ou FINISSE par l'un d'eux.
TITLE_NOISE = {
    # Le nom du JEU est du bruit : presque toutes les annonces le citent, et
    # sans lui les candidats devenaient « one-piece-monkey-luffy » au lieu de
    # « monkey-d-luffy ».
    "one", "piece", "onepiece", "tcg", "bandai",
    # Rarete et traitements propres a One Piece.
    "sr", "ur", "parallel",
    "super",
    # « d » est garde comme MOT par _words (initiale de « Monkey D. Luffy »),
    # mais reste du remplissage : un groupe ne peut ni commencer ni finir par
    # lui, il ne peut que se trouver au milieu d'un nom.
    "d",
    "carte", "cartes", "card", "cards", "lot", "lots", "holo",
    "rare", "neuve", "neuf", "occasion", "fr", "francaise", "francais",
    "tres", "bon", "etat", "mint", "nm", "lp", "mp", "hp", "psa", "bgs",
    "cgc", "the", "de", "du", "des", "la", "le", "les", "un", "une", "et",
    "en", "au", "aux", "avec", "pour", "sur", "vends", "vend", "vente",
    "prix", "envoi", "protege", "sleeve", "toploader", "shiny", "reverse",
    "promo", "jumbo", "full", "art", "gold", "near",
    "grade", "gradee", "graded", "edition", "ere", "eme", "vintage",
    "collection", "belle", "beau", "sans", "doubles", "serie", "series",
    "bloc", "niv",
}

# Suffixes qui font partie du nom reel d'une carte : gardes dans les
# groupes de mots ("monkey-d-luffy-leader", "roronoa-zoro-parallele"),
# jamais utilises seuls et jamais en debut de groupe.
#
# Ils ne sont PAS du bruit, et c'est tout l'enjeu : un Leader et un
# Personnage du meme nom sont deux cartes differentes, souvent a des prix
# sans rapport. Tant que ces mots etaient traites comme du remplissage,
# deux choses cassaient en silence :
#
# 1. un groupe ne peut pas finir par un mot de bruit, donc le candidat
#    "monkey-d-luffy-leader" n'etait jamais construit : une annonce
#    « Luffy Leader » ne retrouvait pas sa carte ;
# 2. `extract_variant` ne rendait jamais rien, donc l'alerte « le titre
#    annonce une variante que la carte retenue n'a pas » ne se declenchait
#    jamais. Le prix d'un Personnage pouvait s'afficher, en confiance,
#    sous une annonce de Leader.
NAME_SUFFIXES = {
    "leader", "parallele", "manga", "alternative", "alt",
    "secret", "sec",
}

# Variantes ecrites sur une seule lettre. One Piece n'en a pas : ses
# variantes s'ecrivent en toutes lettres (ci-dessus). L'ensemble reste
# defini — le filtre de mots courts s'y refere — mais vide.
VARIANT_LETTERS: set = set()

# Taille maximale d'un groupe de mots teste comme nom de carte. 4 couvre
# "Base Secrete de la Team Aqua" tronque a "secrete-de-la-team" et surtout
# les noms a rallonge type "Decodage de Decryptomane".
MAX_NAME_WORDS = 4

# Garde-fou : un titre a rallonge peut generer beaucoup de groupes. On
# plafonne pour garder une seule requete SQL de taille raisonnable.
MAX_CANDIDATES = 40


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return normalized.lower()


def extract_card_codes(text: str) -> List[str]:
    """
    Codes carte normalises. On renvoie DEUX formes pour chaque code trouve :
    zero-padde ("PAF 005") et brut ("PAF 5"), car l'index ZebraDex melange
    les deux conventions (observe en prod : "PBL 016" mais "LOT 5",
    "CEC 66"). Tester les deux evite de rater un match pour une histoire de
    zero.
    """
    # On efface d'abord les numeros de set ("062/162") : sans ca le mot qui
    # les precede est pris pour un prefixe de code et produit des faux
    # comme "FER 062" (depuis "Epine de Fer 062/162") ou "GOLD 215" - des
    # faux annonces en confiance HAUTE, donc particulierement nuisibles.
    cleaned = SET_NUMBER_PATTERN.sub(" ", (text or "").upper())

    out = []

    def keep(prefix: str, number: str):
        letters = re.match(r"[A-Z]+", prefix)
        if prefix in NOT_CODE_PREFIXES or (letters and letters.group(0) in NOT_CODE_PREFIXES):
            return
        for form in (f"{prefix} {number.zfill(3)}", f"{prefix} {number.lstrip('0') or '0'}"):
            if form not in out:
                out.append(form)

    # Codes de bloc colles au numero de set : a recuperer AVANT l'effacement.
    for match in CARD_CODE_BEFORE_SET_PATTERN.finditer((text or "").upper()):
        keep(*match.groups())

    for match in CARD_CODE_PATTERN.finditer(cleaned):
        keep(*match.groups())

    return out


def extract_set_number(text: str) -> Optional[Tuple[str, str]]:
    """Retourne (numero, total) zero-paddes, ex ("004", "102")."""
    match = SET_NUMBER_PATTERN.search(text or "")
    if not match:
        return None
    number, total = match.groups()
    return number.zfill(3), total.zfill(3)


# Initiales conservees malgre leur longueur de 1. One Piece en fait un usage
# constant — Monkey D. Luffy, Portgas D. Ace, Marshall D. Teach, Gol D. Roger
# — et les jeter produisait « monkey-luffy », qui ne correspond a aucun slug
# de l'index (« monkey-d-luffy »). Le rapprochement par nom echouait donc sur
# les personnages les plus demandes du jeu.
INITIALES = {"d"}


def _words(text: str) -> List[str]:
    raw = [w for w in re.split(r"[^a-z0-9]+", normalize(text)) if w]
    return [w for w in raw
            if len(w) > 1 or w in VARIANT_LETTERS or w in INITIALES]


def _is_fillerish(word: str) -> bool:
    return word in TITLE_NOISE or word in NAME_SUFFIXES or word.isdigit()


def extract_name_candidates(text: str) -> List[str]:
    """
    Slugs candidats depuis le titre, ordonnes du PLUS SPECIFIQUE au moins
    specifique : groupes de 4 mots, puis 3, puis 2, puis mots isoles.
    C'est cet ordre qui garantit qu'on essaie "epine-de-fer" avant "epine",
    et "monkey-d-luffy" avant "luffy".

    Regles de bon sens pour ne pas noyer la requete SQL sous du bruit :
    - un groupe ne peut ni commencer ni finir par un mot de remplissage
      ("carte one piece ...", "... de") ;
    - un groupe ne peut pas commencer par un suffixe de variante ("v-shiny"
      n'est pas un nom de carte, "monkey-d-luffy" oui) ;
    - un groupe contenant un nombre est ecarte (le numero de set est traite
      separement) ;
    - un groupe doit contenir au moins un mot qui ne soit ni du bruit ni un
      suffixe.
    """
    words = _words(text)

    candidates: List[str] = []
    for size in range(MAX_NAME_WORDS, 1, -1):
        for i in range(len(words) - size + 1):
            gram = words[i:i + size]
            if gram[0] in TITLE_NOISE or gram[0] in NAME_SUFFIXES:
                continue
            if gram[-1] in TITLE_NOISE:
                continue
            if any(w.isdigit() for w in gram):
                continue
            if all(_is_fillerish(w) for w in gram):
                continue
            slug = "-".join(gram)
            if slug not in candidates:
                candidates.append(slug)

    for word in words:
        if _is_fillerish(word) or word in VARIANT_LETTERS:
            continue
        if word not in candidates:
            candidates.append(word)

    return candidates[:MAX_CANDIDATES]


def extract_variant(text: str) -> Optional[str]:
    """
    Variante explicitement annoncee dans le titre ("ex", "gx", "v",
    "vmax"...). Sert a detecter un rabattement dangereux : si le titre dit
    "Monkey D. Luffy" et qu'on finit par retenir la carte "Luffy" tout
    court, le prix de reference est celui d'une autre carte, bien moins
    chere - il faut le signaler plutot que de l'afficher comme un prix sur.
    """
    found = [w for w in _words(text) if w in NAME_SUFFIXES]
    if not found:
        return None
    # Le plus long l'emporte : "vmax" prime sur le "v" qu'il contient.
    return max(found, key=len)
