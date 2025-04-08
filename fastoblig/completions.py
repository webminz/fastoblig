from fastoblig.canvas import CanvasClient
from fastoblig.domain import SubmissionState
from fastoblig.storage import Storage


class AutoCompleter:

    def __init__(self, storage: Storage, client: CanvasClient) -> None:
        self.storage = storage
        self.client = client

    def canvas_courses(self, prefix: str) -> list[tuple[str, str]]:
        return []

    def watched_courses(self, prefix: str) -> list[tuple[str, str]]:
        items = [ (f"{c.id}", f"{c.code} {c.semester} {c.year}") for c in self.storage.get_courses() if c.code is not None and c.code.startswith(prefix)]
        return items

    def watched_exercises(self, prefix: str) -> list[tuple[str, str]]:
        items = [ (f"{e.id}", f"{e.name} {e.course}") for e in self.storage.get_exercises() if e.name is not None and prefix in e.name]
        return items

    def submission_states(self, prefix: str) -> list[str]:
        items = [ s.name for s in SubmissionState if s.name.startswith(prefix) ]
        return items


