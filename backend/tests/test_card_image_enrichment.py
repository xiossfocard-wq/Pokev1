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
from app.collectors.card_images import ImageCarte
from app.database import SessionLocal, init_db
from app.models import MarketCardPrice


class ClientFactice:
    """Rend une image pour les codes connus, None pour les autres, et
    enregistre ce qu'on lui a demande."""

    def __init__(self, codes_servis=()):
        self.codes_servis = set(codes_servis)
        self.demandes = []

    def chercher_image(self, display_name, card_code=None):
        self.demandes.append(card_code)
        if card_code in self.codes_servis:
            return ImageCarte(image_url=f"https://exemple.test/{card_code}.png",
                              card_id=card_code)
        return None


def carte(nom, code, prix=10.0):
    return MarketCardPrice(
        card_code=code,
        name_slug=nom.lower().replace(" ", "-"),
        display_name=nom,
        series_name="Romance Dawn",
        price_eur=prix,
        source="zebradex",
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

        self.assertEqual(resume, {"examined": 1, "found": 1, "not_found": 0})
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
            def chercher_image(self, display_name, card_code=None):
                self.demandes.append(card_code)
                if card_code == "OP01-001":
                    raise RuntimeError("hote injoignable")
                return super().chercher_image(display_name, card_code)

        self.db.add_all([
            carte("Carte chere", "OP01-001", prix=400.0),
            carte("Monkey D. Luffy", "OP01-120", prix=10.0),
        ])
        self.db.commit()

        client = ClientQuiLeve({"OP01-120"})
        resume = self._lancer(client)

        self.assertEqual(resume, {"examined": 2, "found": 1, "not_found": 1})
        self.assertIsNotNone(self._recharger("OP01-001").image_checked_at)
        self.assertEqual(
            self._recharger("OP01-120").image_url,
            "https://exemple.test/OP01-120.png",
        )

    def test_catalogue_vide_ne_fait_rien(self):
        self.assertEqual(
            self._lancer(ClientFactice()),
            {"examined": 0, "found": 0, "not_found": 0},
        )


if __name__ == "__main__":
    unittest.main()
