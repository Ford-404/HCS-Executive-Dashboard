"""Thin Procore REST client: OAuth client-credentials auth, pagination, and the
two resources this report needs (projects and prime contracts)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

HOSTS = {
    "production": ("https://login.procore.com", "https://api.procore.com"),
    "sandbox": ("https://login-sandbox.procore.com", "https://sandbox.procore.com"),
}


class ProcoreClient:
    def __init__(self, client_id: str, client_secret: str, company_id: str | int,
                 environment: str = "production", prime_contract_path: str | None = None,
                 timeout: int = 60):
        self.login_base, self.api_base = HOSTS[environment]
        self.client_id = client_id
        self.client_secret = client_secret
        self.company_id = str(company_id)
        self.prime_contract_path = prime_contract_path or "/rest/v1.0/prime_contract?project_id={project_id}"
        self.timeout = timeout
        self.session = requests.Session()
        self._token: str | None = None
        self._token_expires = 0.0

    # ---- auth -----------------------------------------------------------
    def _auth_header(self) -> dict:
        if not self._token or time.time() > self._token_expires - 60:
            resp = self.session.post(
                f"{self.login_base}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            self._token = body["access_token"]
            self._token_expires = time.time() + int(body.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._token}", "Procore-Company-Id": self.company_id}

    # ---- transport --------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        url = path if path.startswith("http") else f"{self.api_base}{path}"
        for attempt in range(5):
            resp = self.session.get(url, params=params, headers=self._auth_header(), timeout=self.timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = int(resp.headers.get("Retry-After", 2 ** attempt * 5))
                log.warning("GET %s -> %s, retrying in %ss", url, resp.status_code, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def get_all(self, path: str, params: dict | None = None, per_page: int = 100) -> list[dict]:
        """Follow Procore's page/per_page pagination until a short page comes back."""
        params = dict(params or {})
        out: list[dict] = []
        page = 1
        while True:
            params.update(page=page, per_page=per_page)
            data = self._get(path, params).json()
            if isinstance(data, dict):  # v2 endpoints wrap results in {"data": [...]}
                data = data.get("data", [])
            out.extend(data)
            if len(data) < per_page:
                return out
            page += 1

    # ---- resources --------------------------------------------------------
    def list_projects(self, status: str = "Active") -> list[dict]:
        return self.get_all(
            f"/rest/v1.0/companies/{self.company_id}/projects",
            {"filters[by_status]": status},
        )

    def get_project(self, project_id: int) -> dict:
        """Full project record (includes custom fields that the list view may omit)."""
        return self._get(f"/rest/v1.0/projects/{project_id}", {"company_id": self.company_id}).json()

    def list_prime_contracts(self, project_id: int) -> list[dict]:
        path = self.prime_contract_path.format(project_id=project_id, company_id=self.company_id)
        return self.get_all(path)


class FixtureClient:
    """Same interface as ProcoreClient, but reads saved JSON. Used for tests and
    for previewing the layout without API credentials."""

    def __init__(self, fixture_dir: str | Path):
        d = Path(fixture_dir)
        self._projects = json.loads((d / "projects.json").read_text())
        self._contracts = json.loads((d / "prime_contracts.json").read_text())

    def list_projects(self, status: str = "Active") -> list[dict]:
        return [p for p in self._projects if p.get("active", True)]

    def get_project(self, project_id: int) -> dict:
        return next(p for p in self._projects if p["id"] == project_id)

    def list_prime_contracts(self, project_id: int) -> list[dict]:
        return self._contracts.get(str(project_id), [])
