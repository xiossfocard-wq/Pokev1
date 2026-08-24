"""
File d'attente EN MEMOIRE pour les recherches ciblees ("Chercher Pikachu").

Pourquoi ce module existe
-------------------------
Une recherche ciblee interroge Vinted et eBay en direct, puis score chaque
annonce trouvee (matching de prix + ecritures en base Neon). Mesure faite
le 24/08/2026 sur la prod : 289 s a froid, 126 s a chaud pour "pikachu".

Un navigateur n'attend pas aussi longtemps sur une seule requete HTTP (et
un intermediaire type Cloudflare/Render peut couper la connexion avant).
C'est pour ca que la barre de recherche ne rendait jamais rien depuis le
dashboard alors que le meme appel en `curl` finissait par repondre : curl,
lui, attend sans broncher.

Solution retenue
----------------
Le POST /api/listings/search ne fait plus le travail lui-meme : il cree un
job, le lance en tache de fond et rend un identifiant IMMEDIATEMENT. Le
frontend interroge ensuite GET /api/listings/search/{job_id} toutes les 2 s
jusqu'a l'etat "done". Plus aucune requete longue, donc plus aucun timeout.

Choix assumes
-------------
- Stockage en memoire (pas de table en base) : un job ne survit pas a un
  redemarrage du serveur. Acceptable pour une recherche a la demande, et
  ca evite une migration de schema.
- UN SEUL worker : deux recherches simultanees taperaient sur Vinted en
  parallele, ce qui contredit la politesse de scraping (delai entre
  requetes dans vinted_scraper.py). Les recherches sont donc mises en file.
- On memorise les IDs des annonces, pas les objets SQLAlchemy : ceux-ci
  appartiennent a la session du thread de fond et seraient inutilisables
  ailleurs. Le GET les relit proprement avec sa propre session.
"""
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Duree de retention d'un job termine : au-dela, il est purge. Large par
# rapport au temps de lecture d'un resultat par l'utilisateur.
JOB_RETENTION = timedelta(minutes=30)

# Garde-fou memoire : au-dela, on purge les plus anciens meme non expires.
MAX_JOBS = 50

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"


class SearchJob:
    def __init__(self, job_id: str, query: str):
        self.id = job_id
        self.query = query
        self.status = STATUS_PENDING
        self.message = "En attente de demarrage…"
        self.listing_ids: list = []
        self.error: Optional[str] = None
        self.created_at = datetime.utcnow()
        self.finished_at: Optional[datetime] = None

    @property
    def is_finished(self) -> bool:
        return self.status in (STATUS_DONE, STATUS_ERROR)

    def to_dict(self) -> dict:
        elapsed = (self.finished_at or datetime.utcnow()) - self.created_at
        return {
            "job_id": self.id,
            "query": self.query,
            "status": self.status,
            "message": self.message,
            "error": self.error,
            "result_count": len(self.listing_ids),
            "elapsed_seconds": round(elapsed.total_seconds(), 1),
        }


class SearchJobStore:
    def __init__(self):
        self._jobs: dict = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="targeted-search"
        )

    # -- lecture ---------------------------------------------------------

    def get(self, job_id: str) -> Optional[SearchJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def find_active_for_query(self, query: str) -> Optional[SearchJob]:
        """Une meme recherche relancee pendant qu'elle tourne encore ne cree
        pas un second job (sinon on doublerait la charge sur Vinted pour
        rien) : on renvoie celui deja en cours."""
        key = (query or "").strip().lower()
        with self._lock:
            for job in self._jobs.values():
                if job.query.strip().lower() == key and not job.is_finished:
                    return job
        return None

    # -- ecriture --------------------------------------------------------

    def submit(self, query: str, worker) -> SearchJob:
        """Cree un job et le met en file. `worker(job)` sera appele dans un
        thread de fond ; il doit remplir job.listing_ids."""
        existing = self.find_active_for_query(query)
        if existing is not None:
            return existing

        job = SearchJob(uuid.uuid4().hex[:12], (query or "").strip())
        with self._lock:
            self._purge_locked()
            self._jobs[job.id] = job
        self._executor.submit(self._run, job, worker)
        return job

    def _run(self, job: SearchJob, worker):
        job.status = STATUS_RUNNING
        job.message = "Interrogation de Vinted et eBay…"
        try:
            worker(job)
            job.status = STATUS_DONE
            job.message = f"{len(job.listing_ids)} annonce(s) trouvee(s)."
        except Exception as exc:  # noqa: BLE001 - on veut remonter l'erreur telle quelle
            logger.exception("Recherche ciblee '%s' echouee", job.query)
            job.status = STATUS_ERROR
            job.error = str(exc)
            job.message = "La recherche a echoue."
        finally:
            job.finished_at = datetime.utcnow()

    def _purge_locked(self):
        now = datetime.utcnow()
        expired = [
            jid for jid, job in self._jobs.items()
            if job.finished_at and now - job.finished_at > JOB_RETENTION
        ]
        for jid in expired:
            self._jobs.pop(jid, None)

        if len(self._jobs) >= MAX_JOBS:
            oldest = sorted(self._jobs.values(), key=lambda j: j.created_at)
            for job in oldest[: len(self._jobs) - MAX_JOBS + 1]:
                self._jobs.pop(job.id, None)


store = SearchJobStore()
