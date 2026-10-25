"""
Tests de la detection de langue (core/language_filter.py).

D'ou viennent ces titres
------------------------
Ce qui est teste ici, ce sont des TOURNURES de langue — « Karte …
Sammelkarte », « carta … promozionale », « graad 9.5 », le sigle « JAP »
colle en fin de titre. Ces tournures ont ete relevees sur 500 annonces
reelles de la production, et ce sont elles qui portent la valeur de
preuve : le filtre ne regarde rien d'autre.

Les noms de cartes, eux, sont ceux de One Piece, le jeu que le projet
suit. Les laisser dans un autre jeu aurait teste le filtre sur un
vocabulaire qu'il ne rencontrera plus jamais.

Les deux categories de tests comptent autant l'une que l'autre :

- ce qui doit etre ECARTE : sur l'echantillon d'origine, ~18% des annonces
  n'etaient pas francaises et passaient toutes le filtre precedent ;
- ce qui doit etre GARDE : un filtre trop zele fait disparaitre de vraies
  bonnes affaires francaises sans que l'utilisateur sache pourquoi. Les
  faux positifs sont plus graves que les faux negatifs ici.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.language_filter import looks_non_french, detect_language


class TestAnnoncesEtrangeresEcartees(unittest.TestCase):
    def test_allemand_sans_declaration_de_langue(self):
        """Le vendeur ne dit jamais "allemand" : il ecrit simplement en
        allemand. C'etait le moule le plus frequent de l'echantillon."""
        for titre in [
            "One Piece Karte Ruffy Einzelkarte Sammelkarte",
            "One Piece Karte Lorenor Zorro Einzelkarte Sammelkarte",
            "One Piece Karte Ruffy Leader sehr gut Zustand",
        ]:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))
                self.assertEqual(detect_language(titre).language, "de")

    def test_italien(self):
        for titre in [
            "Carta One Piece Rufy promozionale condizioni ottime",
            "carta da collezione One Piece",
            "Carta One Piece Zoro OP01-025 condizioni ottime",
            "Carta One Piece Nami rarissima spedizione tracciata",
        ]:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))

    def test_articles_italiens_seul_indice(self):
        """Le cas le plus difficile du jeu : les personnages s'ecrivent
        pareil dans les deux langues, donc l'article contracte peut etre le
        SEUL indice restant."""
        for titre in [
            "Monkey D. Luffy del Mare Orientale OP01-120",
            "Roronoa Zoro della Marina OP01-025",
            "Nico Robin dei Rivoluzionari OP02-068",
        ]:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))
                self.assertEqual(detect_language(titre).language, "it")

    def test_neerlandais(self):
        self.assertTrue(looks_non_french("One Piece Luffy graad 9.5"))
        self.assertTrue(looks_non_french("Zoro OP01-025 GRAAD 9.5"))
        self.assertTrue(looks_non_french("One Piece Nami zeldzaam kaart"))

    def test_sigles_de_langue_en_fin_de_titre(self):
        """Les vendeurs collent le sigle en fin de titre. Signal capital sur
        One Piece : les cartes japonaises y sont tres nombreuses, et le nom
        du personnage ne les distingue pas d'une francaise."""
        cas = [
            ("Carte One Piece Monkey D. Luffy OP01-120 JAP", "ja"),
            ("Luffy Leader Parallel OP01-003 JPN Mint", "ja"),
            ("One Piece Nami OP01-016 ITA", "it"),
            ("One Piece Shanks manga rare eng swirl", "en"),
            ("One Piece Zoro KOR promo", "ko"),
        ]
        for titre, langue in cas:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))
                self.assertEqual(detect_language(titre).language, langue)

    def test_carte_anglaise_au_vocabulaire_de_collectionneur(self):
        """Sans nom traduit pour trancher, c'est le vocabulaire qui doit
        trahir la carte anglaise. Un seul mot ne suffit pas, plusieurs oui."""
        titre = "Monkey D. Luffy OP01-120 Original Trading Card - Near Mint"
        self.assertTrue(looks_non_french(titre))
        self.assertEqual(detect_language(titre).language, "en")

    def test_vocabulaire_de_jeu_ecrit_a_l_anglaise(self):
        """« alternate art », « parallel », « starter deck » : des termes que
        le vendeur francais ecrit autrement (alternative, parallele, deck de
        depart)."""
        for titre in [
            "One Piece Zoro alternate art parallel",
            "One Piece starter deck sealed",
        ]:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))
                self.assertEqual(detect_language(titre).language, "en")

    def test_racine_de_langue_declinee(self):
        """Les declarations de langue doivent matcher en PREFIXE : sans ca,
        "japan" ne trouve pas "japanese" et l'annonce passe au travers."""
        for titre in [
            "One Piece Luffy OP01-120 japanese",
            "Zoro OP01-025 japanese promo",
            "Carta One Piece italiano",
            "One Piece Sanji germany edition",
        ]:
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))

    def test_raison_expliquee(self):
        """Une annonce ecartee doit pouvoir etre expliquee, sinon elle
        disparait du dashboard sans que personne ne sache pourquoi."""
        verdict = detect_language("One Piece Karte Ruffy Sammelkarte")
        self.assertFalse(verdict.is_french)
        self.assertTrue(verdict.reasons)
        self.assertIn("karte", verdict.reasons[0])


class TestLimiteConnueDuFiltre(unittest.TestCase):
    """Ce que le filtre ne sait PAS faire sur One Piece, affirme ici pour
    que personne ne suppose le contraire plus tard.

    Sur un jeu aux noms traduits, un titre anglais muet se repere au nom
    lui-meme. One Piece ne traduit pas ses personnages : rien, dans
    « Monkey D. Luffy OP01-120 », ne dit la langue de la carte. Ces
    annonces-la passent, et c'est irreductible sur le texte seul.
    """

    def test_titre_anglais_muet_passe(self):
        for titre in [
            "Monkey D. Luffy OP01-120",
            "Roronoa Zoro OP01-025 Super Rare",
            "One Piece Card Game Nami OP01-016",
        ]:
            with self.subTest(titre=titre):
                self.assertFalse(
                    looks_non_french(titre),
                    "Si ce test se met a echouer, c'est que le filtre s'est "
                    "durci : verifier qu'il n'ecarte pas des annonces "
                    "francaises au passage.",
                )


class TestAnnoncesFrancaisesGardees(unittest.TestCase):
    def test_titres_francais_ordinaires(self):
        for titre in [
            "Carte One Piece Monkey D. Luffy OP01-120 Secret Rare FR",
            "Carte One Piece Roronoa Zoro OP01-025 - Romance Dawn",
            "Beau Lot de 10 cartes One Piece Neuves Fr",
            "Carte One Piece Nami OP01-016 état correct",
            "Carte en très bon état de collection",
        ]:
            with self.subTest(titre=titre):
                self.assertFalse(looks_non_french(titre), titre)

    def test_mention_francaise_explicite_l_emporte(self):
        """Elle desarme meme un marqueur etranger fort : un vendeur qui
        ecrit "carte francaise" dans un titre bilingue vend la francaise."""
        self.assertFalse(looks_non_french("One Piece Luffy carte française VF"))
        self.assertFalse(
            looks_non_french("One Piece Zoro carta collezione - carte française")
        )

    def test_un_seul_mot_anglais_ne_suffit_pas(self):
        """"card", "holo", "original" sont employes par des vendeurs
        francais : un seul de ces mots ne doit rien declencher."""
        self.assertFalse(looks_non_french("Carte One Piece Luffy card promo jumbo"))
        self.assertFalse(looks_non_french("One Piece Sanji OP01-013 – Near Mint – FR"))

    def test_vocabulaire_francais_desarme_les_signaux_faibles(self):
        """Deux mots anglais suffiraient, mais le vocabulaire de vendeur
        francais a cote rend l'annonce francaise beaucoup plus probable."""
        self.assertFalse(
            looks_non_french(
                "Carte One Piece Luffy original trading card - envoi soigné, état neuf"
            )
        )

    def test_sigles_ambigus_en_francais_ignores(self):
        """"EN", "DE", "IT", "US" sont des mots francais ordinaires : ils ne
        doivent jamais compter comme sigles de langue, sinon "lot DE 10
        cartes" disparait du dashboard."""
        self.assertFalse(looks_non_french("Carte EN très bon état de collection"))
        self.assertFalse(looks_non_french("Lot DE 10 cartes One Piece Neuves Fr"))
        self.assertFalse(looks_non_french("Luffy IT OP01-120"))

    def test_titre_minimal(self):
        self.assertFalse(looks_non_french("Carte One Piece"))
        self.assertFalse(looks_non_french("One Piece"))


class TestRetroCompatibilite(unittest.TestCase):
    """La detection de base doit continuer de fonctionner a l'identique."""

    def test_declaration_explicite(self):
        self.assertTrue(looks_non_french("One Piece Kaido carte anglaise rare"))
        self.assertTrue(looks_non_french("Luffy version japonaise"))

    def test_alphabet_non_latin(self):
        self.assertTrue(looks_non_french("ルフィ 美品"))
        self.assertTrue(looks_non_french("원피스 카드"))

    def test_jeton_court(self):
        self.assertTrue(looks_non_french("Luffy JP Romance Dawn"))
        self.assertFalse(looks_non_french("carte enjpolie fictive"))

    def test_entrees_vides(self):
        self.assertFalse(looks_non_french(None, "", None))

    def test_description_aussi_analysee(self):
        self.assertTrue(looks_non_french("Kaido", "État japonais, très bon état"))



class TestSiglesEnCapitales(unittest.TestCase):
    """« EN » et « US » ecrits en capitales par le vendeur.

    Releves sur Vinted le 25/10/2026, depuis le poste de l'utilisateur, ces
    deux titres passaient pour francais et entraient dans le radar avec un
    score — alors qu'une carte anglaise ne vaut pas le prix d'une francaise.
    En minuscules, « en » est une preposition ordinaire : c'est la CASSE qui
    porte l'information.
    """

    def test_les_titres_reels_sont_ecartes(self):
        for titre in ("Carte one piece Katakuri op03-099 alt art EN psa 10",
                      "Buggy SP Wanted US"):
            with self.subTest(titre=titre):
                self.assertTrue(looks_non_french(titre))
                self.assertEqual(detect_language(titre).language, "en")

    def test_un_titre_court_avec_code_de_carte(self):
        """Le code « ST01 » est en capitales par nature : il ne doit pas
        faire passer un titre court pour un titre ecrit tout en capitales."""
        self.assertTrue(looks_non_french("Zoro ST01-001 EN"))

    def test_la_preposition_reste_francaise(self):
        for titre in ("Carte en très bon état de collection",
                      "Luffy OP01-120 EN BON ÉTAT",
                      "Portgas D. Ace OP02-013 SR EN parfait état",
                      "Ener OP15-118 SEC en français"):
            with self.subTest(titre=titre):
                self.assertFalse(looks_non_french(titre))

    def test_un_titre_tout_en_capitales_ne_dit_rien_de_sa_casse(self):
        """Un faux positif coute plus qu'un faux negatif : on n'ecarte pas
        une annonce francaise sur un indice qu'on ne peut pas lire."""
        for titre in ("LUFFY OP01-120 EN TRES BON ETAT",
                      "CARTE ONE PIECE SHANKS US"):
            with self.subTest(titre=titre):
                self.assertFalse(looks_non_french(titre))

    def test_un_titre_francais_du_releve_reste_francais(self):
        self.assertFalse(looks_non_french("Monkey D. Luffy – SP EB02-061 | One Piece"))


if __name__ == "__main__":
    unittest.main()
