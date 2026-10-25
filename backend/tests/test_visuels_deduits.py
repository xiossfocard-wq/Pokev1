"""
Tests de la deduction des visuels et de leur verification en arriere-plan.

CE QUI EST VERIFIE
------------------
Deux promesses, qui ne vont pas l'une sans l'autre :

1. AFFICHER VITE. Un echantillon verifie suffit a etablir le format, et
   toutes les autres adresses se posent d'un coup — au lieu de dix a
   quarante minutes de verification carte par carte.

2. NE PAS MENTIR DURABLEMENT. Une adresse deduite est marquee comme telle,
   puis verifiee en arriere-plan ; celle que le site refuse est retiree et
   la carte repasse par la recherche complete. Une coupure reseau, elle, ne
   retire rien.

Le client d'images utilise est le VRAI, branche sur un site simule qui ne
sert que les adresses qu'on lui donne.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import pipeline
from app.collectors import card_images
from app.collectors.card_images import MARQUE_DEDUITE, ClientImagesCartes
from app.database import Base
from app.models import MarketCardPrice

FR = "https://fr.test/card"
EN = "https://en.test/card"


class Reponse:
    def __init__(self, code, type_contenu=""):
        self.status_code = code
        self.headers = {"Content-Type": type_contenu}

    def close(self):
        pass


class SiteSimule:
    """Sert une image pour les adresses connues, 404 pour les autres."""

    def __init__(self, servies=(), coupe=False):
        self.servies = set(servies)
        self.coupe = coupe
        self.headers = {}
        self.appels = []

    def head(self, url, **_):
        self.appels.append(url)
        if self.coupe:
            raise requests.ConnectionError("coupure")
        if url in self.servies:
            return Reponse(200, "image/" + url.rsplit(".", 1)[-1])
        return Reponse(404, "text/html")

    get = head


def reglages():
    return mock.patch.multiple(card_images.settings,
                               card_image_base_url=FR,
                               card_image_fallback_base_url=EN,
                               card_image_verify=True)


class BaseEnMemoire(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()

    def tearDown(self):
        self.db.close()

    def cartes(self, codes, langue="en", slug=lambda c: c.lower()):
        for code in codes:
            self.db.add(MarketCardPrice(card_code=code, name_slug=slug(code),
                                        display_name=code, language=langue))
        self.db.commit()

    def fiche(self, code, slug=None):
        requete = self.db.query(MarketCardPrice).filter_by(card_code=code)
        if slug:
            requete = requete.filter_by(name_slug=slug)
        return requete.one()


class TestDeduction(BaseEnMemoire):
    CODES = [f"OP0{s}-{n:03d}" for s in range(1, 9) for n in range(1, 6)]  # 40 cartes

    def deduire(self, site):
        with reglages():
            return pipeline.deduire_visuels(
                self.db, client=ClientImagesCartes(session=site, min_delay=0))

    def test_un_format_etabli_est_etendu_a_toutes_les_cartes(self):
        """Le site anglais sert du png : l'echantillon l'etablit, et les
        quarante cartes recoivent leur adresse sans quarante verifications."""
        self.cartes(self.CODES)
        site = SiteSimule({f"{EN}/{c}.png" for c in self.CODES})
        rapport = self.deduire(site)
        self.assertEqual(rapport["deduites"] + rapport["verifiees"], 40)
        self.assertEqual(self.fiche("OP05-003").image_url, f"{EN}/OP05-003.png")
        # Huit cartes verifiees, a raison de deux essais au plus chacune
        # (webp refuse, puis png) : loin des quarante cartes.
        self.assertLessEqual(len(site.appels), 16)

    def test_les_adresses_deduites_sont_marquees(self):
        """Pour que le travail de fond sache lesquelles verifier."""
        self.cartes(self.CODES)
        self.deduire(SiteSimule({f"{EN}/{c}.png" for c in self.CODES}))
        sources = {l.image_source for l in self.db.query(MarketCardPrice).all()}
        self.assertIn(f"onepiece-cardgame-en{MARQUE_DEDUITE}", sources)
        # Celles de l'echantillon, elles, ont ete verifiees pour de vrai.
        self.assertIn("onepiece-cardgame-en", sources)

    def test_sans_format_etabli_rien_n_est_deduit(self):
        """Un site qui ne sert presque rien : on ne generalise pas sur deux
        succes, on laisse la recherche carte par carte."""
        self.cartes(self.CODES)
        rapport = self.deduire(SiteSimule({f"{EN}/OP01-001.png"}))
        self.assertEqual(rapport["deduites"], 0)
        self.assertFalse(rapport["groupes"][0]["format_etabli"])
        self.assertIsNone(self.fiche("OP05-003").image_url)

    def test_l_echantillon_couvre_plusieurs_series(self):
        """Les premieres cartes d'une liste triee sont toutes de la meme
        serie : un echantillon fait d'elles ne dirait rien des autres."""
        self.cartes(self.CODES)
        site = SiteSimule({f"{EN}/{c}.png" for c in self.CODES})
        self.deduire(site)
        series = {url.rsplit("/", 1)[-1][:4] for url in site.appels}
        self.assertGreaterEqual(len(series), 4)

    def test_une_carte_francaise_reste_sur_le_site_francais(self):
        self.cartes(self.CODES, langue="fr")
        self.deduire(SiteSimule({f"{FR}/{c}.webp" for c in self.CODES}))
        self.assertEqual(self.fiche("OP05-003").image_url, f"{FR}/OP05-003.webp")

    def test_une_illustration_alternative_recoit_son_suffixe(self):
        """Le suffixe des alternatives est eprouve dans l'echantillon, puis
        applique : le second parallele recoit « _p2 », pas l'image du
        premier."""
        self.cartes(self.CODES)
        self.cartes(["OP03-002", "OP06-004"], slug=lambda c: c.lower() + "-parallele-2")
        servies = {f"{EN}/{c}.png" for c in self.CODES}
        servies |= {f"{EN}/OP03-002_p2.png", f"{EN}/OP06-004_p2.png"}
        self.deduire(SiteSimule(servies))
        for code in ("OP03-002", "OP06-004"):
            self.assertEqual(self.fiche(code, slug=code.lower() + "-parallele-2").image_url,
                             f"{EN}/{code}_p2.png")

    def test_une_coupure_reseau_ne_deduit_rien(self):
        self.cartes(self.CODES)
        rapport = self.deduire(SiteSimule(coupe=True))
        self.assertEqual(rapport["deduites"], 0)
        self.assertGreater(rapport["network_errors"], 0)
        self.assertEqual(rapport["http_responses"], 0)


class TestVerificationEnArrierePlan(BaseEnMemoire):
    def deduite(self, code, url):
        self.db.add(MarketCardPrice(card_code=code, name_slug=code.lower(),
                                    display_name=code, language="en",
                                    image_url=url,
                                    image_source=f"onepiece-cardgame-en{MARQUE_DEDUITE}"))
        self.db.commit()

    def verifier(self, site):
        return pipeline.verifier_visuels_deduits(
            self.db, client=ClientImagesCartes(session=site, min_delay=0))

    def test_une_adresse_confirmee_perd_sa_marque(self):
        self.deduite("OP01-001", f"{EN}/OP01-001.png")
        self.verifier(SiteSimule({f"{EN}/OP01-001.png"}))
        fiche = self.fiche("OP01-001")
        self.assertEqual(fiche.image_source, "onepiece-cardgame-en")
        self.assertEqual(fiche.image_url, f"{EN}/OP01-001.png")

    def test_une_adresse_refusee_est_retiree_et_remise_en_tete(self):
        """Elle doit repasser par la recherche complete au plus tot, pas
        attendre derriere des milliers de cartes deja examinees."""
        self.deduite("OP01-001", f"{EN}/OP01-001.png")
        rapport = self.verifier(SiteSimule())
        fiche = self.fiche("OP01-001")
        self.assertIsNone(fiche.image_url)
        self.assertIsNone(fiche.image_source)
        self.assertIsNone(fiche.image_checked_at)
        self.assertEqual(rapport["removed"], 1)

    def test_une_coupure_reseau_ne_retire_rien(self):
        """Sinon quelques minutes sans reseau videraient le catalogue de
        tous ses visuels."""
        self.deduite("OP01-001", f"{EN}/OP01-001.png")
        rapport = self.verifier(SiteSimule(coupe=True))
        fiche = self.fiche("OP01-001")
        self.assertEqual(fiche.image_url, f"{EN}/OP01-001.png")
        self.assertTrue(fiche.image_source.endswith(MARQUE_DEDUITE))
        self.assertEqual(rapport["unknown"], 1)

    def test_les_adresses_verifiees_ne_sont_pas_reexaminees(self):
        self.db.add(MarketCardPrice(card_code="OP01-002", name_slug="op01-002",
                                    display_name="x", image_url=f"{FR}/OP01-002.webp",
                                    image_source="onepiece-cardgame"))
        self.db.commit()
        site = SiteSimule()
        self.assertEqual(self.verifier(site)["examined"], 0)
        self.assertEqual(site.appels, [])


if __name__ == "__main__":
    unittest.main()
