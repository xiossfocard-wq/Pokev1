"""
Tests du releve de prix quotidien et du rattrapage des themes
(app/services/card_catalog.py).

Le releve est le mecanisme dont depend TOUT l'historique, donc toute
tendance de fond et toute projection. Deux proprietes comptent :

- un seul releve par carte et par jour, sinon la regression serait faussee
  par des doublons ;
- relancer la capture dans la meme journee met a jour au lieu d'empiler.

Le rattrapage des themes, lui, est ce qui evite qu'un theme nouvellement
ajoute reste vide pendant des jours.
"""
import sys, os, unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CardPriceSnapshot, MarketCardPrice
from app.services.card_catalog import (
    enregistrer_releve_du_jour,
    historique_de_la_carte,
    recalculer_champs_derives,
)
from app.services.card_themes import decoder_themes


def carte(nom, prix, code=None, rarete=None, themes=None):
    return MarketCardPrice(
        card_code=code,
        name_slug=nom.lower().replace(" ", "-"),
        display_name=nom,
        series_name="Serie test",
        rarity=rarete,
        price_eur=prix,
        source="zebradex",
        theme_slugs=themes,
    )


class TestReleveQuotidien(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add_all([
            carte("Dracaufeu ex", 400.0, code="PAF 234"),
            carte("Pikachu", 1.5, code="PAF 10"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_un_releve_est_cree_par_carte(self):
        resultat = enregistrer_releve_du_jour(self.db)
        self.assertEqual(resultat["examined"], 2)
        self.assertEqual(resultat["created"], 2)
        self.assertEqual(self.db.query(CardPriceSnapshot).count(), 2)

    def test_relancer_le_meme_jour_n_empile_pas_de_doublons(self):
        """Sans cette propriete, deux appels dans la journee donneraient
        deux points identiques et fausseraient la pente."""
        enregistrer_releve_du_jour(self.db)
        resultat = enregistrer_releve_du_jour(self.db)

        self.assertEqual(resultat["created"], 0)
        self.assertEqual(self.db.query(CardPriceSnapshot).count(), 2)

    def test_relancer_apres_un_changement_de_prix_met_a_jour_le_jour(self):
        enregistrer_releve_du_jour(self.db)

        pikachu = self.db.query(MarketCardPrice).filter_by(display_name="Pikachu").first()
        pikachu.price_eur = 2.5
        self.db.commit()

        resultat = enregistrer_releve_du_jour(self.db)
        self.assertEqual(resultat["updated"], 1)
        self.assertEqual(resultat["created"], 0)

        releve = (
            self.db.query(CardPriceSnapshot)
            .filter_by(name_slug="pikachu", captured_on=date.today())
            .one()
        )
        self.assertEqual(releve.price_eur, 2.5)

    def test_l_historique_est_rendu_dans_l_ordre(self):
        pikachu = self.db.query(MarketCardPrice).filter_by(display_name="Pikachu").first()
        debut = date.today() - timedelta(days=4)
        # Insere volontairement en desordre.
        for decalage in (3, 0, 4, 1, 2):
            self.db.add(CardPriceSnapshot(
                name_slug=pikachu.name_slug, card_code=pikachu.card_code,
                price_eur=1.0 + decalage, captured_on=debut + timedelta(days=decalage),
            ))
        self.db.commit()

        historique = historique_de_la_carte(self.db, pikachu.name_slug, pikachu.card_code)
        jours = [j for j, _ in historique]
        self.assertEqual(jours, sorted(jours))
        self.assertEqual(len(historique), 5)

    def test_l_historique_d_une_carte_ne_melange_pas_les_autres(self):
        enregistrer_releve_du_jour(self.db)
        historique = historique_de_la_carte(self.db, "pikachu", "PAF 10")
        self.assertEqual(len(historique), 1)
        self.assertEqual(historique[0][1], 1.5)

    def test_la_limite_borne_le_travail(self):
        resultat = enregistrer_releve_du_jour(self.db, limite=1)
        self.assertEqual(resultat["examined"], 1)


class TestRattrapageDesThemes(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_les_cartes_sans_theme_sont_rattrapees(self):
        """Au premier deploiement, toutes les cartes deja synchronisees
        n'ont aucun theme : sans ce rattrapage, les themes resteraient vides
        jusqu'a une resynchronisation complete, qui prend des jours."""
        self.db.add(carte("Noctali VMAX", 180.0, themes=None))
        self.db.commit()

        resultat = recalculer_champs_derives(self.db)
        self.assertEqual(resultat["updated"], 1)

        ligne = self.db.query(MarketCardPrice).one()
        self.assertIn("evolutions-evoli", decoder_themes(ligne.theme_slugs))

    def test_un_second_passage_ne_change_rien(self):
        """Idempotent : utile parce que la route peut etre relancee a la
        main sans risque."""
        self.db.add(carte("Pikachu", 1.0))
        self.db.commit()

        recalculer_champs_derives(self.db)
        resultat = recalculer_champs_derives(self.db)
        self.assertEqual(resultat["updated"], 0)

    def test_la_rarete_est_prise_en_compte(self):
        self.db.add(carte("Carte quelconque", 10.0, rarete="Illustration Rare"))
        self.db.commit()

        recalculer_champs_derives(self.db)
        ligne = self.db.query(MarketCardPrice).one()
        self.assertIn("illustration-rare", decoder_themes(ligne.theme_slugs))


if __name__ == "__main__":
    unittest.main()
