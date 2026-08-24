"""
Tests du rapprochement annonce -> carte (services/price_index.py).

Tous les titres utilises ici sont de VRAIS titres d'annonces, releves le
25/08/2026 sur les 500 dernieres annonces collectees en production. C'est
la seule facon honnete de tester ce code : un titre invente par un
developpeur est toujours plus propre que ce qu'ecrit un vendeur reel.

L'index de test reproduit fidelement deux pieges observes en prod :
- un meme nom de carte existe dans plusieurs series a des prix tres
  differents (10 cartes "Dracaufeu", de 3 a 250 EUR) ;
- les codes carte melangent les conventions de zero-padding ("PBL 016"
  mais "CEC 66"), ce qui faisait echouer la comparaison textuelle.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MarketCardPrice
from app.services import price_index
from app.services.price_index import find_price_for_listing


def card(name_slug, display_name, card_code, price, series="Serie test"):
    return MarketCardPrice(
        name_slug=name_slug, display_name=display_name, card_code=card_code,
        price_eur=price, price_low_eur=price * 0.9, price_high_eur=price * 1.1,
        series_name=series, source="zebradex",
    )


class PriceMatchingTestCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add_all(self._index())
        self.db.commit()
        # Le cache des noms est global au module : on le vide entre deux
        # tests, sinon un test herite de l'index du precedent.
        price_index._slug_cache = []
        price_index._slug_cache_at = None

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = []
        price_index._slug_cache_at = None

    def _index(self):
        return [
            # "Dracaufeu" existe dans plusieurs series, a des prix sans
            # rapport : c'est le piege principal du matching par nom seul.
            card("dracaufeu", "Dracaufeu", "BS 4", 250.0, "Set de Base"),
            card("dracaufeu", "Dracaufeu", "CEC 66", 7.48, "Cosmic Eclipse"),
            card("dracaufeu", "Dracaufeu", "GEN 11", 3.20, "Generations"),
            card("dracaufeu-ex", "Dracaufeu Ex", "PAF 054", 29.50, "Destinees Paldea"),
            card("dracaufeu-v", "Dracaufeu V", "SWSH 019", 41.00, "Epee et Bouclier"),
            # Noms francais en plusieurs mots : impossibles a retrouver
            # avant, le parseur ne construisait que des paires de mots.
            card("epine-de-fer", "Epine de Fer", "TEF 62", 1.90, "Forces Temporelles"),
            card("paume-de-fer", "Paume de Fer", "TEF 61", 2.40, "Forces Temporelles"),
            card("stade-en-ruines", "Stade en Ruines", "PAR 215", 12.00, "Faille Paradoxe"),
            card("mew-ex", "Mew Ex", "PAF 232", 180.0, "Destinees Paldea"),
            card("salameche", "Salameche", "MEW 004", 1.10, "151"),
        ]

    def match(self, titre):
        return find_price_for_listing(self.db, titre)


class TestNomsEnPlusieursMots(PriceMatchingTestCase):
    def test_epine_de_fer(self):
        m = self.match("Carte Pokémon Epine de Fer 062/162 Holo - Ecarlate et Violet - Forces Temporelles FR")
        self.assertIsNotNone(m, "un nom de carte en 3 mots doit etre retrouve")
        self.assertEqual(m.row.display_name, "Epine de Fer")

    def test_paume_de_fer(self):
        m = self.match("Carte Pokémon Paume de Fer 061/162 - Ecarlate et Violet - Forces Temporelles FR")
        self.assertIsNotNone(m)
        self.assertEqual(m.row.display_name, "Paume de Fer")

    def test_stade_en_ruines(self):
        m = self.match("Carte Pokémon Stade en Ruines Gold 215/196")
        self.assertIsNotNone(m)
        self.assertEqual(m.row.display_name, "Stade en Ruines")


class TestVariantes(PriceMatchingTestCase):
    def test_variante_v_non_confondue_avec_la_carte_de_base(self):
        """Le bug le plus couteux : "Dracaufeu V" recevait le prix de
        "Dracaufeu" (7,48 EUR) parce que le "V" d'une seule lettre etait
        purement efface du titre."""
        m = self.match("Carte Pokémon Dracaufeu V Shiny 079/073 - La Voie")
        self.assertIsNotNone(m)
        self.assertEqual(m.row.display_name, "Dracaufeu V")
        self.assertEqual(m.row.price_eur, 41.00)

    def test_variante_ex_prioritaire_sur_le_nom_nu(self):
        m = self.match("Carte card pokémon dracaufeu ex 054 091")
        self.assertEqual(m.row.display_name, "Dracaufeu Ex")

    def test_variante_absente_de_l_index_est_signalee(self):
        """"Dracaufeu VMAX" n'existe pas dans l'index : on retombe sur une
        autre carte, et il faut le dire au lieu d'afficher un prix sur."""
        m = self.match("Carte Pokémon Dracaufeu VMAX 020/189")
        self.assertIsNotNone(m)
        self.assertIsNotNone(m.warning, "un rabattement de variante doit etre signale")
        self.assertEqual(m.confidence, "low")
        self.assertTrue(m.is_uncertain)

    def test_pas_d_alerte_quand_la_variante_correspond(self):
        m = self.match("Mew ex PAF 232 SIR")
        self.assertIsNone(m.warning)


class TestNumeroDeSet(PriceMatchingTestCase):
    def test_numero_departage_les_homonymes(self):
        """4/102 = le Dracaufeu du Set de Base (250 EUR), pas la mediane
        des 3 Dracaufeu de l'index."""
        m = self.match("Carte Pokémon PSA 10 Dracaufeu 4/102 célébrations")
        self.assertEqual(m.confidence, "high")
        self.assertEqual(m.row.card_code, "BS 4")
        self.assertEqual(m.row.price_eur, 250.0)

    def test_comparaison_numerique_et_non_textuelle(self):
        """Le code reel est "CEC 66" (non zero-padde) : l'ancien
        LIKE '%066' ne le trouvait jamais."""
        m = self.match("Carte Pokémon Dracaufeu 66/236 Cosmic Eclipse")
        self.assertEqual(m.confidence, "high")
        self.assertEqual(m.row.card_code, "CEC 66")


class TestCodeCarte(PriceMatchingTestCase):
    def test_code_explicite(self):
        m = self.match("Mew ex PAF 232 SIR")
        self.assertEqual(m.confidence, "high")
        self.assertEqual(m.row.display_name, "Mew Ex")

    def test_code_non_padde_dans_le_titre(self):
        m = self.match("Carte Pokemon Salameche MEW 4 neuve")
        self.assertEqual(m.row.display_name, "Salameche")

    def test_mot_du_titre_pris_pour_un_code_ne_passe_plus(self):
        """"Epine de Fer 062/162" ne doit PAS produire le code "FER 062" :
        c'etait un faux match annonce en confiance HAUTE."""
        m = self.match("Carte Pokémon Epine de Fer 062/162 Holo")
        self.assertNotIn("code carte", m.reason)


class TestFautesDeFrappe(PriceMatchingTestCase):
    def test_faute_de_frappe_rattrapee(self):
        m = self.match("carte pokemon dracofeu holo")
        self.assertIsNotNone(m, "une faute d'une lettre doit etre rattrapee")
        self.assertIn("faute de frappe", m.reason)
        self.assertEqual(m.confidence, "low")

    def test_accent_manquant(self):
        m = self.match("carte pokemon salameche")
        self.assertEqual(m.row.display_name, "Salameche")

    def test_mot_trop_different_non_rattrape(self):
        """On prefere ne rien trouver plutot que d'inventer : "Ronflex"
        n'est pas une faute de frappe de "Dracaufeu"."""
        self.assertIsNone(self.match("carte pokemon Ronflex holo"))


class TestIncertitude(PriceMatchingTestCase):
    def test_homonymes_signales_comme_incertains(self):
        m = self.match("carte pokemon dracaufeu")
        self.assertEqual(m.confidence, "low")
        self.assertEqual(len(m.candidates), 3)
        self.assertGreater(m.price_spread_eur, 200)
        self.assertTrue(m.is_uncertain)

    def test_details_exposes_au_frontend(self):
        detail = self.match("carte pokemon dracaufeu").to_dict()
        for cle in ("candidates_count", "price_spread_eur", "uncertain", "warning"):
            self.assertIn(cle, detail)
        self.assertEqual(detail["candidates_count"], 3)
        self.assertTrue(detail["uncertain"])

    def test_match_sur_code_non_incertain(self):
        m = self.match("Mew ex PAF 232 SIR")
        self.assertFalse(m.is_uncertain)


class TestAbsenceDeMatch(PriceMatchingTestCase):
    def test_titre_vide(self):
        self.assertIsNone(self.match(""))

    def test_titre_sans_nom_de_carte(self):
        self.assertIsNone(self.match("Carte Pokémon"))

    def test_lot_generique(self):
        self.assertIsNone(self.match("Beau Lot de 10 cartes Pokémon 151 Reverse Holo EV3.5 Neuves Fr"))


if __name__ == "__main__":
    unittest.main()
