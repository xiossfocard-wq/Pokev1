"""
Ce qui n'a pas ete mesure ne s'affiche pas comme une mesure, et ne pese pas.

LE CONSTAT
----------
- La page de recherche Vinted ne donne pas les avis du vendeur : TOUTES les
  annonces Vinted recevaient la meme note neutre, affichee « fiabilite
  vendeur 45/100 » comme un constat, et comptant pour 20 % du score.
- Un titre sans un mot sur l'etat donnait « qualite (texte) ~50/100 » : une
  absence d'information presentee comme une carte moyenne, comptant 30 %.
- L'analyse du texte cherchait ses mots en sous-chaine : « tache » dans
  « détachée », « pli » dans « remplie » ; « jamais joué » etait a la fois un
  gage d'etat et l'aveu d'une carte jouee ; et le « MP » de « contactez-moi
  en MP » decotait la carte de 30 % comme « Moderately Played ».
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.collectors.vinted_scraper import VintedListing
from app.database import Base
from app.models import Listing, MarketCardPrice, SourcePlatform
from app.pipeline import _nouvelle_annonce_vinted, _score_listing, calculer_deal_score, rescore_unpriced_listings
from app.schemas import ListingOut
from app.scoring.card_appeal import detect_card_appeal
from app.scoring.quality_text import analyze_text_quality
from app.services import price_index
from app.settings_service import DEFAULTS


class TestTexte(unittest.TestCase):
    def test_jamais_joue_est_un_gage_d_etat(self):
        r = analyze_text_quality("Luffy jamais joué", "")
        self.assertEqual(r.matched_negative, [])
        self.assertGreater(r.score, 50)

    def test_un_mot_n_est_pas_trouve_dans_un_autre(self):
        for titre in ("Carte détachée du classeur", "Pochette remplie", "Lot avec jouet"):
            with self.subTest(titre=titre):
                r = analyze_text_quality(titre, "")
                self.assertEqual(r.matched_negative, [])
                self.assertFalse(r.informatif)

    def test_le_mp_d_un_message_prive_n_est_pas_un_etat(self):
        for texte in ("contactez-moi en MP", "envoyez un mp", "réponse par MP"):
            with self.subTest(texte=texte):
                self.assertIsNone(analyze_text_quality("Zoro OP01-025", texte).condition_tier)
        self.assertEqual(analyze_text_quality("Shanks OP01-120 MP", "").condition_tier, "MP")

    def test_near_mint_ne_compte_pas_mint_une_seconde_fois(self):
        self.assertEqual(analyze_text_quality("Ace near mint", "").matched_positive, ["near mint"])

    def test_un_titre_qui_ne_dit_rien_de_l_etat_n_est_pas_informatif(self):
        self.assertFalse(analyze_text_quality("Shanks OP01-120", "").informatif)
        self.assertTrue(analyze_text_quality("Shanks OP01-120 rayure", "").informatif)


def annonce(**champs):
    base = dict(source=SourcePlatform.VINTED, external_id="x", title="Shanks OP01-120",
                url="https://vinted.test/x", price=10.0, currency="EUR",
                reference_price=24.0, margin_ratio=0.0, savings_ratio=0.25,
                quality_text_score=50.0, seller_reliability_score=45.0,
                seller_reliability_detail="Profil Vinted sans avis exploitable",
                quality_text_detail={"matched_positive": [], "matched_negative": [],
                                     "negated_negative": [], "condition_tier": None},
                price_detail={})
    base.update(champs)
    return Listing(**base)


class TestScore(unittest.TestCase):
    reglages = dict(DEFAULTS, mode_evaluation="collection")
    bonus = detect_card_appeal("Shanks OP01-120", "")["appeal_bonus"]

    def test_sans_vendeur_ni_texte_le_score_est_celui_de_l_affaire(self):
        """25 % sous la cote = la moitie des points d'affaire (plafond 50 %).
        Avant : 0,5 x 50 + 0,3 x 50 + 0,2 x 45 = 49, les deux inconnus
        comptes comme des mesures."""
        a = annonce()
        self.assertFalse(a.vendeur_connu)
        self.assertFalse(a.texte_informatif)
        # Le bonus d'attrait suit l'affaire : la moitie ici.
        self.assertAlmostEqual(calculer_deal_score(a, self.reglages), 50.0 + self.bonus * 0.5)

    def test_le_bonus_d_attrait_suit_l_affaire(self):
        """Une remise de 10 % sur une SEC de Shanks ne vaut pas une alerte :
        ajoute tel quel, le bonus (30 points) y suffisait presque."""
        petite = annonce(savings_ratio=0.10)   # 20 points d'affaire
        self.assertAlmostEqual(calculer_deal_score(petite, self.reglages), 20.0 + self.bonus * 0.2)
        self.assertLess(calculer_deal_score(petite, self.reglages), 30)
        moitie = annonce(savings_ratio=0.50)   # tous les points d'affaire
        self.assertEqual(calculer_deal_score(moitie, self.reglages), 100.0)

    def test_un_vendeur_note_compte(self):
        connu = annonce(seller_reliability_score=95.0, seller_reliability_detail="4.9/5 sur 120 avis")
        inconnu = annonce()
        self.assertTrue(connu.vendeur_connu)
        self.assertNotEqual(calculer_deal_score(connu, self.reglages),
                            calculer_deal_score(inconnu, self.reglages))

    def test_un_texte_qui_dit_l_etat_compte(self):
        informatif = annonce(quality_text_score=90.0, quality_text_detail={"matched_positive": ["near mint"]})
        self.assertTrue(informatif.texte_informatif)
        self.assertNotEqual(calculer_deal_score(informatif, self.reglages),
                            calculer_deal_score(annonce(), self.reglages))

    def test_l_api_dit_ce_qui_a_ete_mesure(self):
        sortie = ListingOut.model_validate(annonce(id=1, status="scored", shipping_price=0.0,
                                                   photo_urls=[], is_vintage=False,
                                                   is_popular_character=False,
                                                   first_seen_at=__import__("datetime").datetime(2026, 10, 26),
                                                   last_seen_at=__import__("datetime").datetime(2026, 10, 26)))
        self.assertFalse(sortie.vendeur_connu)
        self.assertFalse(sortie.texte_informatif)


class TestCollecte(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.db.add(MarketCardPrice(card_code="OP01-120", name_slug="shanks", display_name="Shanks",
                                    price_eur=24.0, language="fr", source="opecards"))
        self.db.commit()
        price_index._slug_cache = None

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = None

    def test_une_annonce_vinted_n_a_pas_d_avis_vendeur(self):
        a = _nouvelle_annonce_vinted(VintedListing(item_id="1", title="Shanks OP01-120", price=10.0,
                                                   currency="EUR", url="https://www.vinted.fr/items/1"))
        self.assertFalse(a.vendeur_connu)

    def test_le_texte_analyse_est_garde(self):
        a = _nouvelle_annonce_vinted(VintedListing(item_id="2", title="Shanks OP01-120 rayure", price=10.0,
                                                   currency="EUR", url="https://www.vinted.fr/items/2"))
        self.db.add(a)
        self.db.commit()
        _score_listing(self.db, a)
        self.assertEqual(a.quality_text_detail["matched_negative"], ["rayure"])
        self.assertTrue(a.texte_informatif)

    def test_une_annonce_notee_sans_texte_garde_est_renotee(self):
        a = _nouvelle_annonce_vinted(VintedListing(item_id="3", title="Shanks OP01-120", price=10.0,
                                                   currency="EUR", url="https://www.vinted.fr/items/3"))
        self.db.add(a)
        self.db.commit()
        _score_listing(self.db, a)
        a.quality_text_detail = None
        self.db.commit()
        self.assertEqual(rescore_unpriced_listings(self.db)["examined"], 1)
        self.db.refresh(a)
        self.assertIsNotNone(a.quality_text_detail)


if __name__ == "__main__":
    unittest.main()
