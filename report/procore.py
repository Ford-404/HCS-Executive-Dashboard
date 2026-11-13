"""Data sources for the report. The report only needs three methods:

    list_projects(status) -> [project, ...]
    get_project(id)       -> project (full record, incl. custom fields)
    list_prime_contracts(project_id) -> [prime contract, ...]

ProcoreAdapter provides them on top of the Procore client shared with the HCS Safety
Scorecard (report/procore_base.py: OAuth, rate limiting, retries, Windows cert store).
FixtureClient provides them from saved JSON for tests and offline previews.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PRIME_CONTRACT_PATH = "/rest/v1.0/prime_contracts?project_id={project_id}"


class ProcoreAdapter:
    def __init__(self, env_file: str | None = ".env", prime_contract_path: str | None = None,
                 company_id: str | int | None = None):
        from .procore_base import ProcoreClient  # needs requests/dotenv; not needed for fixtures

        self.base = ProcoreClient(env_file)
        if company_id and not self.base.company_id:
            self.base.company_id = str(company_id)
        self.company_id = str(self.base.company_id)
        self.prime_contract_path = prime_contract_path or DEFAULT_PRIME_CONTRACT_PATH

    def list_projects(self, status: str = "Active") -> list[dict]:
        return self.base.get_all(f"/rest/v1.0/companies/{self.company_id}/projects",
                                 {"filters[by_status]": status})

    def get_project(self, project_id: int) -> dict:
        return self.base.get(f"/rest/v1.0/projects/{project_id}", {"company_id": self.company_id})

    def list_prime_contracts(self, project_id: int) -> list[dict]:
        path = self.prime_contract_path.format(project_id=project_id, company_id=self.company_id)
        return self.base.get_all(path)

    @property
    def request_count(self) -> int:
        return self.base.request_count


class FixtureClient:
    """Same interface as ProcoreAdapter, but reads saved JSON. Used for tests and
    for previewing the layout without API credentials."""

    def __init__(self, fixture_dir: str | Path):
        d = Path(fixture_dir)
        self._projects = json.loads((d / "projects.json").read_text(encoding="utf-8"))
        self._contracts = json.loads((d / "prime_contracts.json").read_text(encoding="utf-8"))

    def list_projects(self, status: str = "Active") -> list[dict]:
        return [p for p in self._projects if p.get("active", True)]

    def get_project(self, project_id: int) -> dict:
        return next(p for p in self._projects if p["id"] == project_id)

    def list_prime_contracts(self, project_id: int) -> list[dict]:
        return self._contracts.get(str(project_id), [])
