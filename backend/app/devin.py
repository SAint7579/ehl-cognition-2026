"""Devin Cloud Sessions API (v3). Science runs in the sandbox VM, not locally."""

from __future__ import annotations

import re
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlparse

import httpx

from backend.app.settings import configured_repos, env_value, missing_devin_settings

APP_ATTACHMENT = re.compile(
    r"/attachments/(?P<uuid>[0-9a-fA-F-]{36})/(?P<name>[^/?#]+)$"
)


class SessionClient(Protocol):
    def create_session(
        self,
        prompt: str,
        title: str,
        playbook_id: str | None = None,
    ) -> dict[str, Any]: ...
    def list_playbooks(self) -> list[dict[str, Any]]: ...
    def get_playbook(self, playbook_id: str) -> dict[str, Any]: ...
    def get_session(self, session_id: str) -> dict[str, Any]: ...
    def send_message(self, session_id: str, message: str) -> None: ...
    def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...
    def list_attachments(self, session_id: str) -> list[dict[str, Any]]: ...
    def download(self, url: str) -> bytes: ...


class DevinError(RuntimeError):
    pass


class DevinClient:
    def __init__(
        self,
        api_key: str,
        org_id: str,
        base_url: str = "https://api.devin.ai",
        snapshot_id: str | None = None,
        repos: list[str] | None = None,
        playbook_id: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.org_id = org_id
        self.snapshot_id = snapshot_id
        self.repos = repos or []
        self.playbook_id = playbook_id
        self._timeout = timeout
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            follow_redirects=False,
        )

    @classmethod
    def from_env(cls) -> DevinClient:
        missing = missing_devin_settings()
        if missing:
            raise DevinError(_missing_message(missing))
        return cls(
            api_key=env_value("DEVIN_API_KEY"),
            org_id=env_value("DEVIN_ORG_ID"),
            base_url=env_value("DEVIN_BASE_URL") or "https://api.devin.ai",
            snapshot_id=env_value("DEVIN_SNAPSHOT_ID") or None,
            repos=configured_repos(),
            playbook_id=env_value("DEVIN_PLAYBOOK_ID") or None,
        )

    def _org(self, path: str) -> str:
        return f"/v3/organizations/{self.org_id}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        if response.status_code >= 400:
            detail = response.text.strip()[:800] or response.reason_phrase
            raise DevinError(f"Devin API {response.status_code} on {path}: {detail}")
        if not response.content:
            return {}
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.content

    def create_session(
        self,
        prompt: str,
        title: str,
        playbook_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": prompt,
            "title": title[:120],
            "tags": ["sandbox"],
        }
        if self.snapshot_id:
            body["snapshot_id"] = self.snapshot_id
        selected_playbook = playbook_id or self.playbook_id
        if selected_playbook:
            body["playbook_id"] = selected_playbook
        if self.repos:
            body["repos"] = self.repos
        try:
            return self._create(body)
        except DevinError as error:
            if "repos" in body and "422" in str(error):
                body.pop("repos", None)
                return self._create(body)
            raise

    def list_playbooks(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            params: dict[str, str | int] = {"first": 200}
            if after:
                params["after"] = after
            data = self._request("GET", self._org("/playbooks"), params=params)
            page = _as_items(data)
            items.extend(page)
            if not isinstance(data, dict) or not data.get("has_next_page"):
                return items
            next_cursor = data.get("end_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                return items
            after = next_cursor

    def get_playbook(self, playbook_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            self._org(f"/playbooks/{quote(playbook_id, safe='')}"),
        )

    def _create(self, body: dict[str, Any]) -> dict[str, Any]:
        data = self._request("POST", self._org("/sessions"), json=body)
        if not isinstance(data, dict) or not data.get("session_id"):
            raise DevinError(f"Devin create-session returned no session_id: {data!r}")
        return data

    def get_session(self, session_id: str) -> dict[str, Any]:
        candidates = [session_id]
        bare = session_id.removeprefix("devin-")
        if session_id.startswith("devin-"):
            candidates.append(bare)
        else:
            candidates.append(f"devin-{session_id}")
        last_error: DevinError | None = None
        for candidate in candidates:
            try:
                data = self._request("GET", self._org(f"/sessions/{candidate}"))
            except DevinError as error:
                last_error = error
                if "404" not in str(error):
                    raise
                continue
            if not isinstance(data, dict):
                raise DevinError("Devin get-session returned a non-object")
            return data
        raise last_error or DevinError(f"Devin session not found: {session_id}")

    def send_message(self, session_id: str, message: str) -> None:
        self._request(
            "POST",
            self._org(f"/sessions/{session_id}/messages"),
            json={"message": message},
        )

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            self._org(f"/sessions/{session_id}/messages"),
            params={"first": 200},
        )
        return _as_items(data)

    def list_attachments(self, session_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", self._org(f"/sessions/{session_id}/attachments"))
        return _as_items(data)

    def download(self, url: str) -> bytes:
        errors: list[str] = []
        parsed = attachment_ref(url)
        if parsed:
            uuid, name = parsed
            try:
                return self._download_api(uuid, name)
            except Exception as error:
                errors.append(str(error))
        try:
            return self._download_url(url)
        except Exception as error:
            errors.append(str(error))
        raise DevinError("attachment download failed: " + " | ".join(errors))

    def _download_api(self, uuid: str, name: str) -> bytes:
        path = self._org(f"/attachments/{uuid}/{name}")
        response = self._http.get(path)
        return self._body_or_redirect(response, path)

    def _download_url(self, url: str) -> bytes:
        response = self._http.get(url)
        return self._body_or_redirect(response, url)

    def _body_or_redirect(self, response: httpx.Response, source: str) -> bytes:
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise DevinError(f"attachment redirect from {source} had no Location")
            return _get_presigned(location, self._timeout)
        if response.status_code in {401, 403}:
            return _get_presigned(str(response.request.url), self._timeout)
        if response.status_code >= 400:
            raise DevinError(f"attachment download failed ({response.status_code}) for {source}")
        return response.content


def attachment_ref(url: str) -> tuple[str, str] | None:
    path = unquote(urlparse(url).path)
    match = APP_ATTACHMENT.search(path)
    if not match:
        return None
    return match.group("uuid"), match.group("name")


def normalize_session_ref(value: str) -> tuple[str, str]:
    text = value.strip()
    if "/sessions/" in text:
        session_id = text.rstrip("/").rsplit("/", 1)[-1]
        url = text if text.startswith("http") else f"https://app.devin.ai/sessions/{session_id}"
        return session_id, url
    session_id = text.removeprefix("devin-")
    return session_id, f"https://app.devin.ai/sessions/{session_id}"


def _get_presigned(url: str, timeout: float) -> bytes:
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    if response.status_code >= 400:
        raise DevinError(f"attachment download failed ({response.status_code})")
    return response.content


def _as_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "attachments", "messages"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _missing_message(missing: list[str]) -> str:
    return (
        "This product runs science in a Devin Cloud sandbox, not on this Mac. "
        f"Set {', '.join(missing)} and restart the API. "
        "Do not install mmseqs or mkdssp locally for the job path."
    )
