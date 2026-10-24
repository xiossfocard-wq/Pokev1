"""
Tests du job d'enrichissement des visuels (pipeline.enrich_card_images).

Ce job n'etait pas teste. Il l'est maintenant parce qu'il porte deux
decisions sur lesquelles l'interface repose :

1. `image_checked_at` est horodate MEME en cas d'echec, sinon les cartes
   introuvables monopolisent la file a chaque passage ;
2. les cartes sans code sont ecartees, parce qu'aucune adresse d'image
   n'est deductible pour elles et qu'elles prendraient la place de cartes
   servables dans un lot de taille fixe.

Aucun acces reseau : le client d'images est remplace par un double.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Le moteur est fige a l'import : voir la note dans test_api_routes.py.
_fichier_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_fichier_db.close()
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _fichier_db.name)

from app import pipeline
from app.collectors.card_images import SOURCE_EN, ImageCarte
from app.database import SessionLocal, init_db
from app.models import MarketCardPrice


class ClientFactice:
    """Rend une image pour les codes connus, None pour les autres, et
    enregistre ce qu'on lui a demande."""

    def __init__(self, codes_servis=(), codes_anglais=()):
        self.codes_servis = set(codes_servis)
        self.codes_anglais = set(codes_anglais)
        self.demandes = []
        # Ce que l'appelant a transmis sur chaque fiche : son rang et sa
        # langue. C'est precisement ce qui manquait pour chercher la bonne
        # illustration au bon endroit.
        self.contextes = []
        self.erreurs_reseau = 0
        self.reponses_http = 0

    def chercher_image(self, display_name, card_code=None, rang=None,
                       anglais=False):
        self.demandes.append(card_code)
        self.contextes.append({"code": card_code, "rang": rang,
                               "anglais": anglais})
        self.reponses_http += 1
        if card_code in self.codes_servis:
            return ImageCarte(image_url=f"https://exemple.test/{card_code}.png",
                              card_id=card_code)
        if anglais and card_code in self.codes_anglais:
            return ImageCarte(image_url=f"https://en.exemple.test/{card_code}.png",
                              source=SOURCE_EN, card_id=card_code)
        return None


def carte(nom, code, prix=10.0, langue=None, slug=None):
    return MarketCardPrice(
        card_code=code,
        name_slug=slug or nom.lower().replace(" ", "-"),
        display_name=nom,
        series_name="Romance Dawn",
        price_eur=prix,
        source="zebradex",
        language=langue,
    )


class TestEnrichissementVisuels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.db.query(MarketCardPrice).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _lancer(self, client, limit=40):
        with mock.patch.object(pipeline, "ClientImagesCartes",
                               return_value=client):
            return pipeline.enrich_card_images(self.db, limit=limit)

    def _recharger(self, code):
        return (
            self.db.query(MarketCardPrice)
            .filter(MarketCardPrice.card_code == code)
            .one()
        )

    def test_enregistre_l_image_trouvee(self):
        self.db.add(carte("Monkey D. Luffy", "OP01-120"))
        self.db.commit()

        resume = self._lancer(ClientFactice({"OP01-120"}))

        self.assertEqual((resume["examined"], resume["found"], resume["not_found"]),
                         (1, 1, 0))
        ligne = self._recharger("OP01-120")
        self.assertEqual(ligne.image_url, "https://exemple.test/OP01-120.png")
        self.assertEqual(ligne.image_source, "onepiece-cardgame")
        self.assertIsNotNone(ligne.image_checked_at)

    def test_horodate_meme_un_echec(self):
        """Sans cet horodatage, la carte introuvable revient en tete de file
        au passage suivant et y reste pour toujours."""
        self.db.add(carte("Carte absente", "OP99-999"))
        self.db.commit()

        resume = self._lancer(ClientFactice())

        self.assertEqual(resume["not_found"], 1)
        ligne = self._recharger("OP99-999")
        self.assertIsNone(ligne.image_url)
        self.assertIsNotNone(ligne.image_checked_at)

    def test_ignore_les_cartes_sans_code(self):
        """Aucune adresse d'image n'est deductible sans code : ces cartes ne
        doivent pas consommer de place dans le lot."""
        self.db.add_all([
            carte("Sans code", None),
            carte("Code vide", ""),
            carte("Monkey D. Luffy", "OP01-120"),
        ])
        self.db.commit()

        client = ClientFactice({"OP01-120"})
        resume = self._lancer(client)

        self.assertEqual(resume["examined"], 1)
        self.assertEqual(client.demandes, ["OP01-120"])

    def test_ne_reinterroge_pas_une_carte_deja_servie(self):
        deja = carte("Deja illustree", "OP01-001")
        deja.image_url = "https://exemple.test/deja.png"
        self.db.add_all([deja, carte("Monkey D. Luffy", "OP01-120")])
        self.db.commit()

        client = ClientFactice({"OP01-120"})
        self._lancer(client)

        self.assertEqual(client.demandes, ["OP01-120"])

    def test_les_plus_cheres_d_abord(self):
        """Le catalogue compte des milliers de cartes et le lot est petit :
        a defaut de tout servir, on sert d'abord ce qu'on regarde."""
        self.db.add_all([
            carte("Carte modeste", "OP01-001", prix=1.0),
            carte("Carte chere", "OP01-120", prix=400.0),
        ])
        self.db.commit()

        client = ClientFactice()
        self._lancer(client, limit=1)

        self.assertEqual(client.demandes, ["OP01-120"])

    def test_une_source_qui_casse_ne_casse_pas_le_cycle(self):
        """Une exception du collecteur ne doit pas interrompre le lot : les
        cartes suivantes doivent quand meme etre traitees."""
        class ClientQuiLeve(ClientFactice):
            def chercher_image(self, display_name, card_code=None, rang=None,
                               anglais=False):
                if card_code == "OP01-001":
                    self.demandes.append(card_code)
                    raise RuntimeError("hote injoignable")
                return super().chercher_image(display_name, card_code,
                                              rang=rang, anglais=anglais)

        self.db.add_all([
            carte("Carte chere", "OP01-001", prix=400.0),
            carte("Monkey D. Luffy", "OP01-120", prix=10.0),
        ])
        self.db.commit()

        client = ClientQuiLeve({"OP01-120"})
        resume = self._lancer(client)

        self.assertEqual((resume["examined"], resume["found"], resume["not_found"]),
                         (2, 1, 1))
        self.assertIsNotNone(self._recharger("OP01-001").image_checked_at)
        self.assertEqual(
            self._recharger("OP01-120").image_url,
            "https://exemple.test/OP01-120.png",
        )

    def test_catalogue_vide_ne_fait_rien(self):
        resume = self._lancer(ClientFactice())
        self.assertEqual(resume["examined"], 0)
        self.assertEqual(resume["found"], 0)
        self.assertEqual(resume["not_found"], 0)


class TestCeQueLaFicheSaitDElleMeme(unittest.TestCase):
    """Le pipeline transmet au client le rang et la langue de chaque fiche.

    Sans la langue, une carte qui n'existe qu'en anglais était cherchée sur
    le site français, où elle ne pouvait pas être : c'est ce qui laissait des
    centaines de fiches sans visuel. Sans le rang, la fiche du second
    parallèle pouvait recevoir l'image du premier.
    """

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.db.query(MarketCardPrice).delete()
        self.db.commit()

    def tearDown(self):
        self.db.query(MarketCardPrice).delete()
        self.db.commit()
        self.db.close()

    def _lancer(self, client):
        with mock.patch.object(pipeline, "ClientImagesCartes", return_value=client):
            return pipeline.enrich_card_images(self.db, limit=50)

    def test_une_carte_francaise_n_est_pas_cherchee_en_anglais(self):
        """Son illustration anglaise porterait un texte anglais, alors que
        c'est la carte française qui est en vente."""
        self.db.add(carte("Ener", "OP15-118", langue="fr"))
        self.db.commit()
        client = ClientFactice()
        self._lancer(client)
        self.assertFalse(client.contextes[0]["anglais"])

    def test_une_carte_absente_du_jeu_francais_est_cherchee_en_anglais(self):
        self.db.add(carte("Monkey.D.Luffy", "OP01-024", langue="en"))
        self.db.commit()
        client = ClientFactice()
        self._lancer(client)
        self.assertTrue(client.contextes[0]["anglais"])

    def test_le_rang_de_la_fiche_est_transmis(self):
        self.db.add_all([
            carte("Shanks", "OP17-022", slug="shanks"),
            carte("Shanks (Parallèle 2)", "OP17-022", slug="shanks-parallele-2"),
        ])
        self.db.commit()
        client = ClientFactice()
        self._lancer(client)
        self.assertEqual(sorted(c["rang"] for c in client.contextes), [0, 2])

    def test_les_visuels_anglais_sont_comptes_a_part(self):
        """Pour que le compte rendu dise d'où viennent les images."""
        self.db.add(carte("Monkey.D.Luffy", "OP01-024", langue="en"))
        self.db.commit()
        resume = self._lancer(ClientFactice(codes_anglais={"OP01-024"}))
        self.assertEqual(resume["found"], 1)
        self.assertEqual(resume["found_en"], 1)
        enregistree = self.db.query(MarketCardPrice).one()
        self.assertEqual(enregistree.image_source, SOURCE_EN)

    def test_le_compte_rendu_distingue_panne_et_absence(self):
        """« Le site ne répond pas » et « le site n'a pas cette image » n'ont
        ni la même cause ni le même remède. Les confondre faisait annoncer
        une source injoignable alors qu'elle répondait très bien."""
        self.db.add(carte("Inconnue", "OP99-999", langue="en"))
        self.db.commit()
        resume = self._lancer(ClientFactice())
        self.assertEqual(resume["found"], 0)
        self.assertGreater(resume["http_responses"], 0)
        self.assertEqual(resume["network_errors"], 0)


if __name__ == "__main__":
    unittest.main()
