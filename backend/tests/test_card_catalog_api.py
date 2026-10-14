"""
Tests de l'API d'exploration du catalogue (/api/cards), a travers un vrai
client HTTP.

Couvre la demande du 10/10/2026 : chercher des cartes par theme, par prix,
par type, voir les tendances, et refuser proprement une projection que
l'historique ne permet pas.

Aucun acces reseau : les cartes sont ecrites directement en base, et
l'enrichissement des visuels (qui interroge une API externe) n'est pas
appele ici.
"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Le moteur est fige a l'import : voir la note dans test_api_routes.py.
_fichier_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_fichier_db.close()
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _fichier_db.name)

_raison_saut = None
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover
    TestClient = None
    _raison_saut = f"client de test FastAPI indisponible ({exc})"

if TestClient is not None:
    from app.database import SessionLocal, init_db
    from app.main import app
    from app.models import CardPriceSnapshot, MarketCardPrice
    from app.services.card_themes import (
        cle_de_recherche, encoder_themes, themes_de_la_carte,
    )


def carte(nom, prix, rarete=None, serie="Romance Dawn", code=None,
          variation=None, image=None):
    """Fabrique une carte avec ses themes deja calcules, comme le fait la
    synchronisation reelle."""
    return MarketCardPrice(
        card_code=code,
        name_slug=nom.lower().replace(" ", "-"),
        display_name=nom,
        series_name=serie,
        rarity=rarete,
        price_eur=prix,
        price_low_eur=prix * 0.9,
        price_high_eur=prix * 1.1,
        variation_7d_eur=variation,
        source="zebradex",
        theme_slugs=encoder_themes(themes_de_la_carte(nom, rarete)),
        search_key=cle_de_recherche(nom, code),
        image_url=image,
        image_source="onepiece-cardgame" if image else None,
    )


@unittest.skipIf(TestClient is None, _raison_saut or "")
class TestCatalogueHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def setUp(self):
        self.db = SessionLocal()
        self.db.query(MarketCardPrice).delete()
        self.db.query(CardPriceSnapshot).delete()
        self.db.commit()

        self.db.add_all([
            carte("Monkey D. Luffy", 419.31, "Secret Rare", code="OP01-120",
                  variation=25.0, image="https://exemple.test/luffy.png"),
            carte("Trafalgar Law", 180.0, "Super Rare", code="OP02-049",
                  variation=-30.0),
            carte("Nami", 1.20, "Commune", code="OP01-016", variation=0.01),
            carte("Nico Robin", 4.50, "Rare", code="OP01-017", variation=1.5),
            carte("Shanks", 65.0, "Manga Rare", code="OP01-120",
                  variation=None),
            carte("Dracule Mihawk", 95.0, "Alternative Art",
                  serie="Paramount War", code="OP02-004", variation=9.0),
            carte("Portgás D. Ace", 72.0, "Super Rare", code="OP02-013",
                  variation=6.0),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    # --- recherche et filtres --------------------------------------------

    def test_recherche_sans_filtre_rend_tout_avec_le_total(self):
        reponse = self.client.get("/api/cards")
        self.assertEqual(reponse.status_code, 200)
        corps = reponse.json()
        self.assertEqual(corps["total"], 7)
        self.assertEqual(len(corps["cartes"]), 7)

    def test_recherche_par_nom(self):
        corps = self.client.get("/api/cards", params={"q": "luffy"}).json()
        self.assertEqual(corps["total"], 1)
        self.assertEqual(corps["cartes"][0]["display_name"], "Monkey D. Luffy")

    def test_recherche_par_code_de_carte(self):
        corps = self.client.get("/api/cards", params={"q": "OP02-049"}).json()
        self.assertEqual(corps["total"], 1)
        self.assertEqual(corps["cartes"][0]["display_name"], "Trafalgar Law")

    def test_recherche_insensible_aux_accents(self):
        """Regression. Deux defauts se cumulaient et rendaient la recherche
        inutilisable sur les noms accentues :

        - `lower()` de SQLite ne traite que l'ASCII, donc « Évoli » y restait
          « Évoli » alors que Python en faisait « évoli » : taper le nom
          exact, accent compris, ne rendait RIEN ;
        - personne ne tape les accents, et « electhor ex » ne correspondait
          ni au name_slug (« electhor-ex », avec un tiret) ni au nom affiche
          (« Électhor ex »), y compris sous Postgres.

        Les quatre graphies doivent desormais ramener la carte."""
        for graphie in ("Portgás", "portgás", "Portgas", "PORTGAS"):
            corps = self.client.get("/api/cards", params={"q": graphie}).json()
            self.assertEqual(
                corps["total"], 1,
                f"la recherche « {graphie} » ne trouve pas la carte",
            )
            self.assertEqual(corps["cartes"][0]["display_name"], "Portgás D. Ace")

    def test_recherche_sans_accent_sur_un_nom_compose(self):
        """Le cas qui echouait AUSSI sous Postgres : nom accentue en deux
        mots, cherche sans accent et avec un espace."""
        self.db.add(carte("Portgás D. Ace (Édition Spéciale)", 41.0,
                          "Super Rare", code="EB01-006"))
        self.db.commit()

        for graphie in ("edition speciale", "Édition Spéciale", "EDITION SPECIALE"):
            corps = self.client.get("/api/cards", params={"q": graphie}).json()
            self.assertEqual(corps["total"], 1, f"echec sur « {graphie} »")

    def test_la_recherche_fonctionne_avant_le_rattrapage(self):
        """Une base synchronisee avant l'ajout de la cle de recherche ne doit
        pas devenir mystérieusement vide : le repli sur le slug et sur le
        code de carte prend le relais jusqu'au passage de
        /api/admin/recompute-card-fields."""
        ancienne = carte("Eustass Kid", 72.0, "Super Rare", code="OP01-060")
        ancienne.search_key = None  # comme avant la migration
        self.db.add(ancienne)
        self.db.commit()

        par_slug = self.client.get("/api/cards", params={"q": "eustass"}).json()
        self.assertGreaterEqual(par_slug["total"], 1)

        par_code = self.client.get("/api/cards", params={"q": "OP01-060"}).json()
        self.assertGreaterEqual(par_code["total"], 1)

    def test_filtre_par_theme(self):
        corps = self.client.get("/api/cards", params={"theme": "chapeau-de-paille"}).json()
        noms = {c["display_name"] for c in corps["cartes"]}
        self.assertEqual(noms, {"Monkey D. Luffy", "Nami", "Nico Robin"})

    def test_filtre_par_fourchette_de_prix(self):
        corps = self.client.get(
            "/api/cards", params={"price_min": 50, "price_max": 200}
        ).json()
        noms = {c["display_name"] for c in corps["cartes"]}
        self.assertEqual(noms, {"Trafalgar Law", "Shanks", "Dracule Mihawk", "Portgás D. Ace"})

    def test_filtre_par_rarete(self):
        corps = self.client.get("/api/cards", params={"rarity": "Super Rare"}).json()
        self.assertEqual(corps["total"], 2)

    def test_filtre_par_serie(self):
        corps = self.client.get("/api/cards", params={"series": "Paramount"}).json()
        self.assertEqual(corps["total"], 1)
        self.assertEqual(corps["cartes"][0]["display_name"], "Dracule Mihawk")

    def test_filtre_sur_la_presence_d_image(self):
        avec = self.client.get("/api/cards", params={"with_image": True}).json()
        self.assertEqual(avec["total"], 1)
        sans = self.client.get("/api/cards", params={"with_image": False}).json()
        self.assertEqual(sans["total"], 6)

    def test_les_filtres_se_cumulent(self):
        corps = self.client.get(
            "/api/cards",
            params={"theme": "chapeau-de-paille", "price_max": 10},
        ).json()
        noms = {c["display_name"] for c in corps["cartes"]}
        self.assertEqual(noms, {"Nami", "Nico Robin"})

    def test_tri_par_prix_croissant(self):
        corps = self.client.get(
            "/api/cards", params={"sort_by": "prix", "order": "asc"}
        ).json()
        prix = [c["price_eur"] for c in corps["cartes"]]
        self.assertEqual(prix, sorted(prix))

    def test_pagination(self):
        page1 = self.client.get("/api/cards", params={"limit": 2, "offset": 0}).json()
        page2 = self.client.get("/api/cards", params={"limit": 2, "offset": 2}).json()
        self.assertEqual(page1["total"], 7)
        self.assertEqual(len(page1["cartes"]), 2)
        ids1 = {c["id"] for c in page1["cartes"]}
        ids2 = {c["id"] for c in page2["cartes"]}
        self.assertEqual(ids1 & ids2, set())

    # --- erreurs explicites ----------------------------------------------

    def test_theme_inconnu_est_refuse_en_nommant_les_valeurs(self):
        """Servir une liste vide pour un theme qui n'existe pas laisserait
        croire que le theme est vide."""
        reponse = self.client.get("/api/cards", params={"theme": "licornes"})
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("chapeau-de-paille", reponse.json()["detail"])

    def test_fourchette_inversee_est_refusee(self):
        reponse = self.client.get(
            "/api/cards", params={"price_min": 100, "price_max": 10}
        )
        self.assertEqual(reponse.status_code, 400)

    def test_tendance_inconnue_est_refusee(self):
        reponse = self.client.get("/api/cards", params={"trend": "haussiere"})
        self.assertEqual(reponse.status_code, 400)

    def test_tri_inconnu_est_refuse(self):
        reponse = self.client.get("/api/cards", params={"sort_by": "popularite"})
        self.assertEqual(reponse.status_code, 400)

    # --- themes ----------------------------------------------------------

    def test_les_themes_sont_comptes_et_chiffres(self):
        corps = self.client.get("/api/cards/themes").json()
        par_slug = {t["slug"]: t for t in corps["themes"]}
        equipage = par_slug["chapeau-de-paille"]
        self.assertEqual(equipage["card_count"], 3)
        self.assertEqual(equipage["price_min_eur"], 1.2)
        self.assertEqual(equipage["price_max_eur"], 419.31)
        self.assertTrue(equipage["label"])
        self.assertTrue(equipage["description"])

    def test_un_theme_sans_carte_est_rendu_a_zero(self):
        """Il doit apparaitre avec 0 plutot que disparaitre : l'interface
        peut alors le griser au lieu de le cacher sans explication."""
        corps = self.client.get("/api/cards/themes").json()
        par_slug = {t["slug"]: t for t in corps["themes"]}
        self.assertIn("cent-betes", par_slug)
        self.assertEqual(par_slug["cent-betes"]["card_count"], 0)

    def test_valeurs_de_filtres_refletent_la_base(self):
        corps = self.client.get("/api/cards/filters").json()
        self.assertEqual(corps["total_cards"], 7)
        self.assertIn("Super Rare", corps["rarities"])
        self.assertIn("Paramount War", corps["series"])
        self.assertEqual(corps["price_min_eur"], 1.2)
        self.assertEqual(corps["price_max_eur"], 419.31)

    # --- cartes en vogue -------------------------------------------------

    def test_les_cartes_en_vogue_sont_classees_en_pourcentage(self):
        """Évoli (+1,50 sur 3 EUR, soit +50 %) doit passer devant Dracaufeu
        (+25 sur 394 EUR, soit +6 %), alors qu'en euros c'est l'inverse.
        C'est tout l'interet du classement en pourcentage."""
        corps = self.client.get("/api/cards/trending", params={"direction": "hausse"}).json()
        noms = [c["display_name"] for c in corps["cartes"]]
        self.assertIn("Nico Robin", noms)
        self.assertIn("Monkey D. Luffy", noms)
        self.assertLess(noms.index("Nico Robin"), noms.index("Monkey D. Luffy"))

    def test_les_baisses_sont_servies_a_part(self):
        corps = self.client.get("/api/cards/trending", params={"direction": "baisse"}).json()
        noms = [c["display_name"] for c in corps["cartes"]]
        self.assertEqual(noms, ["Trafalgar Law"])

    def test_une_carte_sans_variation_n_est_pas_en_vogue(self):
        """Mew ex n'a pas de variation publiee : l'absence de donnee ne doit
        pas etre lue comme une stabilite, ni comme une tendance."""
        for direction in ("hausse", "baisse"):
            corps = self.client.get(
                "/api/cards/trending", params={"direction": direction}
            ).json()
            self.assertNotIn("Shanks", [c["display_name"] for c in corps["cartes"]])

    def test_les_tendances_se_filtrent_par_budget(self):
        corps = self.client.get(
            "/api/cards/trending", params={"direction": "hausse", "price_max": 10}
        ).json()
        noms = [c["display_name"] for c in corps["cartes"]]
        self.assertIn("Nico Robin", noms)
        self.assertNotIn("Monkey D. Luffy", noms)

    def test_direction_inconnue_est_refusee(self):
        reponse = self.client.get("/api/cards/trending", params={"direction": "haut"})
        self.assertEqual(reponse.status_code, 400)

    # --- fiche carte -----------------------------------------------------

    def test_la_fiche_porte_les_themes_decrits(self):
        id_carte = self.client.get(
            "/api/cards", params={"q": "luffy"}
        ).json()["cartes"][0]["id"]

        corps = self.client.get(f"/api/cards/{id_carte}").json()
        self.assertEqual(corps["display_name"], "Monkey D. Luffy")
        slugs = {t["slug"] for t in corps["themes_detail"]}
        self.assertIn("chapeau-de-paille", slugs)
        for theme in corps["themes_detail"]:
            self.assertTrue(theme["label"])

    def test_la_fourchette_est_signalee_comme_derivee(self):
        """Le README insiste : ce ne sont pas des extremes de ventes
        conclues. L'API doit porter ce rappel jusqu'a l'interface."""
        corps = self.client.get("/api/cards").json()
        for c in corps["cartes"]:
            self.assertTrue(c["price_range_is_derived"])

    def test_aucune_projection_quand_l_historique_est_vide(self):
        """LA garantie a ne pas perdre : pas de chiffre invente."""
        id_carte = self.client.get("/api/cards").json()["cartes"][0]["id"]
        corps = self.client.get(f"/api/cards/{id_carte}").json()
        self.assertEqual(corps["trend_history"]["fiabilite"], "insuffisant")
        self.assertIsNone(corps["projection"]["prix_projete_eur"])
        self.assertTrue(corps["projection"]["avertissement"])

    def test_une_projection_apparait_quand_l_historique_le_permet(self):
        ligne = self.db.query(MarketCardPrice).filter_by(display_name="Nami").first()
        debut = date.today() - timedelta(days=29)
        for i in range(30):
            self.db.add(CardPriceSnapshot(
                name_slug=ligne.name_slug, card_code=ligne.card_code,
                price_eur=1.0 + i * 0.1, captured_on=debut + timedelta(days=i),
            ))
        self.db.commit()

        corps = self.client.get(f"/api/cards/{ligne.id}").json()
        self.assertEqual(len(corps["history"]), 30)
        self.assertNotEqual(corps["trend_history"]["fiabilite"], "insuffisant")
        self.assertIsNotNone(corps["projection"]["prix_projete_eur"])
        self.assertGreater(corps["trend_history"]["pente_eur_par_jour"], 0)

    def test_carte_inconnue_rend_404(self):
        self.assertEqual(self.client.get("/api/cards/999999").status_code, 404)

    def test_les_chemins_litteraux_ne_sont_pas_pris_pour_des_identifiants(self):
        """/api/cards/themes ne doit pas etre interprete comme un id : les
        routes litterales doivent etre declarees avant /{card_id}."""
        for chemin in ("/api/cards/themes", "/api/cards/filters", "/api/cards/trending"):
            self.assertEqual(self.client.get(chemin).status_code, 200, chemin)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(TestClient is None, _raison_saut or "")
class TestAnnoncesDeLaCarte(unittest.TestCase):
    """Le pont entre les deux moities de l'app : depuis une carte du
    catalogue, voir ce qui est en vente maintenant.

    Ce qui compte ici : le lien annonce -> carte doit etre un vrai lien
    joignable (il ne vivait que dans un JSON), les exclusions du dashboard
    doivent s'appliquer a l'identique, et les photos du VENDEUR doivent
    etre rendues — c'est l'exemplaire reel qu'on achete.
    """

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def setUp(self):
        from app.models import Listing, ListingStatus, SourcePlatform
        self.Listing, self.ListingStatus, self.Source = Listing, ListingStatus, SourcePlatform

        self.db = SessionLocal()
        self.db.query(Listing).delete()
        self.db.query(MarketCardPrice).delete()
        self.db.commit()

        self.luffy = carte("Monkey D. Luffy", 400.0, "Secret Rare", code="OP01-120")
        self.zoro = carte("Roronoa Zoro", 180.0, "Super Rare", code="OP01-025")
        self.db.add_all([self.luffy, self.zoro])
        self.db.commit()
        self.db.refresh(self.luffy)
        self.db.refresh(self.zoro)

    def tearDown(self):
        self.db.close()

    def _annonce(self, ext, carte_id, prix, score, **surcharges):
        valeurs = dict(
            source=self.Source.VINTED, external_id=ext,
            title="Carte One Piece", url=f"https://exemple.test/{ext}",
            price=prix, shipping_price=2.0,
            photo_urls=[f"https://exemple.test/{ext}-1.jpg"],
            status=self.ListingStatus.SCORED, deal_score=score,
            margin_net=50.0, matched_card_id=carte_id,
        )
        valeurs.update(surcharges)
        ligne = self.Listing(**valeurs)
        self.db.add(ligne)
        self.db.commit()
        return ligne

    def test_seules_les_annonces_de_cette_carte_remontent(self):
        self._annonce("a", self.luffy.id, 120.0, 88.0)
        self._annonce("b", self.zoro.id, 60.0, 70.0)

        corps = self.client.get(f"/api/cards/{self.luffy.id}/listings").json()
        self.assertEqual(corps["count"], 1)
        self.assertEqual(corps["listings"][0]["id"],
                         self.db.query(self.Listing).filter_by(external_id="a").one().id)
        self.assertEqual(corps["display_name"], "Monkey D. Luffy")

    def test_les_meilleures_affaires_d_abord(self):
        self._annonce("moyenne", self.luffy.id, 200.0, 62.0)
        self._annonce("excellente", self.luffy.id, 110.0, 91.0)

        corps = self.client.get(f"/api/cards/{self.luffy.id}/listings").json()
        scores = [a["deal_score"] for a in corps["listings"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_les_photos_du_vendeur_sont_rendues(self):
        """Pour decider d'acheter, c'est l'exemplaire reel qu'on regarde."""
        self._annonce("photo", self.luffy.id, 130.0, 80.0,
                      photo_urls=["https://exemple.test/1.jpg", "https://exemple.test/2.jpg"])
        corps = self.client.get(f"/api/cards/{self.luffy.id}/listings").json()
        self.assertEqual(len(corps["listings"][0]["photo_urls"]), 2)

    def test_le_total_port_compris_est_calcule(self):
        """Le prix affiche sur l'annonce n'est pas ce qu'on paie."""
        self._annonce("port", self.luffy.id, 100.0, 80.0, shipping_price=4.5)
        corps = self.client.get(f"/api/cards/{self.luffy.id}/listings").json()
        self.assertEqual(corps["listings"][0]["total_eur"], 104.5)

    def test_une_annonce_masquee_a_la_main_reste_masquee_ici(self):
        """Une annonce cachee d'un cote ne doit pas reapparaitre de l'autre."""
        self._annonce("cachee", self.luffy.id, 120.0, 88.0, manual_status="hidden")
        corps = self.client.get(f"/api/cards/{self.luffy.id}/listings").json()
        self.assertEqual(corps["count"], 0)

    def test_une_annonce_disparue_chez_le_vendeur_est_exclue(self):
        self._annonce("vendue", self.luffy.id, 120.0, 88.0,
                      status=self.ListingStatus.UNAVAILABLE)
        corps = self.client.get(f"/api/cards/{self.luffy.id}/listings").json()
        self.assertEqual(corps["count"], 0)

    def test_une_annonce_ecartee_est_exclue(self):
        self._annonce("ecartee", self.luffy.id, 120.0, 88.0,
                      status=self.ListingStatus.IGNORED)
        corps = self.client.get(f"/api/cards/{self.luffy.id}/listings").json()
        self.assertEqual(corps["count"], 0)

    def test_une_carte_sans_annonce_rend_une_liste_vide(self):
        """Pas une erreur : la plupart des cartes n'ont rien en vente."""
        reponse = self.client.get(f"/api/cards/{self.zoro.id}/listings")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["count"], 0)

    def test_carte_inconnue_rend_404(self):
        self.assertEqual(self.client.get("/api/cards/999999/listings").status_code, 404)
