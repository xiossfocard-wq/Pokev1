"""
Tests du reglage SCHEDULER_ENABLED.

Ce reglage etait INVOQUE sans exister : des commandes de test passaient
SCHEDULER_ENABLED=false en croyant desactiver la collecte, alors que rien
ne lisait cette variable et que le planificateur demarrait quand meme. Sans
consequence visible ici — le premier passage n'arrive qu'apres l'intervalle
— mais une variable qui ne fait rien finit par mentir a quelqu'un.

Il devient utile avec l'usage local : on veut pouvoir ouvrir l'interface
sans qu'une collecte parte toute seule derriere.
"""
import sys, os, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import scheduler as module_scheduler


class TestReglageDuPlanificateur(unittest.TestCase):
    def setUp(self):
        self.faux = mock.MagicMock()
        correctif = mock.patch.object(module_scheduler, "scheduler", self.faux)
        correctif.start()
        self.addCleanup(correctif.stop)

    def _lancer(self, actif):
        with mock.patch.object(module_scheduler.settings, "scheduler_enabled", actif):
            module_scheduler.start_scheduler()

    def test_actif_par_defaut_les_taches_sont_programmees(self):
        """C'est la collecte qui fait vivre l'app : son defaut doit rester
        « allumee »."""
        from app.config import Settings
        self.assertTrue(Settings().scheduler_enabled)

        self._lancer(True)
        self.faux.start.assert_called_once()
        taches = [appel.kwargs.get("id") for appel in self.faux.add_job.call_args_list]
        self.assertIn("deal_check", taches)
        self.assertIn("card_price_snapshot", taches)
        self.assertIn("card_images", taches)

    def test_desactive_aucune_tache_n_est_programmee(self):
        self._lancer(False)
        self.faux.add_job.assert_not_called()
        self.faux.start.assert_not_called()

    def test_desactive_l_application_demarre_quand_meme(self):
        """Le point important : couper la collecte ne doit pas empecher
        l'app de tourner. Sinon le reglage serait inutilisable."""
        self._lancer(False)  # ne doit rien lever

    def test_le_reglage_se_lit_depuis_l_environnement(self):
        from app.config import Settings
        for valeur, attendu in [("false", False), ("true", True),
                                ("0", False), ("1", True)]:
            with self.subTest(valeur=valeur):
                with mock.patch.dict(os.environ, {"SCHEDULER_ENABLED": valeur}):
                    self.assertEqual(Settings().scheduler_enabled, attendu)


if __name__ == "__main__":
    unittest.main()
