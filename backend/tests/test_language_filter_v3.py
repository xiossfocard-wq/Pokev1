"""
Tests de la detection de langue amelioree (core/language_filter.py).

Comme pour le matching, tous les titres sont de VRAIS titres releves le
25/08/2026 sur les 500 dernieres annonces de la production. Les deux
categories de tests sont aussi importantes l'une que l'autre :

- ce qui doit etre ECARTE : sur ces 500 annonces, ~18% n'etaient pas
  francaises et passaient toutes le filtre precedent ;
- ce qui doit etre GARDE : un filtre trop zele fait disparaitre de vraies
  bonnes affaires francaises sans que l'utilisateur sache pourquoi. Les
  faux positifs sont plus graves que les faux negatifs ici.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.language_filter import looks_non_french, detect_language


class TestAnnoncesEtrangeresEcartees(unittest.TestCase):
    def test_allemand_sans_declaration_de_langue(self):
        """~30 annonces de ce moule dans l'echantillon. Le vendeur ne dit
        jamais "allemand" : il ecrit simplement en allemand."""
        for titre in [
            "Pokémon Karte Sirapfel Einzelkarte Sammelkarte",
            "Pokémon Karte Türkisgrüne Maske Ogerpon Einzelkarte Sammelkarte",
            "Pokémon Karte Fundamentmaske-Ogerpon Einzelkarte Sammelkarte",
        ]:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))
                self.assertEqual(detect_language(titre).language, "de")

    def test_italien(self):
        for titre in [
            "Carta Pokemon Grookey promozionale 30th anniversario graad 9",
            "carta da collezione Pokemon",
            "Carta Pokémon magneton 27/112 condizioni ottime vintage",
            "Carta Pokemon Monte gravità gold scintille folgoranti ita",
        ]:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))

    def test_neerlandais(self):
        self.assertTrue(looks_non_french("Eevee graad 9.5 ita"))
        self.assertTrue(looks_non_french("Piplup GRAAD 9.5"))
        self.assertTrue(
            looks_non_french("Eevee reverse holo Prismatic Evolutions Pokémon kaart")
        )

    def test_nom_de_pokemon_anglais(self):
        """Le signal decisif pour les cartes anglaises muettes : une carte
        francaise s'appelle Dracaufeu, pas Charizard."""
        for titre in [
            "Charizard EX Secret Rare 223/197 MT",
            "Gengar 057/091 Holo (Trick or Trade Halloween 2024) - Near Mint!",
            "Psyduck #28 Pokemon Astral Radiance",
            "Pokemon Munchlax",
            "Charizard V 017/172",
            "Pokémon Salamence EX holo card mint",
        ]:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))
                self.assertEqual(detect_language(titre).language, "en")

    def test_raison_expliquee(self):
        """Une annonce ecartee doit pouvoir etre expliquee, sinon elle
        disparait du dashboard sans que personne ne sache pourquoi."""
        verdict = detect_language("Charizard V 017/172")
        self.assertFalse(verdict.is_french)
        self.assertTrue(verdict.reasons)
        self.assertIn("Dracaufeu", verdict.reasons[0])


class TestAnnoncesFrancaisesGardees(unittest.TestCase):
    def test_titres_francais_ordinaires(self):
        for titre in [
            "Carte Pokémon Epine de Fer 062/162 Holo - Ecarlate et Violet FR",
            "Carte Pokémon Dracaufeu V Shiny 079/073 - La Voie",
            "Beau Lot de 10 cartes Pokémon 151 Reverse Holo EV3.5 Neuves Fr",
            "Base Secrète de la Team Aqua 28/34 XY Double Danger 2015",
            "Carte Pokémon Stade en Ruines Gold 215/196",
            "Carte en très bon état de collection",
        ]:
            with self.subTest(titre=titre):
                self.assertFalse(looks_non_french(titre), titre)

    def test_vendeur_qui_ecrit_les_deux_noms(self):
        """Cas reel : beaucoup de vendeurs francais ajoutent le nom anglais
        pour etre trouves dans les recherches. La presence du nom FRANCAIS
        doit desarmer le signal "nom anglais"."""
        self.assertFalse(
            looks_non_french("Carte pokemon Dracaufeu Charizard Gold Metal 4/102 Celebrations")
        )
        self.assertFalse(looks_non_french("Ectoplasma (s4a 71) Shiny Star V - Gengar"))

    def test_mention_francaise_explicite_l_emporte(self):
        self.assertFalse(looks_non_french("Charizard carte française VF holo"))

    def test_un_seul_mot_anglais_ne_suffit_pas(self):
        """"card", "holo", "full art" sont employes par des vendeurs
        francais : un seul de ces mots ne doit rien declencher."""
        self.assertFalse(
            looks_non_french("Carte card pokémon dracaufeu v de peter promo jumbo")
        )
        self.assertFalse(looks_non_french("Kravos V Full Art 72/73 – Near Mint – FR"))

    def test_titre_minimal(self):
        self.assertFalse(looks_non_french("Carte Pokémon"))
        self.assertFalse(looks_non_french("Pokemon"))


class TestRetroCompatibilite(unittest.TestCase):
    """La detection precedente doit continuer de fonctionner a l'identique."""

    def test_declaration_explicite(self):
        self.assertTrue(looks_non_french("Zekrom carte anglaise rare"))
        self.assertTrue(looks_non_french("Pikachu version japonaise"))

    def test_alphabet_non_latin(self):
        self.assertTrue(looks_non_french("ピカチュウ 美品"))
        self.assertTrue(looks_non_french("포켓몬 카드"))

    def test_jeton_court(self):
        self.assertTrue(looks_non_french("Dracaufeu JP set de base"))
        self.assertFalse(looks_non_french("carte enjpolie fictive"))

    def test_entrees_vides(self):
        self.assertFalse(looks_non_french(None, "", None))

    def test_description_aussi_analysee(self):
        self.assertTrue(looks_non_french("Zekrom", "État japonais, très bon état"))


if __name__ == "__main__":
    unittest.main()
