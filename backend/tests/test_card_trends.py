"""
Tests des tendances et de la projection (app/services/card_trends.py).

Ce que ces tests protegent avant tout : le REFUS de projeter quand
l'historique est trop court. C'est la garantie centrale du module. Un prix
projete calcule sur deux releves serait un chiffre invente, et un chiffre
invente affiche a cote de vrais prix est pris pour un vrai prix.
"""
import sys, os, unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.card_trends import (
    MIN_JOURS,
    MIN_POINTS,
    projection,
    tendance_7_jours,
    tendance_historique,
)


class TestTendance7Jours(unittest.TestCase):
    def test_le_pourcentage_part_du_prix_d_avant(self):
        """Une carte passee de 10 a 20 EUR a pris 100 %, pas 50 %."""
        t = tendance_7_jours(price_eur=20.0, variation_7d_eur=10.0)
        self.assertEqual(t.variation_pct, 100.0)
        self.assertEqual(t.direction, "hausse")

    def test_une_petite_variation_est_stable(self):
        t = tendance_7_jours(price_eur=100.0, variation_7d_eur=1.0)
        self.assertEqual(t.direction, "stable")
        self.assertEqual(t.label, "Stable sur 7 jours")

    def test_une_baisse_est_detectee(self):
        t = tendance_7_jours(price_eur=50.0, variation_7d_eur=-8.0)
        self.assertEqual(t.direction, "baisse")
        self.assertEqual(t.intensite, "forte")
        self.assertLess(t.variation_pct, 0)

    def test_variation_moderee(self):
        t = tendance_7_jours(price_eur=104.0, variation_7d_eur=4.0)
        self.assertEqual(t.direction, "hausse")
        self.assertEqual(t.intensite, "moderee")

    def test_variation_absente_est_dite_inconnue(self):
        """Pas de variation publiee : on le dit, on ne met pas zero. Zero
        voudrait dire « stable », ce qui est une affirmation."""
        t = tendance_7_jours(price_eur=30.0, variation_7d_eur=None)
        self.assertEqual(t.direction, "inconnu")
        self.assertIsNone(t.variation_pct)

    def test_prix_absent_est_dit_inconnu(self):
        t = tendance_7_jours(price_eur=None, variation_7d_eur=5.0)
        self.assertEqual(t.direction, "inconnu")

    def test_variation_superieure_au_prix_ne_casse_pas(self):
        """Cas degenere : le pourcentage n'aurait aucun sens, la valeur en
        euros est conservee."""
        t = tendance_7_jours(price_eur=5.0, variation_7d_eur=10.0)
        self.assertIsNone(t.variation_pct)
        self.assertEqual(t.direction, "hausse")
        self.assertIn("EUR", t.label)


def _serie(nb_jours: int, prix_depart: float = 10.0, pas: float = 0.5):
    debut = date(2026, 9, 1)
    return [(debut + timedelta(days=i), prix_depart + i * pas) for i in range(nb_jours)]


class TestTendanceHistorique(unittest.TestCase):
    def test_historique_vide(self):
        fond = tendance_historique([])
        self.assertEqual(fond.points, 0)
        self.assertEqual(fond.fiabilite, "insuffisant")
        self.assertIsNone(fond.variation_pct)

    def test_historique_trop_court_est_refuse(self):
        fond = tendance_historique(_serie(MIN_POINTS - 1))
        self.assertEqual(fond.fiabilite, "insuffisant")
        self.assertIsNone(fond.pente_eur_par_jour)

    def test_assez_de_points_mais_etales_sur_trop_peu_de_jours(self):
        """Dix releves pris dans la meme semaine ne font pas une tendance de
        fond : les deux conditions sont exigees."""
        debut = date(2026, 9, 1)
        releves = [(debut + timedelta(days=i % 3), 10.0 + i) for i in range(10)]
        self.assertEqual(tendance_historique(releves).fiabilite, "insuffisant")

    def test_une_hausse_lineaire_est_mesuree(self):
        fond = tendance_historique(_serie(30))
        self.assertEqual(fond.points, 30)
        self.assertEqual(fond.jours_couverts, 29)
        self.assertAlmostEqual(fond.pente_eur_par_jour, 0.5, places=3)
        self.assertAlmostEqual(fond.r2, 1.0, places=3)
        self.assertNotEqual(fond.fiabilite, "insuffisant")

    def test_le_desordre_des_releves_ne_change_rien(self):
        serie = _serie(30)
        a_l_endroit = tendance_historique(serie)
        a_l_envers = tendance_historique(list(reversed(serie)))
        self.assertEqual(a_l_endroit.pente_eur_par_jour, a_l_envers.pente_eur_par_jour)
        self.assertEqual(a_l_endroit.variation_pct, a_l_envers.variation_pct)

    def test_un_prix_constant_donne_une_pente_nulle(self):
        releves = [(date(2026, 9, 1) + timedelta(days=i), 12.0) for i in range(20)]
        fond = tendance_historique(releves)
        self.assertEqual(fond.pente_eur_par_jour, 0.0)
        self.assertEqual(fond.variation_pct, 0.0)

    def test_des_prix_erratiques_donnent_un_mauvais_ajustement(self):
        """Le r2 doit dire que la droite ne decrit pas bien les donnees :
        c'est ce qui empeche de presenter du bruit comme une tendance."""
        debut = date(2026, 9, 1)
        prix = [10, 80, 12, 75, 9, 90, 11, 70, 13, 85,
                8, 95, 14, 65, 10, 88, 12, 72, 9, 91]
        releves = [(debut + timedelta(days=i), float(p)) for i, p in enumerate(prix)]
        fond = tendance_historique(releves)
        self.assertLess(fond.r2, 0.3)

    def test_l_avertissement_est_toujours_porte(self):
        for releves in ([], _serie(3), _serie(30)):
            self.assertTrue(tendance_historique(releves).avertissement)


class TestProjection(unittest.TestCase):
    def test_aucune_projection_sans_historique_suffisant(self):
        """LA garantie du module : pas de chiffre invente."""
        for releves in ([], _serie(1), _serie(MIN_POINTS - 1)):
            p = projection(releves)
            self.assertIsNone(p.prix_projete_eur)
            self.assertEqual(p.fiabilite, "insuffisant")

    def test_projection_sur_une_hausse_lineaire(self):
        p = projection(_serie(30), horizon_jours=10)
        # Dernier prix 24.5, pente 0.5/jour, 10 jours -> 29.5
        self.assertAlmostEqual(p.prix_projete_eur, 29.5, places=2)

    def test_la_projection_ne_descend_jamais_sous_zero(self):
        """Une pente fortement descendante prolongee donnerait un prix
        negatif, ce qui n'existe pas."""
        releves = _serie(30, prix_depart=20.0, pas=-0.6)
        p = projection(releves, horizon_jours=365)
        self.assertGreaterEqual(p.prix_projete_eur, 0.0)

    def test_l_horizon_est_rendu_tel_quel(self):
        self.assertEqual(projection(_serie(30), horizon_jours=90).horizon_jours, 90)

    def test_l_avertissement_d_extrapolation_est_present(self):
        p = projection(_serie(30))
        self.assertIn("prevision", p.avertissement.lower())


if __name__ == "__main__":
    unittest.main()
