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
    from app.services.card_themes import encoder_themes, themes_de_la_carte


def carte(nom, prix, rarete=None, serie="Faille Paradoxe", code=None,
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
        image_url=image,
        image_source="tcgdex" if image else None,
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
            carte("Dracaufeu ex", 419.31, "Double Rare", code="PAF 234",
                  variation=25.0, image="https://exemple.test/dracaufeu.png"),
            carte("Noctali VMAX", 180.0, "Secret Rare", code="EB12 215",
                  variation=-30.0),
            carte("Pikachu", 1.20, "Commune", code="PAF 10", variation=0.01),
            carte("Évoli", 4.50, "Rare", code="PAF 11", variation=1.5),
            carte("Mew ex", 65.0, "Illustration Rare", code="PAF 232",
                  variation=None),
            carte("Lugia V", 95.0, "Full Art", serie="Tempête Argentée",
                  code="EB12 138", variation=9.0),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    # --- recherche et filtres --------------------------------------------

    def test_recherche_sans_filtre_rend_tout_avec_le_total(self):
        reponse = self.client.get("/api/cards")
        self.assertEqual(reponse.status_code, 200)
        corps = reponse.json()
        self.assertEqual(corps["total"], 6)
        self.assertEqual(len(corps["cartes"]), 6)

    def test_recherche_par_nom(self):
        corps = self.client.get("/api/cards", params={"q": "dracaufeu"}).json()
        self.assertEqual(corps["total"], 1)
        self.assertEqual(corps["cartes"][0]["display_name"], "Dracaufeu ex")

    def test_recherche_par_code_de_carte(self):
        corps = self.client.get("/api/cards", params={"q": "PAF 232"}).json()
        self.assertEqual(corps["total"], 1)
        self.assertEqual(corps["cartes"][0]["display_name"], "Mew ex")

    def test_filtre_par_theme(self):
        corps = self.client.get("/api/cards", params={"theme": "evolutions-evoli"}).json()
        noms = {c["display_name"] for c in corps["cartes"]}
        self.assertEqual(noms, {"Noctali VMAX", "Évoli"})

    def test_filtre_par_fourchette_de_prix(self):
        corps = self.client.get(
            "/api/cards", params={"price_min": 50, "price_max": 200}
        ).json()
        noms = {c["display_name"] for c in corps["cartes"]}
        self.assertEqual(noms, {"Noctali VMAX", "Mew ex", "Lugia V"})

    def test_filtre_par_rarete(self):
        corps = self.client.get("/api/cards", params={"rarity": "Illustration Rare"}).json()
        self.assertEqual(corps["total"], 1)

    def test_filtre_par_serie(self):
        corps = self.client.get("/api/cards", params={"series": "Argentée"}).json()
        self.assertEqual(corps["total"], 1)
        self.assertEqual(corps["cartes"][0]["display_name"], "Lugia V")

    def test_filtre_sur_la_presence_d_image(self):
        avec = self.client.get("/api/cards", params={"with_image": True}).json()
        self.assertEqual(avec["total"], 1)
        sans = self.client.get("/api/cards", params={"with_image": False}).json()
        self.assertEqual(sans["total"], 5)

    def test_les_filtres_se_cumulent(self):
        corps = self.client.get(
            "/api/cards",
            params={"theme": "evolutions-evoli", "price_max": 10},
        ).json()
        self.assertEqual(corps["total"], 1)
        self.assertEqual(corps["cartes"][0]["display_name"], "Évoli")

    def test_tri_par_prix_croissant(self):
        corps = self.client.get(
            "/api/cards", params={"sort_by": "prix", "order": "asc"}
        ).json()
        prix = [c["price_eur"] for c in corps["cartes"]]
        self.assertEqual(prix, sorted(prix))

    def test_pagination(self):
        page1 = self.client.get("/api/cards", params={"limit": 2, "offset": 0}).json()
        page2 = self.client.get("/api/cards", params={"limit": 2, "offset": 2}).json()
        self.assertEqual(page1["total"], 6)
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
        self.assertIn("pikachu", reponse.json()["detail"])

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
        evoli = par_slug["evolutions-evoli"]
        self.assertEqual(evoli["card_count"], 2)
        self.assertEqual(evoli["price_min_eur"], 4.5)
        self.assertEqual(evoli["price_max_eur"], 180.0)
        self.assertTrue(evoli["label"])
        self.assertTrue(evoli["description"])

    def test_un_theme_sans_carte_est_rendu_a_zero(self):
        """Il doit apparaitre avec 0 plutot que disparaitre : l'interface
        peut alors le griser au lieu de le cacher sans explication."""
        corps = self.client.get("/api/cards/themes").json()
        par_slug = {t["slug"]: t for t in corps["themes"]}
        self.assertIn("spectres", par_slug)
        self.assertEqual(par_slug["spectres"]["card_count"], 0)

    def test_valeurs_de_filtres_refletent_la_base(self):
        corps = self.client.get("/api/cards/filters").json()
        self.assertEqual(corps["total_cards"], 6)
        self.assertIn("Illustration Rare", corps["rarities"])
        self.assertIn("Tempête Argentée", corps["series"])
        self.assertEqual(corps["price_min_eur"], 1.2)
        self.assertEqual(corps["price_max_eur"], 419.31)

    # --- cartes en vogue -------------------------------------------------

    def test_les_cartes_en_vogue_sont_classees_en_pourcentage(self):
        """Évoli (+1,50 sur 3 EUR, soit +50 %) doit passer devant Dracaufeu
        (+25 sur 394 EUR, soit +6 %), alors qu'en euros c'est l'inverse.
        C'est tout l'interet du classement en pourcentage."""
        corps = self.client.get("/api/cards/trending", params={"direction": "hausse"}).json()
        noms = [c["display_name"] for c in corps["cartes"]]
        self.assertIn("Évoli", noms)
        self.assertIn("Dracaufeu ex", noms)
        self.assertLess(noms.index("Évoli"), noms.index("Dracaufeu ex"))

    def test_les_baisses_sont_servies_a_part(self):
        corps = self.client.get("/api/cards/trending", params={"direction": "baisse"}).json()
        noms = [c["display_name"] for c in corps["cartes"]]
        self.assertEqual(noms, ["Noctali VMAX"])

    def test_une_carte_sans_variation_n_est_pas_en_vogue(self):
        """Mew ex n'a pas de variation publiee : l'absence de donnee ne doit
        pas etre lue comme une stabilite, ni comme une tendance."""
        for direction in ("hausse", "baisse"):
            corps = self.client.get(
                "/api/cards/trending", params={"direction": direction}
            ).json()
            self.assertNotIn("Mew ex", [c["display_name"] for c in corps["cartes"]])

    def test_les_tendances_se_filtrent_par_budget(self):
        corps = self.client.get(
            "/api/cards/trending", params={"direction": "hausse", "price_max": 10}
        ).json()
        noms = [c["display_name"] for c in corps["cartes"]]
        self.assertIn("Évoli", noms)
        self.assertNotIn("Dracaufeu ex", noms)

    def test_direction_inconnue_est_refusee(self):
        reponse = self.client.get("/api/cards/trending", params={"direction": "haut"})
        self.assertEqual(reponse.status_code, 400)

    # --- fiche carte -----------------------------------------------------

    def test_la_fiche_porte_les_themes_decrits(self):
        id_carte = self.client.get(
            "/api/cards", params={"q": "dracaufeu"}
        ).json()["cartes"][0]["id"]

        corps = self.client.get(f"/api/cards/{id_carte}").json()
        self.assertEqual(corps["display_name"], "Dracaufeu ex")
        slugs = {t["slug"] for t in corps["themes_detail"]}
        self.assertIn("ligne-dracaufeu", slugs)
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
        ligne = self.db.query(MarketCardPrice).filter_by(display_name="Pikachu").first()
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
