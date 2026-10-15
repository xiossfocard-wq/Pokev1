"""
Tests du rapprochement annonce -> carte (services/price_index.py).

L'index de test reproduit les pieges propres a One Piece :

- un meme personnage porte plusieurs cartes a des prix sans rapport
  (« Monkey D. Luffy » de 2,40 € a 412 €) ;
- un LEADER et un PERSONNAGE du meme nom sont deux cartes differentes :
  confondre les deux, c'est afficher un prix faux en confiance ;
- les initiales (« Monkey D. Luffy », « Portgas D. Ace ») : le « D. »
  d'une seule lettre etait purement efface par le filtre de bruit, ce qui
  rendait ces noms introuvables ;
- le zero-padding du code varie entre la source et ce qu'ecrit le vendeur
  (« OP01-004 » contre « OP01-4 »).

Les titres sont construits sur les tournures reellement observees en
production (« Carte One Piece <nom> <code> <rarete> FR », les titres tout
en minuscules, les lots generiques) : c'est la FORME qui est testee ici,
pas le nom des personnages.
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
            # Le meme personnage, trois cartes, trois prix sans rapport :
            # c'est le piege principal du rapprochement par nom seul.
            card("monkey-d-luffy", "Monkey D. Luffy", "OP01-120", 412.0, "Romance Dawn"),
            card("monkey-d-luffy", "Monkey D. Luffy", "OP05-119", 18.00, "Awakening"),
            card("monkey-d-luffy", "Monkey D. Luffy", "ST01-001", 2.40, "Deck Chapeau de Paille"),
            # Un LEADER du meme nom : carte differente, prix different.
            card("monkey-d-luffy-leader", "Monkey D. Luffy Leader", "OP01-003", 25.00, "Romance Dawn"),
            # Noms a initiale et noms composes.
            card("portgas-d-ace", "Portgas D. Ace", "OP02-013", 88.00, "Paramount War"),
            card("charlotte-katakuri", "Charlotte Katakuri", "OP02-074", 73.00, "Paramount War"),
            card("edward-newgate", "Edward Newgate", "OP02-001", 210.0, "Paramount War"),
            card("donquixote-doflamingo", "Donquixote Doflamingo", "OP04-040", 47.00, "Kingdoms of Intrigue"),
            card("roronoa-zoro", "Roronoa Zoro", "OP01-025", 188.0, "Romance Dawn"),
            # Code a zero-padding, pour le cas « OP01-4 ».
            card("nami", "Nami", "OP01-004", 3.40, "Romance Dawn"),
        ]

    def match(self, titre):
        return find_price_for_listing(self.db, titre)


class TestNomsAInitialeEtComposes(PriceMatchingTestCase):
    """Le « D. » d'une seule lettre etait efface avec la ponctuation : tous
    les noms de ce moule — et ils sont nombreux dans One Piece — etaient
    introuvables."""

    def test_initiale_au_milieu_du_nom(self):
        m = self.match("Carte One Piece Portgas D. Ace OP02-013 super rare FR")
        self.assertIsNotNone(m, "un nom a initiale doit etre retrouve")
        self.assertEqual(m.row.display_name, "Portgas D. Ace")

    def test_initiale_sans_point(self):
        """Beaucoup de vendeurs ecrivent « Monkey D Luffy » sans le point."""
        m = self.match("carte one piece monkey d luffy")
        self.assertIsNotNone(m)
        self.assertEqual(m.row.display_name, "Monkey D. Luffy")

    def test_nom_compose_en_deux_mots(self):
        m = self.match("Carte One Piece Charlotte Katakuri OP02-074")
        self.assertEqual(m.row.display_name, "Charlotte Katakuri")

    def test_autre_nom_compose(self):
        m = self.match("Carte One Piece Donquixote Doflamingo OP04-040 SR")
        self.assertEqual(m.row.display_name, "Donquixote Doflamingo")


class TestVariantes(PriceMatchingTestCase):
    def test_leader_non_confondu_avec_le_personnage(self):
        """Le bug le plus couteux : un Leader et un Personnage du meme nom
        sont deux cartes. Tant que « leader » etait traite comme du bruit,
        le candidat « monkey-d-luffy-leader » n'etait jamais construit et
        l'annonce recevait le prix d'une autre carte."""
        m = self.match("Carte One Piece Monkey D. Luffy Leader OP01-003")
        self.assertIsNotNone(m)
        self.assertEqual(m.row.display_name, "Monkey D. Luffy Leader")
        self.assertEqual(m.row.price_eur, 25.00)

    def test_leader_retrouve_sans_code(self):
        m = self.match("Carte One Piece Monkey D. Luffy Leader")
        self.assertEqual(m.row.display_name, "Monkey D. Luffy Leader")

    def test_variante_absente_de_l_index_est_signalee(self):
        """« Monkey D. Luffy Manga » n'existe pas dans l'index : on retombe
        sur une autre carte, et il faut le dire au lieu d'afficher un prix
        sur."""
        m = self.match("Carte One Piece Monkey D. Luffy Manga")
        self.assertIsNotNone(m)
        self.assertIsNotNone(m.warning, "un rabattement de variante doit etre signale")
        self.assertIn("MANGA", m.warning)
        self.assertEqual(m.confidence, "low")
        self.assertTrue(m.is_uncertain)

    def test_pas_d_alerte_quand_la_variante_correspond(self):
        m = self.match("Carte One Piece Monkey D. Luffy Leader OP01-003")
        self.assertIsNone(m.warning)


class TestCodeCarte(PriceMatchingTestCase):
    def test_code_explicite_departage_les_homonymes(self):
        """OP01-120 = le Luffy a 412 €, pas la mediane des trois."""
        m = self.match("Carte One Piece Monkey D. Luffy OP01-120 Secret Rare")
        self.assertEqual(m.confidence, "high")
        self.assertEqual(m.row.price_eur, 412.0)

    def test_un_autre_code_designe_une_autre_carte(self):
        m = self.match("Carte One Piece Monkey D. Luffy ST01-001 neuve")
        self.assertEqual(m.confidence, "high")
        self.assertEqual(m.row.price_eur, 2.40)

    def test_separateur_indifferent(self):
        """Le vendeur ecrit « OP01 025 », la source « OP01-025 »."""
        for titre in ["carte one piece zoro OP01-025",
                      "carte one piece zoro OP01 025",
                      "carte one piece zoro op01-025"]:
            with self.subTest(titre=titre):
                m = self.match(titre)
                self.assertEqual(m.confidence, "high")
                self.assertEqual(m.row.display_name, "Roronoa Zoro")

    def test_code_non_padde_dans_le_titre(self):
        """« OP01-4 » et « OP01-004 » designent la meme carte."""
        m = self.match("Carte One Piece Nami OP01-4")
        self.assertEqual(m.confidence, "high")
        self.assertEqual(m.row.display_name, "Nami")

    def test_mot_du_titre_pris_pour_un_code_ne_passe_plus(self):
        m = self.match("Carte One Piece Charlotte Katakuri 062 162 Holo")
        if m is not None:
            self.assertNotIn("code carte", m.reason)


class TestFautesDeFrappe(PriceMatchingTestCase):
    def test_faute_de_frappe_rattrapee(self):
        m = self.match("carte one piece roronoa zorro holo")
        self.assertIsNotNone(m, "une faute d'une lettre doit etre rattrapee")
        self.assertIn("faute de frappe", m.reason)
        self.assertEqual(m.confidence, "low")

    def test_mot_trop_different_non_rattrape(self):
        """On prefere ne rien trouver plutot que d'inventer : « Chopper »
        n'est pas une faute de frappe de « Nami »."""
        self.assertIsNone(self.match("carte one piece Chopper holo"))


class TestIncertitude(PriceMatchingTestCase):
    def test_homonymes_signales_comme_incertains(self):
        m = self.match("carte one piece monkey d luffy")
        self.assertEqual(m.confidence, "low")
        self.assertEqual(len(m.candidates), 3)
        self.assertGreater(m.price_spread_eur, 400)
        self.assertTrue(m.is_uncertain)

    def test_details_exposes_au_frontend(self):
        detail = self.match("carte one piece monkey d luffy").to_dict()
        for cle in ("candidates_count", "price_spread_eur", "uncertain", "warning"):
            self.assertIn(cle, detail)
        self.assertEqual(detail["candidates_count"], 3)
        self.assertTrue(detail["uncertain"])

    def test_match_sur_code_non_incertain(self):
        m = self.match("Carte One Piece Monkey D. Luffy OP01-120")
        self.assertFalse(m.is_uncertain)


class TestAbsenceDeMatch(PriceMatchingTestCase):
    def test_titre_vide(self):
        self.assertIsNone(self.match(""))

    def test_titre_sans_nom_de_carte(self):
        self.assertIsNone(self.match("Carte One Piece"))

    def test_lot_generique(self):
        self.assertIsNone(
            self.match("Beau Lot de 10 cartes One Piece Romance Dawn Neuves Fr")
        )


class TestNomUsuel(PriceMatchingTestCase):
    """Le vendeur ecrit « Luffy », l'index contient « Monkey D. Luffy ».

    C'etait le plus gros trou du rapprochement sur One Piece : le nom
    complet n'apparait presque jamais dans un titre Vinted, donc la
    majorite des annonces ne trouvaient AUCUN prix de reference des que le
    code carte manquait au titre.
    """

    def test_nom_usuel_unique(self):
        m = self.match("Carte One Piece Katakuri super rare")
        self.assertIsNotNone(m, "le nom usuel doit retrouver le nom complet")
        self.assertEqual(m.row.display_name, "Charlotte Katakuri")
        self.assertEqual(m.confidence, "medium")
        self.assertIn("nom usuel", m.reason)

    def test_nom_usuel_court(self):
        """« Ace », « Law » : trois lettres, mais ce sont de vrais noms
        usuels du jeu et ils doivent passer."""
        for titre, attendu in [
            ("Carte One Piece Ace tres bon etat", "Portgas D. Ace"),
            ("Carte One Piece Doflamingo neuve", "Donquixote Doflamingo"),
            ("Carte One Piece Newgate", "Edward Newgate"),
        ]:
            with self.subTest(titre=titre):
                m = self.match(titre)
                self.assertIsNotNone(m, titre)
                self.assertEqual(m.row.display_name, attendu)

    def test_nom_usuel_ambigu_reste_incertain(self):
        """Trois cartes finissent par « luffy » a des prix sans rapport :
        on rend la mediane mais on le DIT, sinon l'utilisateur lit un prix
        sur la foi d'un nom qui n'identifie pas la carte."""
        m = self.match("Carte One Piece Luffy secret rare FR")
        self.assertIsNotNone(m)
        self.assertEqual(m.confidence, "low")
        self.assertEqual(len(m.candidates), 3)
        self.assertTrue(m.is_uncertain)
        self.assertGreater(m.price_spread_eur, 400)

    def test_le_leader_garde_son_identite(self):
        """« Luffy Leader » doit tomber sur la carte Leader, pas sur le
        Personnage : ce sont deux cartes et deux prix."""
        m = self.match("Carte One Piece Luffy Leader")
        self.assertEqual(m.row.display_name, "Monkey D. Luffy Leader")
        self.assertEqual(m.row.price_eur, 25.00)

    def test_luffy_seul_ne_prend_pas_le_leader(self):
        """L'inverse : « Luffy » tout court ne doit PAS ramasser le Leader,
        dont le nom ne se termine pas par « luffy »."""
        m = self.match("Carte One Piece Luffy secret rare")
        for candidat in m.candidates:
            self.assertNotIn("Leader", candidat.display_name)

    def test_le_code_reste_prioritaire(self):
        """Le nom usuel ne doit jamais passer devant un code explicite :
        celui-ci identifie la carte, le nom non."""
        m = self.match("Carte One Piece Luffy OP01-120 SR")
        self.assertEqual(m.confidence, "high")
        self.assertEqual(m.row.price_eur, 412.0)

    def test_le_nom_complet_reste_prioritaire(self):
        m = self.match("Carte One Piece Monkey D. Luffy")
        self.assertIn("nom 'monkey-d-luffy'", m.reason)
        self.assertNotIn("nom usuel", m.reason)

    def test_mot_sans_rapport_ne_rapproche_rien(self):
        self.assertIsNone(self.match("Carte One Piece Chopper holo"))


class TestNomUsuelGardeFous(unittest.TestCase):
    """Les deux garde-fous qui empechent ce rattrapage de devenir dangereux."""

    def _index(self, cartes):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()
        db.add_all(cartes)
        db.commit()
        price_index._slug_cache = []
        price_index._slug_cache_at = None
        return db

    def tearDown(self):
        price_index._slug_cache = []
        price_index._slug_cache_at = None

    def test_mots_entiers_seulement(self):
        """« ace » ne doit pas attraper « menace » : la correspondance se
        fait sur des mots entiers, jamais sur une fin de chaine."""
        db = self._index([
            card("menace-fantome", "Menace Fantome", "OP09-001", 5.0),
        ])
        self.assertIsNone(find_price_for_listing(db, "Carte One Piece Ace neuve"))
        db.close()

    def test_trop_de_cartes_aucun_prix(self):
        """Quand trop de cartes finissent par le meme nom, la mediane ne
        veut plus rien dire : mieux vaut ne rendre aucun prix."""
        beaucoup = [
            card(f"personnage-{i}-commun", f"Personnage {i} Commun",
                 f"OP01-{i:03d}", float(i * 30))
            for i in range(1, 15)
        ]
        db = self._index(beaucoup)
        self.assertIsNone(find_price_for_listing(db, "Carte One Piece commun neuve"))
        db.close()

    def test_juste_en_dessous_du_plafond_rapproche(self):
        """Le garde-fou ne doit pas etre si serre qu'il bloque un cas
        normal : sous le plafond, le rapprochement se fait."""
        quelques = [
            card(f"personnage-{i}-commun", f"Personnage {i} Commun",
                 f"OP01-{i:03d}", float(i * 30))
            for i in range(1, 4)
        ]
        db = self._index(quelques)
        m = find_price_for_listing(db, "Carte One Piece commun neuve")
        self.assertIsNotNone(m)
        self.assertEqual(len(m.candidates), 3)
        db.close()


class TestSeparateurDeCodeCarte(unittest.TestCase):
    """Regression trouvee en basculant vers One Piece.

    Le separateur du code depend de la source : One Piece ecrit
    « OP01-120 » avec un tiret, d'autres catalogues separent par une
    espace, et les vendeurs melangent les deux. Le parseur de titre, lui,
    normalise en espace.

    Comparer les chaines telles quelles faisait echouer le rapprochement
    par code sur TOUTES les cartes, en silence : le prix retombait sur un
    rapprochement par nom, bien moins sur, sans que rien ne le signale.
    """

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        price_index._slug_cache = []
        price_index._slug_cache_at = None
        self.db.add(MarketCardPrice(
            name_slug="monkey-d-luffy", display_name="Monkey D. Luffy",
            card_code="OP01-120", price_eur=419.31, series_name="Romance Dawn",
            source="zebradex",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_le_tiret_du_titre_retrouve_le_tiret_de_l_index(self):
        match = find_price_for_listing(self.db, "Carte One Piece Luffy OP01-120 SR")
        self.assertIsNotNone(match, "le code avec tiret n'a pas ete rapproche")
        self.assertEqual(match.confidence, "high")
        self.assertEqual(match.row.display_name, "Monkey D. Luffy")

    def test_l_espace_du_titre_retrouve_le_tiret_de_l_index(self):
        """Un vendeur qui ecrit « OP01 120 » designe la meme carte."""
        match = find_price_for_listing(self.db, "Carte One Piece Luffy OP01 120")
        self.assertIsNotNone(match)
        self.assertEqual(match.confidence, "high")

    def test_la_casse_n_a_pas_d_importance(self):
        match = find_price_for_listing(self.db, "carte one piece luffy op01-120")
        self.assertIsNotNone(match)
        self.assertEqual(match.confidence, "high")

    def test_un_code_d_une_autre_carte_ne_rapproche_pas(self):
        """Le garde-fou : normaliser le separateur ne doit pas rendre deux
        codes differents equivalents."""
        match = find_price_for_listing(self.db, "Carte One Piece Zoro OP01-025")
        if match is not None:
            self.assertNotEqual(match.confidence, "high")


if __name__ == "__main__":
    unittest.main()
