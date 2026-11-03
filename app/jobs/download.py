"""Keep job files alive until a file response finishes or fails."""

from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from app.jobs.store import JobStore


class JobFileResponse(FileResponse):
    def __init__(self, path, *, store: JobStore, job_id: str, **kwargs):
        super().__init__(path, **kwargs)
        self.store = store
        self.job_id = job_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A background callback alone would leak the pin on disconnect/error.
            self.store.release_download(self.job_id)
