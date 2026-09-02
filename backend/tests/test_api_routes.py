"""
Tests des routes HTTP, exercees a travers un vrai client FastAPI.

Pourquoi ce fichier existe : jusqu'ici, les tests appelaient les fonctions
de route DIRECTEMENT (`correct_listing(listing_id, correction, db)`), en
fabriquant la session a la main. C'est utile pour la logique, mais ca saute
tout ce qui fait qu'une API repond ou non en vrai :

- l'application demarre-t-elle (lifespan, `init_db`, rattrapage de schema) ;
- les routeurs sont-ils reellement montes, et sous quel chemin ;
- le `response_model` sait-il serialiser un `Listing` en JSON ;
- l'injection de dependance `Depends(get_db)` fonctionne-t-elle ;
- les codes HTTP sont-ils ceux annonces (404 sur annonce inconnue, 400 sur
  action invalide) plutot qu'une 500 generique.

Le README annoncait ces points comme « non testes, a verifier au premier
lancement ». Ils le sont desormais.

Aucun acces reseau ici : on n'appelle QUE des routes qui se contentent de la
base. En particulier `POST /api/listings/search` est volontairement absent
(il lance un thread qui interroge Vinted et eBay) ; seule la consultation
d'un identifiant de recherche inconnu est verifiee.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Le moteur SQLAlchemy est cree a l'IMPORT de app.database, a partir de
# DATABASE_URL. Il faut donc fixer la variable avant tout import applicatif,
# sinon les tests iraient ecrire dans le dev.db du poste de travail.
_fichier_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_fichier_db.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _fichier_db.name

# TestClient a besoin de httpx, qui n'est pas une dependance d'execution du
# projet (voir requirements-dev.txt). Sans lui, on saute ces tests au lieu
# de faire echouer toute la suite.
_raison_saut = None
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - depend de l'environnement
    TestClient = None
    _raison_saut = f"client de test FastAPI indisponible ({exc})"

if TestClient is not None:
    from app.database import Base, SessionLocal, engine, init_db
    from app.main import app
    from app.models import AppSettings, Listing, ListingStatus, SourcePlatform

    # Garde-fou : le moteur est fige a l'import. Si un autre module de test
    # avait importe app.database AVANT celui-ci, il aurait ete construit sur
    # l'URL par defaut et ces tests ecriraient dans le dev.db du poste sans
    # que rien ne le signale. On prefere un echec bruyant a une base polluee.
    if _fichier_db.name not in str(engine.url):
        raise RuntimeError(
            "app.database a ete importe avant test_api_routes : le moteur "
            f"pointe sur {engine.url} au lieu de la base temporaire des "
            "tests. Lancer ce module en premier, ou isoler son execution."
        )


def tearDownModule():
    """La base temporaire ne sert qu'a ces tests : on ne la laisse pas
    trainer dans le repertoire temporaire du systeme."""
    try:
        engine.dispose()
        os.unlink(_fichier_db.name)
    except (OSError, NameError):  # pragma: no cover
        pass


def annonce(**surcharges):
    valeurs = dict(
        source=SourcePlatform.VINTED,
        external_id="ext-1",
        title="Dracaufeu ex 006/165",
        description="",
        url="https://www.vinted.fr/items/1",
        price=25.0,
        shipping_price=2.0,
        currency="EUR",
        photo_urls=[],
        seller_username="vendeur",
        status=ListingStatus.SCORED,
        reference_price=60.0,
        margin_net=30.0,
        deal_score=80.0,
    )
    valeurs.update(surcharges)
    return Listing(**valeurs)


@unittest.skipIf(TestClient is None, _raison_saut or "")
class TestDemarrageApplication(unittest.TestCase):
    """Le point que le README laissait en suspens : est-ce que le serveur
    demarre pour de vrai, avec son lifespan (creation des tables + ajout des
    colonnes rattrapees) et ses routeurs montes ?"""

    def test_le_serveur_demarre_et_repond(self):
        from app.scheduler import scheduler

        with TestClient(app) as client:
            try:
                reponse = client.get("/api/health")
                self.assertEqual(reponse.status_code, 200)
                self.assertEqual(reponse.json(), {"status": "ok"})
            finally:
                # start_scheduler() a demarre un thread de fond ; sans cet
                # arret, il survit a la fin du test.
                if scheduler.running:
                    scheduler.shutdown(wait=False)

    def test_le_demarrage_cree_le_schema_colonnes_rattrapees_comprises(self):
        from sqlalchemy import inspect

        init_db()
        colonnes = {c["name"] for c in inspect(engine).get_columns("listings")}
        # Ces trois colonnes ont ete ajoutees apres la mise en service : elles
        # ne sont pas creees par create_all sur une table deja existante, d'ou
        # le rattrapage dans init_db.
        self.assertIn("manual_status", colonnes)
        self.assertIn("manual_reference_price", colonnes)
        self.assertIn("manual_reviewed_at", colonnes)

    def test_toutes_les_routes_attendues_sont_montees(self):
        chemins = set()
        for route in app.routes:
            chemins.add(getattr(route, "path", None))
        # include_router() n'aplatit plus les sous-routeurs dans app.routes
        # selon les versions de FastAPI : on interroge donc le schema OpenAPI,
        # qui reflete ce que l'API expose reellement.
        chemins |= set(app.openapi()["paths"].keys())

        for attendu in [
            "/api/health",
            "/api/listings",
            "/api/listings/{listing_id}",
            "/api/listings/{listing_id}/correction",
            "/api/settings",
            "/api/admin/run-check-now",
            "/api/admin/price-index-status",
        ]:
            self.assertIn(attendu, chemins, f"route non montee : {attendu}")


@unittest.skipIf(TestClient is None, _raison_saut or "")
class TestRoutesHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        # Pas de context manager : on ne veut ni le scheduler ni ses threads
        # pendant les tests de routes. Le schema est deja cree ci-dessus.
        cls.client = TestClient(app)

    def setUp(self):
        self.db = SessionLocal()
        self.db.query(Listing).delete()
        self.db.query(AppSettings).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _ajouter(self, **surcharges):
        ligne = annonce(**surcharges)
        self.db.add(ligne)
        self.db.commit()
        self.db.refresh(ligne)
        return ligne

    # --- lecture ---------------------------------------------------------

    def test_liste_vide_rend_un_tableau_vide(self):
        reponse = self.client.get("/api/listings")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json(), [])

    def test_une_annonce_est_serialisee_en_json(self):
        ligne = self._ajouter()
        reponse = self.client.get("/api/listings")
        self.assertEqual(reponse.status_code, 200)
        corps = reponse.json()
        self.assertEqual(len(corps), 1)
        self.assertEqual(corps[0]["id"], ligne.id)
        self.assertEqual(corps[0]["title"], "Dracaufeu ex 006/165")
        self.assertEqual(corps[0]["price"], 25.0)

    def test_detail_d_une_annonce(self):
        ligne = self._ajouter()
        reponse = self.client.get(f"/api/listings/{ligne.id}")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["id"], ligne.id)

    def test_annonce_inconnue_rend_404_et_non_500(self):
        reponse = self.client.get("/api/listings/999999")
        self.assertEqual(reponse.status_code, 404)

    def test_tri_invalide_est_refuse_proprement(self):
        reponse = self.client.get("/api/listings?order=n_importe_quoi")
        self.assertEqual(reponse.status_code, 422)

    def test_les_annonces_sous_le_seuil_de_prix_sont_masquees(self):
        # Une carte a 1 EUR affichee avec « +59 EUR de marge » vient presque
        # toujours d'un rapprochement errone, pas d'une bonne affaire.
        self._ajouter(external_id="pas-chere", price=1.0)
        reponse = self.client.get("/api/listings")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json(), [])

    def test_filtre_par_source(self):
        self._ajouter(external_id="v", source=SourcePlatform.VINTED)
        self._ajouter(external_id="e", source=SourcePlatform.EBAY)
        vinted = self.client.get("/api/listings?source=vinted").json()
        self.assertEqual([a["source"] for a in vinted], ["vinted"])

    def test_source_inconnue_est_refusee(self):
        reponse = self.client.get("/api/listings?source=leboncoin")
        self.assertEqual(reponse.status_code, 400)

    def test_recherche_inconnue_rend_404(self):
        reponse = self.client.get("/api/listings/search/identifiant-inexistant")
        self.assertEqual(reponse.status_code, 404)

    # --- reglages --------------------------------------------------------

    def test_lecture_et_ecriture_des_reglages(self):
        actuels = self.client.get("/api/settings")
        self.assertEqual(actuels.status_code, 200)

        modifies = dict(actuels.json())
        modifies["deal_score_threshold"] = 55.0
        ecriture = self.client.put("/api/settings", json=modifies)
        self.assertEqual(ecriture.status_code, 200)
        self.assertEqual(ecriture.json()["deal_score_threshold"], 55.0)

        # et la valeur est bien persistee, pas seulement renvoyee
        relu = self.client.get("/api/settings").json()
        self.assertEqual(relu["deal_score_threshold"], 55.0)

    # --- corrections manuelles -------------------------------------------

    def test_correction_prix_manuel(self):
        ligne = self._ajouter()
        reponse = self.client.post(
            f"/api/listings/{ligne.id}/correction",
            json={"action": "set_price", "price": 42.0},
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["manual_reference_price"], 42.0)

    def test_correction_prix_negatif_refusee(self):
        ligne = self._ajouter()
        reponse = self.client.post(
            f"/api/listings/{ligne.id}/correction",
            json={"action": "set_price", "price": -5.0},
        )
        self.assertEqual(reponse.status_code, 400)

    def test_correction_prix_sans_montant_refusee(self):
        ligne = self._ajouter()
        reponse = self.client.post(
            f"/api/listings/{ligne.id}/correction", json={"action": "set_price"}
        )
        self.assertEqual(reponse.status_code, 400)

    def test_masquer_puis_annuler_la_correction(self):
        ligne = self._ajouter()

        masquer = self.client.post(
            f"/api/listings/{ligne.id}/correction", json={"action": "hide"}
        )
        self.assertEqual(masquer.status_code, 200)
        self.assertEqual(self.client.get("/api/listings").json(), [])

        annuler = self.client.post(
            f"/api/listings/{ligne.id}/correction", json={"action": "reset"}
        )
        self.assertEqual(annuler.status_code, 200)
        self.assertIsNone(annuler.json()["manual_status"])
        self.assertEqual(len(self.client.get("/api/listings").json()), 1)

    def test_mauvaise_carte_efface_le_prix_de_reference(self):
        ligne = self._ajouter()
        reponse = self.client.post(
            f"/api/listings/{ligne.id}/correction", json={"action": "wrong_card"}
        )
        self.assertEqual(reponse.status_code, 200)
        corps = reponse.json()
        self.assertEqual(corps["manual_status"], "wrong_card")
        # Le prix retire ne doit pas laisser derriere lui une marge et un
        # score qui continueraient de faire trner l'annonce en haut de liste.
        self.assertIsNone(corps["reference_price"])
        self.assertIsNone(corps["margin_net"])

    def test_action_inconnue_refusee(self):
        ligne = self._ajouter()
        reponse = self.client.post(
            f"/api/listings/{ligne.id}/correction", json={"action": "supprimer_tout"}
        )
        self.assertEqual(reponse.status_code, 400)

    def test_correction_sur_annonce_inconnue_rend_404(self):
        reponse = self.client.post(
            "/api/listings/999999/correction", json={"action": "reset"}
        )
        self.assertEqual(reponse.status_code, 404)

    # --- routes d'administration sans reseau ------------------------------

    def test_etat_de_l_index_de_prix(self):
        reponse = self.client.get("/api/admin/price-index-status")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("cards_in_index", reponse.json())

    def test_diagnostic_de_langue(self):
        reponse = self.client.get("/api/admin/test-language", params={"title": "carte japanese"})
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(reponse.json()["is_french"])


if __name__ == "__main__":
    unittest.main()
