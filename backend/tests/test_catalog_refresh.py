"""
Le catalogue des series ZebraDex doit etre redecouvert regulierement, pas
seulement quand il est vide : sinon les extensions sorties apres la mise
en service n'apparaissent jamais (trois manquaient le 19/09/2026).
"""
import sys, os, unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AppSettings, ZebraDexSeriesState
from app.services import price_index


class TestRafraichissementCatalogue(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def _serie(self):
        self.db.add(ZebraDexSeriesState(
            series_id="s1", name="Serie", code="S1", bloc="B", url="https://x/s1",
        ))
        self.db.commit()

    def test_catalogue_vide_doit_etre_rafraichi(self):
        self.assertTrue(price_index._catalog_needs_refresh(self.db))

    def test_jamais_rafraichi_depuis_la_mise_en_service(self):
        self._serie()
        self.assertTrue(price_index._catalog_needs_refresh(self.db))

    def test_rafraichi_recemment_pas_besoin(self):
        self._serie()
        price_index._mark_catalog_refreshed(self.db)
        self.assertFalse(price_index._catalog_needs_refresh(self.db))

    def test_rafraichi_il_y_a_plus_d_un_jour(self):
        self._serie()
        vieux = (datetime.utcnow() - timedelta(hours=25)).isoformat()
        self.db.add(AppSettings(key="zebradex_catalog_refreshed_at", value=vieux))
        self.db.commit()
        self.assertTrue(price_index._catalog_needs_refresh(self.db))


if __name__ == "__main__":
    unittest.main()
