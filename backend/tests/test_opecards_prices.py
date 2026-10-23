"""
Tests des prix de référence (collectors/opecards_prices.py) et de leur
application au catalogue (services/catalog_prices.py).

Ces tests tournent contre un EXTRAIT REEL d'OPECards.fr, relevé le
22/10/2026 et conservé dans fixtures/opecards_op15_prix.html.

Ce qui est vérifié ici tient en une phrase : qu'un prix atterrisse sur LA
BONNE carte. C'est la seule chose qui compte, parce qu'une erreur de
rapprochement ne se voit pas — elle produit un chiffre plausible, une marge
plausible, et une « bonne affaire » qui n'existe pas.

LE CAS QUI A CHANGE LE MODELE
-----------------------------
Trois entrées portent le code OP15-118-SEC :

    Ener                10,50 €
    Ener (Version 2)    22,00 €
    Ener (Version 3)   695,00 €

Le catalogue regroupait jusque-là toutes les illustrations alternatives
d'un code sous une seule fiche. Il aurait annoncé 22 € pour une carte qui
en vaut 695.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors.cardlist_fr import CarteFR
from app.collectors.opecards_prices import (
    ClientOPECards, analyser_page, derniere_page, rang_de_version,
    separer_code_et_rarete, series_francaises,
)
from app.database import Base
from app.models import MarketCardPrice
from app.services.catalog_fr import appliquer_noms_francais
from app.services.catalog_prices import appliquer_prix

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "opecards_op15_prix.html")


def page() -> str:
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


def carte_fr(code, nom, rang=0, rarete="SEC"):
    return CarteFR(code, nom, rarete, "PERSONNAGE", "Aventure (OP-15)", None, rang)


class TestSeparationCodeRarete(unittest.TestCase):
    """Le site colle le code et la rarete dans un seul libelle."""

    def test_rarete_detachee(self):
        self.assertEqual(separer_code_et_rarete("OP15-118-SEC"), ("OP15-118", "SEC"))
        self.assertEqual(separer_code_et_rarete("OP15-086-SR"), ("OP15-086", "SR"))

    def test_rarete_d_une_seule_lettre(self):
        """« -R » ne doit pas etre confondu avec la fin du numero."""
        self.assertEqual(separer_code_et_rarete("OP15-116-R"), ("OP15-116", "R"))
        self.assertEqual(separer_code_et_rarete("OP15-022-L"), ("OP15-022", "L"))

    def test_rarete_avec_ponctuation(self):
        self.assertEqual(separer_code_et_rarete("ST01-001-DON!!"),
                         ("ST01-001", "DON!!"))

    def test_sans_rarete_le_code_passe_entier(self):
        """Couper au dernier tiret donnerait « OP15 » / « 118 »."""
        self.assertEqual(separer_code_et_rarete("OP15-118"), ("OP15-118", None))

    def test_vide(self):
        self.assertEqual(separer_code_et_rarete(""), (None, None))


class TestRangDeVersion(unittest.TestCase):
    def test_la_version_2_est_la_premiere_alternative(self):
        """La numerotation rendue est celle des ALTERNATIVES, pour
        correspondre aux suffixes « _p1 », « _p2 » de la liste officielle."""
        self.assertEqual(rang_de_version("Ener (Version 2)"), ("Ener", 1))
        self.assertEqual(rang_de_version("Ener (Version 3)"), ("Ener", 2))

    def test_sans_version_c_est_l_ordinaire(self):
        self.assertEqual(rang_de_version("Ener"), ("Ener", 0))

    def test_une_parenthese_qui_n_est_pas_une_version_reste_dans_le_nom(self):
        nom, rang = rang_de_version("Capone \"Gang\" Bege")
        self.assertEqual(rang, 0)
        self.assertIn("Gang", nom)


class TestAnalysePage(unittest.TestCase):
    def setUp(self):
        self.cartes = analyser_page(page())
        self.par_cle = {(c.card_code, c.rang_variante): c for c in self.cartes}

    def test_les_trois_versions_ont_des_prix_distincts(self):
        """LE cas qui justifie tout le reste : 66 fois l'ecart."""
        self.assertEqual(self.par_cle[("OP15-118", 0)].price_eur, 10.50)
        self.assertEqual(self.par_cle[("OP15-118", 1)].price_eur, 22.00)
        self.assertEqual(self.par_cle[("OP15-118", 2)].price_eur, 695.00)

    def test_le_nom_ne_garde_pas_la_mention_de_version(self):
        """Le rang est une donnee a part, pas un bout de chaine."""
        for rang in (0, 1, 2):
            self.assertEqual(self.par_cle[("OP15-118", rang)].display_name, "Ener")

    def test_une_baisse_est_negative(self):
        """Le signe vient de la CLASSE CSS (text-success = baisse) et non du
        texte : la classe ne depend pas du formatage du gabarit."""
        self.assertEqual(self.par_cle[("OP15-086", 1)].variation_eur, -3.00)

    def test_une_hausse_est_positive(self):
        self.assertEqual(self.par_cle[("OP15-113", 1)].variation_eur, 0.10)

    def test_pas_de_variation_quand_il_n_y_en_a_pas(self):
        self.assertIsNone(self.par_cle[("OP15-118", 0)].variation_eur)

    def test_rarete_recuperee(self):
        self.assertEqual(self.par_cle[("OP15-118", 0)].rarity, "SEC")
        self.assertEqual(self.par_cle[("OP15-116", 1)].rarity, "R")

    def test_accents_du_nom_intacts(self):
        self.assertEqual(self.par_cle[("OP15-116", 1)].display_name,
                         "Gum Gum Carabine Dorée")

    def test_image_et_lien(self):
        carte = self.par_cle[("OP15-118", 2)]
        self.assertTrue(carte.image_url.startswith("https://static.opecards.fr/"))
        self.assertTrue(carte.detail_url.endswith("/cards/op15-118-sec-version-3-ener"))

    def test_page_vide_ne_plante_pas(self):
        self.assertEqual(analyser_page("<html><body></body></html>"), [])


class TestSeriesEtPagination(unittest.TestCase):
    def test_seul_le_groupe_francais_est_retenu(self):
        """Le menu liste aussi les series japonaises et anglaises. Les
        prendre inscrirait au catalogue des cartes jamais imprimees en
        francais."""
        series = series_francaises(page())
        libelles = " | ".join(series.values())
        self.assertIn("OP15", libelles)
        self.assertNotIn("Romance Dawn", libelles)   # OP01, anglais et japonais
        self.assertNotIn("Two Legends", libelles)    # OP08, anglais seul

    def test_le_jeu_francais_commence_a_op09(self):
        """Constat, pas supposition : le groupe francais ne contient ni OP01
        ni OP08. Le catalogue ne doit donc pas promettre ces series."""
        libelles = " ".join(series_francaises(page()).values())
        self.assertIn("OP09", libelles)
        self.assertNotIn("OP01 ", libelles)

    def test_derniere_page(self):
        self.assertEqual(derniere_page(page()), 7)

    def test_une_page_sans_pagination_vaut_une_page(self):
        self.assertEqual(derniere_page("<html></html>"), 1)


class TestConstructionDesUrl(unittest.TestCase):
    def setUp(self):
        self.client = ClientOPECards()

    def test_premiere_page_sans_numero(self):
        self.assertIn("/cards?", self.client.url(page=1, serie="770"))

    def test_pages_suivantes_numerotees(self):
        self.assertIn("/cards/3?", self.client.url(page=3, serie="770"))

    def test_langue_et_serie_transmises(self):
        url = self.client.url(page=1, serie="770")
        self.assertIn("serie=770", url)
        self.assertIn("language=FR", url)


class TestApplicationDesPrix(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=moteur)
        self.db = sessionmaker(bind=moteur)()
        # Le catalogue officiel : trois impressions distinctes du meme code.
        appliquer_noms_francais(self.db, [
            carte_fr("OP15-118", "Ener", 0),
            carte_fr("OP15-118", "Ener (Parallèle 1)", 1),
            carte_fr("OP15-118", "Ener (Parallèle 2)", 2),
            carte_fr("OP15-086", "Nami (Parallèle 1)", 1, "SR"),
        ])

    def tearDown(self):
        self.db.close()

    def fiche(self, code, rang=0):
        from app.collectors.cardlist_fr import rang_de_parallele
        for l in self.db.query(MarketCardPrice).filter_by(card_code=code).all():
            if rang_de_parallele(l.name_slug) == rang:
                return l
        return None

    def appliquer(self):
        return appliquer_prix(self.db, analyser_page(page()))

    def test_chaque_version_recoit_SON_prix(self):
        """Le test qui compte. Si le rapprochement se trompe de variante, la
        carte a 695 € s'affiche a 22 € — et l'erreur ne se voit pas, puisque
        22 € est un prix parfaitement plausible."""
        self.appliquer()
        self.assertEqual(self.fiche("OP15-118", 0).price_eur, 10.50)
        self.assertEqual(self.fiche("OP15-118", 1).price_eur, 22.00)
        self.assertEqual(self.fiche("OP15-118", 2).price_eur, 695.00)

    def test_la_variation_est_enregistree(self):
        self.appliquer()
        self.assertEqual(self.fiche("OP15-086", 1).variation_7d_eur, -3.00)

    def test_une_carte_absente_du_catalogue_n_est_pas_creee(self):
        """Cette source dit ce que valent les cartes, pas lesquelles
        existent. Creer ici donnerait une fiche sans serie ni visuel."""
        rapport = self.appliquer()
        self.assertGreater(rapport["sans_fiche"], 0)
        self.assertIsNone(self.fiche("OP15-113", 1))

    def test_le_reste_de_la_fiche_n_est_pas_touche(self):
        """Seuls le prix et sa variation sont ecrits ici."""
        avant = self.fiche("OP15-118", 2)
        nom, serie = avant.display_name, avant.series_name
        self.appliquer()
        apres = self.fiche("OP15-118", 2)
        self.assertEqual(apres.display_name, nom)
        self.assertEqual(apres.series_name, serie)

    def test_un_ecart_enorme_est_signale_pas_tu(self):
        """Un prix qui est multiplie par soixante est peut-etre reel — ces
        cartes bougent vite — mais c'est aussi la signature d'un
        rapprochement qui a derape. Une marge fausse ne se voit pas."""
        self.fiche("OP15-118", 2).price_eur = 10.0
        self.db.commit()
        rapport = self.appliquer()
        codes = {e["code"] for e in rapport["ecarts_suspects"]}
        self.assertIn("OP15-118", codes)

    def test_un_ecart_normal_n_est_pas_signale(self):
        self.fiche("OP15-118", 2).price_eur = 680.0
        self.db.commit()
        rapport = self.appliquer()
        self.assertEqual(rapport["ecarts_suspects"], [])

    def test_le_compte_des_cartes_encore_sans_prix_est_rendu(self):
        """« 4 chiffrees » ne dit pas si le catalogue est couvert."""
        rapport = self.appliquer()
        self.assertEqual(rapport["sans_prix_restantes"], 0)

    def test_relancer_ne_change_plus_rien(self):
        self.appliquer()
        second = self.appliquer()
        self.assertEqual(second["chiffrees"], 0)
        self.assertGreater(second["inchangees"], 0)

    def test_les_changements_sont_montres(self):
        rapport = self.appliquer()
        self.assertTrue(any(e["apres"] == 695.00 for e in rapport["exemples"]))



class TestSeriesFrancaisesConnues(unittest.TestCase):
    class SessionEnPanne:
        def __init__(self):
            self.headers = {}

        def get(self, *a, **k):
            raise OSError("reseau coupe")

    def test_le_repli_rend_la_liste_gravee(self):
        from app.collectors.opecards_prices import SERIES_FR_CONNUES
        series = ClientOPECards(session=self.SessionEnPanne()).series()
        self.assertEqual(series, dict(SERIES_FR_CONNUES))

    def test_aucune_serie_japonaise_ou_anglaise_gravee(self):
        """Les prendre inscrirait au catalogue des prix de cartes jamais
        imprimees en francais."""
        from app.collectors.opecards_prices import SERIES_FR_CONNUES
        libelles = " | ".join(SERIES_FR_CONNUES.values())
        self.assertNotIn("Romance Dawn", libelles)
        self.assertNotIn("Two Legends", libelles)
        self.assertNotIn("Starter Deck", libelles)

    def test_les_deux_sources_couvrent_les_memes_series(self):
        """Une serie chiffree sans fiche, ou une fiche jamais chiffree,
        viendrait d'un desaccord entre les deux listes."""
        import re
        from app.collectors.cardlist_fr import SERIES_CONNUES
        from app.collectors.opecards_prices import SERIES_FR_CONNUES

        def code_principal(libelle):
            """Le PREMIER code du libelle.

            Le site officiel libelle certains produits groupes
            « [OP15-EB04] » : c'est un seul produit, pas deux series. Lire
            les deux codes ferait croire a une serie EB04 separee, absente
            d'OPECards — un faux ecart.
            """
            trouve = re.search(r"\b((?:OP|ST|EB|PRB)-?\d{2})\b", libelle)
            return trouve.group(1).replace("-", "") if trouve else None

        officielles = {c for c in map(code_principal, SERIES_CONNUES.values()) if c}
        prix = {c for c in map(code_principal, SERIES_FR_CONNUES.values()) if c}

        manquantes = officielles - prix
        self.assertEqual(manquantes, set(),
                         f"series sans source de prix : {sorted(manquantes)}")


class TestDeuxPrixPourUneMemeFiche(unittest.TestCase):
    """Le défaut que ces tests verrouillent.

    Un même code désigne plusieurs cartes : la commune à 12 € et son
    illustration manga à 850. Quand la source des prix les présente sous le
    même nom — donc sous le même rang — les deux prix visent la même fiche,
    et la dernière lue écrasait la première. Le prix qui survivait était
    celui que l'ordre de la page avait mis en dernier.

    Conséquence : la fiche de la commune héritait de 850 €. L'application
    annonçait alors une affaire en or sur une annonce à 30 €, et rien ne
    signalait l'erreur avant l'achat.
    """

    def setUp(self):
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.db.add(MarketCardPrice(
            card_code="OP17-022", display_name="Shanks", name_slug="shanks",
            rarity="C (Common)", price_eur=None))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def prix(self, montant, rarete):
        from app.collectors.opecards_prices import PrixCarte
        return PrixCarte(card_code="OP17-022", display_name="Shanks",
                         rang_variante=0, rarity=rarete, price_eur=montant,
                         variation_eur=None, image_url=None, detail_url=None)

    def retenu(self):
        return self.db.query(MarketCardPrice).filter_by(
            card_code="OP17-022").one().price_eur

    def test_la_rarete_ecarte_le_prix_d_une_autre_carte(self):
        """« C (Common) » et « SEC » ne sont pas la même carte, même sous le
        même code et le même nom."""
        rapport = appliquer_prix(self.db, [self.prix(850.0, "SEC"),
                                           self.prix(12.0, "C")])
        self.assertEqual(self.retenu(), 12.0)
        self.assertEqual(rapport["raretes_opposees"], 1)

    def test_l_ordre_de_la_page_ne_decide_plus(self):
        """La propriété qui compte : lire la page à l'envers doit donner le
        même prix. Sans elle, le résultat dépend d'un tri d'affichage."""
        rapport = appliquer_prix(self.db, [self.prix(12.0, "C"),
                                           self.prix(850.0, "SEC")])
        self.assertEqual(self.retenu(), 12.0)
        self.assertEqual(rapport["raretes_opposees"], 1)

    def test_sans_rarete_lisible_aucun_prix_n_est_retenu(self):
        """Retenir le plus bas semblait prudent. Appliqué plusieurs fois de
        suite, ça pousse le prix au plancher — 0,02 € pour une carte qui en
        vaut 600 — et ce chiffre retire la carte du radar aussi sûrement
        qu'une absence de prix, sans le dire.

        Une fiche sans prix, elle, se compte dans le bilan et se voit."""
        rapport = appliquer_prix(self.db, [self.prix(850.0, None),
                                           self.prix(12.0, None)])
        self.assertIsNone(self.retenu())
        self.assertEqual(len(rapport["conflits"]), 1)

    def test_un_prix_devenu_inconciliable_est_efface(self):
        """Le cas qui compte pour réparer l'existant : la fiche portait un
        prix écrit par un rapprochement fautif, et les candidatures ne
        permettent plus de le confirmer."""
        fiche = self.db.query(MarketCardPrice).filter_by(
            card_code="OP17-022").one()
        fiche.price_eur, fiche.variation_7d_eur = 0.75, -2.0
        self.db.commit()
        appliquer_prix(self.db, [self.prix(850.0, None), self.prix(12.0, None)])
        self.assertIsNone(self.retenu())
        self.assertIsNone(self.db.query(MarketCardPrice).filter_by(
            card_code="OP17-022").one().variation_7d_eur)

    def test_le_conflit_est_rendu_pas_tu(self):
        """Une protection qui joue en silence empêche de voir que la source
        a changé de forme."""
        rapport = appliquer_prix(self.db, [self.prix(12.0, None),
                                           self.prix(850.0, None)])
        self.assertEqual(rapport["conflits"][0]["montants"], [12.0, 850.0])

    def test_le_conflit_joint_l_etat_brut_des_candidatures(self):
        """Sans le nom et la rareté tels que la SOURCE les écrit, on ne peut
        que supposer pourquoi deux cartes se confondent. Avec, on le
        constate."""
        # La fiche n'a pas de rarete : le controle ne peut pas trancher, et
        # c'est exactement la situation ou l'etat brut est necessaire. Les
        # deux candidatures, elles, en portent une — ce qui dit que la
        # distinction existe a la source et manque au catalogue.
        fiche = self.db.query(MarketCardPrice).filter_by(
            card_code="OP17-022").one()
        fiche.rarity = None
        self.db.commit()
        rapport = appliquer_prix(self.db, [self.prix(850.0, "SEC"),
                                           self.prix(12.0, "C")])
        candidats = rapport["conflits"][0]["candidats"]
        self.assertEqual(candidats[0]["prix"], 850.0)
        self.assertEqual(candidats[0]["rarete"], "SEC")
        self.assertEqual(candidats[1]["rarete"], "C")
        self.assertIsNone(rapport["conflits"][0]["rarete_fiche"])

    def test_l_ecart_signale_compare_a_ce_qui_est_retenu(self):
        """Signaler un écart vers une valeur qu'on vient soi-même d'écarter
        enverrait vérifier un chiffre jamais appliqué."""
        fiche = self.db.query(MarketCardPrice).filter_by(
            card_code="OP17-022").one()
        fiche.price_eur = 12.0
        self.db.commit()
        rapport = appliquer_prix(self.db, [self.prix(850.0, "SEC"),
                                           self.prix(12.5, "C")])
        self.assertEqual(self.retenu(), 12.5)
        self.assertEqual(rapport["ecarts_suspects"], [])

    def test_un_rafraichissement_normal_passe(self):
        """Le garde-fou ne doit pas bloquer la mise à jour ordinaire d'un
        prix, sinon il gèle le catalogue."""
        rapport = appliquer_prix(self.db, [self.prix(12.5, "C")])
        self.assertEqual(self.retenu(), 12.5)
        self.assertEqual(rapport["chiffrees"], 1)
        self.assertEqual(rapport["raretes_opposees"], 0)
        self.assertEqual(rapport["conflits"], [])


class TestNormalisationDeLaRarete(unittest.TestCase):
    """Les deux sources ne notent pas la rareté pareil. Comparer les
    libellés bruts conclurait « différent » pour tout le catalogue — et
    écarterait donc la totalité des prix."""

    def test_les_deux_notations_se_rejoignent(self):
        from app.services.catalog_prices import code_rarete
        self.assertEqual(code_rarete("C (Common)"), code_rarete("C"))
        self.assertEqual(code_rarete("SEC (Secret Rare)"), code_rarete("sec"))
        self.assertEqual(code_rarete("SP CARD (Special)"), "SP")

    def test_une_rarete_illisible_ne_sert_pas_a_ecarter(self):
        """Rendre None plutôt que deviner : sinon une notation inconnue
        ferait rejeter des prix parfaitement bons."""
        from app.services.catalog_prices import code_rarete
        for vide in (None, "", "   ", "(Inconnue)"):
            self.assertIsNone(code_rarete(vide))


class TestBalayageDesPrixPerimes(unittest.TestCase):
    """Recharger ne suffit pas à réparer un mauvais rapprochement.

    Un prix écrit par erreur peut n'avoir plus aucune candidature
    légitime — plus rien ne vient donc l'écraser, et il reste en base
    indéfiniment. C'est exactement le chiffre qui invente une bonne
    affaire. Ce balayage est la seule chose qui l'enlève.
    """

    def setUp(self):
        from datetime import datetime, timedelta
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.veille = datetime.utcnow() - timedelta(days=1)
        self.debut = datetime.utcnow() - timedelta(minutes=5)
        self.db.add_all([
            # Mal rapprochée hier, plus aucune candidature aujourd'hui.
            MarketCardPrice(card_code="OP17-022", display_name="Shanks",
                            name_slug="shanks", price_eur=850.0,
                            source="opecards", updated_at=self.veille),
            # Reconfirmée pendant le passage.
            MarketCardPrice(card_code="OP17-005", display_name="Kaido",
                            name_slug="kaido", price_eur=7.0,
                            source="opecards", updated_at=datetime.utcnow()),
            # Une AUTRE source : ce balayage n'a pas à en décider.
            MarketCardPrice(card_code="OP17-099", display_name="Nami",
                            name_slug="nami", price_eur=42.0,
                            source="catalogue", updated_at=self.veille),
            # Jamais chiffrée : rien à oublier, et rien ne doit casser.
            MarketCardPrice(card_code="OP17-100", display_name="Usopp",
                            name_slug="usopp", price_eur=None,
                            source="opecards", updated_at=self.veille),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def balayer(self):
        from app.services.catalog_prices import oublier_les_prix_non_confirmes
        return oublier_les_prix_non_confirmes(self.db, self.debut)

    def prix(self, code):
        return self.db.query(MarketCardPrice).filter_by(card_code=code).one().price_eur

    def test_un_prix_non_reconfirme_est_oublie(self):
        """Le cas qui justifie la fonction : plus rien ne venait l'écraser."""
        self.assertEqual(self.balayer()["oubliees"], 1)
        self.assertIsNone(self.prix("OP17-022"))

    def test_un_prix_reconfirme_est_garde(self):
        self.balayer()
        self.assertEqual(self.prix("OP17-005"), 7.0)

    def test_les_autres_sources_ne_sont_pas_touchees(self):
        """Ce balayage répare un rapprochement, il n'arbitre pas entre les
        sources."""
        self.balayer()
        self.assertEqual(self.prix("OP17-099"), 42.0)

    def test_une_carte_sans_prix_ne_compte_pas_pour_un_oubli(self):
        """Sinon le compte rendu annoncerait des centaines d'oublis à chaque
        passage, et le chiffre ne voudrait plus rien dire."""
        self.assertEqual(self.balayer()["oubliees"], 1)
        self.assertIsNone(self.prix("OP17-100"))

    def test_la_variation_part_avec_le_prix(self):
        """Une variation sans prix n'a aucun sens, et alimenterait une
        tendance sur un chiffre disparu."""
        self.db.query(MarketCardPrice).filter_by(
            card_code="OP17-022").one().variation_7d_eur = -12.0
        self.db.commit()
        self.balayer()
        fiche = self.db.query(MarketCardPrice).filter_by(card_code="OP17-022").one()
        self.assertIsNone(fiche.variation_7d_eur)

    def test_ce_qui_est_oublie_est_nomme(self):
        """Un effacement silencieux empêche de voir qu'il part trop large."""
        rapport = self.balayer()
        self.assertEqual(rapport["exemples"][0]["code"], "OP17-022")
        self.assertEqual(rapport["exemples"][0]["prix_oublie"], 850.0)


class TestVariantesQuiNeDisentPasLeurRang(unittest.TestCase):
    """LA CAUSE REELLE, constatée le 23/10/2026 sur la série OP17.

    Le site nomme ses variantes de deux façons selon les séries :

        OP15   « Ener (Version 2) », « Ener (Version 3) »
        OP17   « Shanks (Parallèle) », « Shanks (Manga) »,
               « Monkey D. Luffy (Super Leader Parallèle) »

    Seule la première dit son indice. La seconde était donc lue comme
    l'impression ordinaire, et les trois prix d'un même code — 850 €, 13 €
    et 0,75 € — revendiquaient la même fiche.

    Rien ne permet d'affirmer que « (Manga) » est la deuxième alternative
    plutôt que la première. Lui attribuer un rang au jugé poserait 850 €
    sur une carte qui en vaut 0,75 : l'erreur qui invente une affaire et
    fait payer.
    """

    def test_la_forme_avec_indice_garde_son_rang(self):
        self.assertEqual(rang_de_version("Ener (Version 3)"), ("Ener", 2))
        self.assertEqual(rang_de_version("Ener (Version 2)"), ("Ener", 1))

    def test_les_mentions_mesurees_recoivent_leur_rang(self):
        """Appariement établi en comparant les images des deux sources :
        relevé du 23/10/2026 sur OP17, cinq codes, distance 0 partout."""
        self.assertEqual(rang_de_version("Shanks (Parallèle)"), ("Shanks", 1))
        self.assertEqual(rang_de_version("Shanks (Manga)"), ("Shanks", 2))

    def test_une_mention_NON_mesuree_reste_sans_rang(self):
        """Le défaut exact qu'on corrigeait : une mention inconnue tombait
        au rang 0, donc sur l'impression ordinaire. Elle doit maintenant ne
        se rattacher à rien, en attendant d'être mesurée."""
        from app.collectors.opecards_prices import VARIANTE_SANS_RANG
        for nom in ("Monkey D. Luffy (Super Leader Parallèle)",
                    "Portgas D. Ace (Alternative)"):
            with self.subTest(nom=nom):
                self.assertEqual(rang_de_version(nom)[1], VARIANTE_SANS_RANG)

    def test_le_rapprochement_est_EXACT_et_non_par_fragment(self):
        """« Super Leader Parallèle » CONTIENT « Parallèle » mais n'est pas
        la première alternative. Un rapprochement par fragment lui donnerait
        le rang 1 et poserait 600 € sur une carte qui en vaut 35."""
        from app.collectors.opecards_prices import VARIANTE_SANS_RANG
        self.assertEqual(
            rang_de_version("Monkey D. Luffy (Super Leader Parallèle)")[1],
            VARIANTE_SANS_RANG)

    def test_l_accentuation_et_la_casse_ne_font_pas_perdre_le_rang(self):
        for nom in ("Shanks (Parallèle)", "Shanks (Parallele)",
                    "Shanks (PARALLELE)"):
            with self.subTest(nom=nom):
                self.assertEqual(rang_de_version(nom)[1], 1)

    def test_une_parenthese_qui_fait_partie_du_nom_reste_le_nom(self):
        """« Mr 3 (Galdino) » est une carte, pas une variante. La confondre
        retirerait du catalogue une carte parfaitement ordinaire."""
        self.assertEqual(rang_de_version("Mr 3 (Galdino)"), ("Mr 3 (Galdino)", 0))

    def test_le_libelle_brut_est_releve(self):
        """C'est lui qui permettra d'établir la correspondance avec les
        rangs de la liste officielle sur constat, et non sur hypothèse."""
        from app.collectors.opecards_prices import marqueur_de_variante
        self.assertEqual(marqueur_de_variante("Shanks (Manga)"), "Manga")
        self.assertEqual(
            marqueur_de_variante("Monkey D. Luffy (Super Leader Parallèle)"),
            "Super Leader Parallèle")
        self.assertIsNone(marqueur_de_variante("Mr 3 (Galdino)"))


class TestLeDefautObserveSurOP17(unittest.TestCase):
    """Le passage complet, reconstitué d'après le relevé du 23/10/2026."""

    def setUp(self):
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.db.add(MarketCardPrice(
            card_code="OP17-022", display_name="Shanks", name_slug="shanks",
            rarity="SR", price_eur=0.75, source="opecards"))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def appliquer(self):
        from app.collectors.opecards_prices import (
            PrixCarte, marqueur_de_variante,
        )

        def candidature(nom_affiche, prix):
            nom, rang = rang_de_version(nom_affiche)
            return PrixCarte(card_code="OP17-022-SR", display_name=nom,
                             rang_variante=rang, rarity="SR", price_eur=prix,
                             variation_eur=None, image_url=None,
                             detail_url="https://www.opecards.fr/x",
                             variante=marqueur_de_variante(nom_affiche))

        return appliquer_prix(self.db, [
            candidature("Shanks (Manga)", 850.0),
            candidature("Shanks (Parallèle)", 13.0),
            candidature("Shanks", 0.75),
        ])

    def test_l_impression_ordinaire_recoit_SON_prix(self):
        """Ce que le défaut empêchait : la fiche de base finissait à 850 €,
        ou au plancher, selon la règle en vigueur. Jamais à son prix."""
        rapport = self.appliquer()
        fiche = self.db.query(MarketCardPrice).filter_by(
            card_code="OP17-022").one()
        self.assertEqual(fiche.price_eur, 0.75)
        self.assertEqual(rapport["conflits"], [])

    def test_chaque_variante_va_sur_SA_fiche(self):
        """Ce que la mesure a débloqué : les deux alternatives ont un rang,
        donc un prix, au lieu de rester vides."""
        self.db.add_all([
            MarketCardPrice(card_code="OP17-022", display_name="Shanks (Parallèle 1)",
                            name_slug="shanks-parallele-1", rarity="SR"),
            MarketCardPrice(card_code="OP17-022", display_name="Shanks (Parallèle 2)",
                            name_slug="shanks-parallele-2", rarity="SR"),
        ])
        self.db.commit()
        from app.collectors.cardlist_fr import rang_de_parallele
        rapport = self.appliquer()
        self.assertEqual(rapport["variantes_sans_rang"], 0)
        par_rang = {rang_de_parallele(l.name_slug): l.price_eur
                    for l in self.db.query(MarketCardPrice)
                    .filter_by(card_code="OP17-022").all()}
        self.assertEqual(par_rang, {0: 0.75, 1: 13.0, 2: 850.0})

    def test_le_prix_de_850_n_atterrit_sur_aucune_fiche(self):
        """Le test qui compte vraiment."""
        self.appliquer()
        montants = [l.price_eur for l in self.db.query(MarketCardPrice).all()]
        self.assertNotIn(850.0, montants)


if __name__ == "__main__":
    unittest.main()
