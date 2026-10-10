"""Background jobs (alignment, rendering) with progress the UI can poll."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str
    project: str
    status: str = "running"          # running | done | error | cancelled
    message: str = ""
    progress: float = 0.0
    info: dict = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "project": self.project, "status": self.status,
                "message": self.message, "progress": round(self.progress, 4), "info": self.info,
                "result": self.result, "error": self.error, "started": self.started,
                "finished": self.finished}


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, kind: str, project: str, fn: Callable[[Job], Any]) -> Job:
        with self.lock:
            for j in self.jobs.values():
                if j.project == project and j.status == "running":
                    raise RuntimeError("This project is already busy. Wait for the current task or cancel it.")
            job = Job(uuid.uuid4().hex[:12], kind, project)
            self.jobs[job.id] = job

        def run():
            from ..render.compositor import Cancelled
            try:
                job.result = fn(job)
                job.status = "cancelled" if job.cancel.is_set() else "done"
                job.progress = 1.0 if job.status == "done" else job.progress
            except Cancelled:
                job.status = "cancelled"
            except Exception as exc:  # report to the UI
                if job.cancel.is_set():
                    job.status = "cancelled"
                    return
                job.status = "error"
                job.error = str(exc) or exc.__class__.__name__
                job.info["trace"] = traceback.format_exc()[-4000:]
            finally:
                job.finished = time.time()

        threading.Thread(target=run, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def active_for(self, project: str) -> list[Job]:
        return [j for j in self.jobs.values() if j.project == project and
                (j.status == "running" or (j.finished and time.time() - j.finished < 5))]
