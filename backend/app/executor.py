"""Drive one Devin Cloud sandbox session per scientific job."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.app.artifacts import is_allowed_artifact, job_dir, list_artifacts, media_type
from backend.app.capabilities import artifact_descriptor
from backend.app.chatfilter import clean_body, is_internal
from backend.app.devin import DevinClient, DevinError, SessionClient, normalize_session_ref
from backend.app.models import ArtifactInfo, JobStatus, Speaker
from backend.app.prompt import follow_up_prompt, investigation_prompt
from backend.app.research import validate_synthesis
from backend.app.settings import settings
from backend.app.store import new_event, new_message, store
from backend.app.supabase import supabase

SleepFn = Callable[[float], None]
NowFn = Callable[[], float]

DONE_OK = frozenset({"exit", "finished", "complete", "completed", "suspended"})
DONE_FAIL = frozenset({"error", "expired", "failed"})
TURN_IDLE = frozenset({"waiting_for_user", "finished"})
NEEDS_CONFIRM = "waiting_for_approval"
BUSY_STAGES = frozenset({
    "working",
    "running",
    "new",
    "claimed",
    "resuming",
    "follow-up",
    "import",
    "sandbox",
    "plan",
    "homolog-search",
    "conservation",
    "structure",
    "literature",
    "analysis",
    "simulation",
    "synthesis",
    "rank",
})
CONFIRM_PROMPT = (
    "Devin is waiting for you to confirm the next step. "
    "Reply **yes** to proceed, or tell it what to do instead."
)
FAIL_DETAIL = frozenset({
    "error",
    "usage_limit_exceeded",
    "out_of_credits",
    "out_of_quota",
    "no_quota_allocation",
    "payment_declined",
    "org_usage_limit_exceeded",
    "user_usage_limit_exceeded",
    "total_session_limit_exceeded",
})
STAGE_LABEL = {
    "working": "Working in the sandbox",
    "waiting_for_user": "Waiting for you",
    "waiting_for_approval": "Waiting for approval in the sandbox",
    "finished": "Finished this turn",
    "new": "Starting the sandbox",
    "claimed": "Claiming the sandbox",
    "resuming": "Resuming the sandbox",
    "homolog-search": "Searching homologs",
    "conservation": "Computing conservation",
    "structure": "Reading the deposited structure",
    "literature": "Searching literature and databases",
    "analysis": "Analyzing scientific data",
    "simulation": "Running a sandbox simulation",
    "synthesis": "Synthesizing the investigation",
    "rank": "Ranking candidate sites",
    "follow-up": "Answering",
    "import": "Pulling result files",
    "sandbox": "Working in the sandbox",
}
FILE_LABEL = {
    "research_plan.json": "Research plan arrived",
    "literature_sources.csv": "Literature source table arrived",
    "synthesis.json": "Scientific synthesis arrived",
    "simulation_results.json": "Simulation results arrived",
    "simulation_metrics.csv": "Simulation metrics arrived",
    "analysis_results.json": "Analysis results arrived",
    "analysis_table.csv": "Analysis table arrived",
    "homolog_search.json": "Homolog search results arrived",
    "homologs.fasta": "Homolog sequences arrived",
    "alignment.json": "Alignment finished",
    "alignment.fasta": "Alignment sequences arrived",
    "conservation.json": "Conservation scores arrived",
    "run.json": "Run log arrived",
    "structure_summary.json": "Structure summary arrived",
    "residue_annotations.json": "Residue annotations arrived",
    "candidate_sites.json": "Candidate-site rankings arrived",
    "final_result.json": "Final result arrived",
    "structure.pdb": "Structure coordinates arrived",
}
PROMPT_ECHO = "You are Devin running this investigation"
ATTACHMENT_MARK = re.compile(r"ATTACHMENT:\{.*?\}(?:\s|$)", re.DOTALL)
ATTACHMENT_URL = re.compile(
    r"https://(?:app|api)\.devin\.ai/attachments/[0-9a-fA-F-]{36}/[A-Za-z0-9._-]+"
)


def get_client() -> SessionClient:
    return DevinClient.from_env()


def run_job(
    job_id: str,
    *,
    client: SessionClient | None = None,
    sleep: SleepFn = time.sleep,
    now: NowFn = time.monotonic,
) -> None:
    job = store.get(job_id)
    if job is None:
        return
    try:
        session_client = client or get_client()
        store.update(job_id, status=JobStatus.running, active_agent=Speaker.planner, active_stage="sandbox")
        if job.devin_session_id:
            session_id, session_url = normalize_session_ref(job.devin_session_id)
            store.update(job_id, devin_session_id=session_id, session_url=job.session_url or session_url)
            store.add_event(job_id, new_event("job.started", "Importing existing Devin sandbox session", "sandbox"))
            store.add_message(
                job_id,
                new_message(
                    Speaker.system,
                    "Restoring results from the sandbox.",
                    stage="sandbox",
                ),
            )
            _finish_from_session(job_id, session_client, session_id, sleep, now, wait=False)
            return
        store.add_event(job_id, new_event("job.started", "Opening Devin Cloud sandbox", "sandbox"))
        playbook_attached = False
        if job.playbook_id:
            playbook = _selected_playbook(session_client, job.playbook_id)
            if playbook is None:
                raise DevinError(f"Devin playbook is no longer available: {job.playbook_id}")
            playbook_attached = True
            if job.playbook_title != playbook.get("title"):
                store.update(
                    job_id,
                    playbook_title=str(playbook.get("title") or "") or None,
                )
            _write_artifact(
                job_id,
                job_dir(job_id),
                "protocol.md",
                str(playbook.get("body") or "").encode("utf-8"),
                {},
            )
        session = session_client.create_session(
            investigation_prompt(job.objective, job.capabilities, playbook_attached),
            job.title,
            job.playbook_id,
        )
        session_id = str(session.get("session_id") or "")
        session_url = str(session.get("url") or "")
        if not session_id:
            raise DevinError("Devin did not return a session_id")
        store.update(job_id, devin_session_id=session_id, session_url=session_url or None)
        store.add_message(
            job_id,
            new_message(
                Speaker.planner,
                "Opened the sandbox. I'll post results here as they land.",
                stage="sandbox",
            ),
        )
        _finish_from_session(job_id, session_client, session_id, sleep, now, wait=True)
    except Exception as error:
        store.update(
            job_id,
            status=JobStatus.failed,
            error=str(error),
            active_agent=None,
            active_stage=None,
            artifacts=list_artifacts(job_id),
        )
        store.add_event(job_id, new_event("job.failed", str(error)))
        store.add_message(job_id, new_message(Speaker.system, f"Sandbox job failed: {error}", stage="error"))


def answer_follow_up(
    job_id: str,
    body: str,
    *,
    client: SessionClient | None = None,
    sleep: SleepFn = time.sleep,
    now: NowFn = time.monotonic,
) -> None:
    job = store.get(job_id)
    if job is None:
        return
    session_id = job.devin_session_id
    if not session_id:
        store.add_message(
            job_id,
            new_message(Speaker.system, "No Devin sandbox session is attached to this job.", stage="error"),
        )
        return
    try:
        session_client = client or get_client()
        store.update(
            job_id,
            status=JobStatus.running,
            active_agent=Speaker.reviewer,
            active_stage="follow-up",
            error=None,
        )
        store.add_event(job_id, new_event("stage.started", "Sending follow-up to the sandbox", "follow-up"))
        session_client.send_message(
            session_id,
            follow_up_prompt(body, job.capabilities),
        )
        _finish_from_session(
            job_id,
            session_client,
            session_id,
            sleep,
            now,
            wait=True,
            wait_for_new_work=True,
            complete_message="Follow-up complete",
        )
    except Exception as error:
        _fail_or_keep_results(job_id, error, "Follow-up failed")


def import_session(
    job_id: str,
    *,
    client: SessionClient | None = None,
    sleep: SleepFn = time.sleep,
    now: NowFn = time.monotonic,
) -> None:
    job = store.get(job_id)
    if job is None or not job.devin_session_id:
        return
    try:
        session_client = client or get_client()
        session_id, session_url = normalize_session_ref(job.devin_session_id)
        store.update(
            job_id,
            status=JobStatus.running,
            active_agent=Speaker.reviewer,
            active_stage="import",
            session_url=job.session_url or session_url,
            error=None,
        )
        store.add_event(job_id, new_event("stage.started", "Pulling artifacts from the sandbox", "import"))
        _finish_from_session(job_id, session_client, session_id, sleep, now, wait=False, complete_message="Imported sandbox artifacts")
    except Exception as error:
        store.update(
            job_id,
            status=JobStatus.failed,
            error=str(error),
            active_agent=None,
            active_stage=None,
            artifacts=list_artifacts(job_id),
        )
        store.add_event(job_id, new_event("job.failed", str(error)))
        store.add_message(job_id, new_message(Speaker.system, f"Import failed: {error}", stage="error"))


def resume_running_jobs() -> None:
    for job in store.list():
        if job.status != JobStatus.running or not job.devin_session_id:
            continue
        try:
            client = get_client()
            session_id, session_url = normalize_session_ref(job.devin_session_id)
            store.update(job.id, session_url=job.session_url or session_url)
            _finish_from_session(
                job.id,
                client,
                session_id,
                time.sleep,
                time.monotonic,
                wait=True,
                wait_for_new_work=False,
                complete_message="Sandbox turn complete",
            )
        except Exception as error:
            _fail_or_keep_results(job.id, error, "Resume failed")


def _fail_or_keep_results(job_id: str, error: Exception, prefix: str) -> None:
    artifacts = list_artifacts(job_id)
    if _has_science(artifacts):
        store.update(
            job_id,
            status=JobStatus.complete,
            error=str(error),
            active_agent=None,
            active_stage=None,
            artifacts=artifacts,
        )
        store.add_event(job_id, new_event("agent.error", f"{prefix}: {error}"))
        store.add_message(
            job_id,
            new_message(
                Speaker.planner,
                "Could not reach the sandbox just now. The earlier results are still on the right. Send the follow-up again.",
                stage="error",
            ),
        )
        return
    store.update(
        job_id,
        status=JobStatus.failed,
        error=str(error),
        active_agent=None,
        active_stage=None,
        artifacts=artifacts,
    )
    store.add_event(job_id, new_event("job.failed", str(error)))
    store.add_message(job_id, new_message(Speaker.system, f"{prefix}: {error}", stage="error"))


_last_sync: dict[str, float] = {}
_last_harvest: dict[str, float] = {}
HARVEST_EVERY = 3.0


def job_is_busy(job: object) -> bool:
    status = getattr(job, "status", None)
    stage = getattr(job, "active_stage", None) or "working"
    if status == JobStatus.queued:
        return True
    if status != JobStatus.running:
        return False
    return stage in BUSY_STAGES


def sync_job(job_id: str) -> None:
    job = store.get(job_id)
    if job is None or not job.devin_session_id:
        return
    now = time.monotonic()
    if now - _last_sync.get(job_id, 0) < settings.poll_interval_seconds:
        return
    _last_sync[job_id] = now
    try:
        client = get_client()
        session_id, _ = normalize_session_ref(job.devin_session_id)
        session = client.get_session(session_id)
    except Exception:
        return
    status, detail = _status_fields(session)
    _set_stage(job_id, status, detail)
    try:
        _ingest_messages(job_id, client, session_id)
        due = now - _last_harvest.get(job_id, 0) >= HARVEST_EVERY
        closing = job.status == JobStatus.running and _turn_complete(status, detail)
        if job.status == JobStatus.running and (due or closing):
            _harvest(job_id, client, session_id, session, {}, force=False, scan_messages=closing)
            _last_harvest[job_id] = now
    except Exception:
        pass
    if _is_failed(status, detail):
        return
    if detail == NEEDS_CONFIRM:
        _hold_for_confirm(job_id)
        return
    if job.status == JobStatus.running and _turn_complete(status, detail) and _assistant_replied_since_user(job_id):
        _complete_job(job_id, "Sandbox turn complete")


def _finish_from_session(
    job_id: str,
    client: SessionClient,
    session_id: str,
    sleep: SleepFn,
    now: NowFn,
    *,
    wait: bool,
    wait_for_new_work: bool = False,
    complete_message: str = "Sandbox investigation complete",
) -> None:
    if wait:
        outcome = _await_session(job_id, client, session_id, sleep, now, wait_for_new_work=wait_for_new_work)
        if outcome == "awaiting":
            return
    else:
        session = client.get_session(session_id)
        _ingest_messages(job_id, client, session_id)
        _harvest(job_id, client, session_id, session, {}, force=False, scan_messages=True)
        status, detail = _status_fields(session)
        if detail == NEEDS_CONFIRM:
            _hold_for_confirm(job_id)
            return
    _complete_job(job_id, complete_message)


def _complete_job(job_id: str, complete_message: str) -> None:
    job = store.get(job_id)
    if job is None or job.status == JobStatus.complete:
        return
    artifacts = list_artifacts(job_id)
    limitations = _limitations(job_id)
    if not _has_science(artifacts) and "No result files arrived from this turn." not in limitations:
        limitations = [*limitations, "No result files arrived from this turn."]
    store.update(
        job_id,
        status=JobStatus.complete,
        active_agent=None,
        active_stage=None,
        artifacts=artifacts,
        limitations=limitations,
        error=None,
    )
    store.add_event(job_id, new_event("job.complete", complete_message))


def _await_session(
    job_id: str,
    client: SessionClient,
    session_id: str,
    sleep: SleepFn,
    now: NowFn,
    *,
    wait_for_new_work: bool,
) -> str:
    started_at = now()
    deadline = started_at + settings.poll_timeout_seconds
    idle_deadline = started_at + settings.poll_idle_timeout_seconds
    known_bytes: dict[str, int] = {}
    last_status_detail: tuple[str, str] | None = None
    last_harvest = 0.0
    saw_work = False
    new_reply = False
    while now() < deadline and now() < idle_deadline:
        session = client.get_session(session_id)
        status, detail = _status_fields(session)
        status_detail = (status, detail)
        if status_detail != last_status_detail:
            _set_stage(job_id, status, detail)
            last_status_detail = status_detail
            idle_deadline = now() + settings.poll_idle_timeout_seconds
        if _is_working(status, detail):
            saw_work = True
            idle_deadline = now() + settings.poll_idle_timeout_seconds
        ingested = _ingest_messages(job_id, client, session_id)
        if ingested:
            new_reply = True
            idle_deadline = now() + settings.poll_idle_timeout_seconds
        closing = _turn_complete(status, detail)
        if closing or now() - last_harvest >= HARVEST_EVERY:
            previous_bytes = dict(known_bytes)
            known_bytes = _harvest(
                job_id,
                client,
                session_id,
                session,
                known_bytes,
                force=False,
                scan_messages=closing,
            )
            last_harvest = now()
            if known_bytes != previous_bytes:
                idle_deadline = now() + settings.poll_idle_timeout_seconds
        if _is_failed(status, detail):
            raise DevinError(session.get("error") or session.get("message") or detail or status)
        if detail == NEEDS_CONFIRM:
            _hold_for_confirm(job_id)
            return "awaiting"
        if closing:
            replied = _assistant_replied_since_user(job_id)
            if wait_for_new_work and not (saw_work or new_reply or replied):
                sleep(settings.poll_interval_seconds)
                continue
            try:
                _ingest_messages(job_id, client, session_id)
                _harvest(job_id, client, session_id, session, known_bytes, force=False, scan_messages=True)
            except Exception:
                pass
            return "done"
        sleep(settings.poll_interval_seconds)
    recovered_reply = False
    recovered_artifacts = False
    try:
        before_bytes = dict(known_bytes)
        recovered_messages = _ingest_messages(job_id, client, session_id)
        new_reply = new_reply or bool(recovered_messages)
        session = client.get_session(session_id)
        known_bytes = _harvest(
            job_id,
            client,
            session_id,
            session,
            known_bytes,
            force=True,
            scan_messages=True,
        )
        recovered_artifacts = known_bytes != before_bytes
        recovered_reply = bool(recovered_messages)
    except Exception:
        pass
    if recovered_artifacts or recovered_reply:
        limitation = (
            "A Devin wait limit was reached after recovering the latest results; "
            "Devin may still be working in the session. Re-check the session for additional outputs."
        )
        job = store.get(job_id)
        if job is not None and limitation not in job.limitations:
            store.update(job_id, limitations=[*job.limitations, limitation])
        return "done"
    raise DevinError(
        "A Devin wait limit was reached, but the session is still live and no new results "
        "were recovered. Re-check the Devin session to fetch results later."
    )


def _status_fields(session: dict[str, Any]) -> tuple[str, str]:
    status = str(session.get("status") or session.get("status_enum") or session.get("state") or "").lower()
    detail = str(session.get("status_detail") or "").lower()
    return status, detail


def _is_failed(status: str, detail: str) -> bool:
    return status in DONE_FAIL or detail in FAIL_DETAIL


def _turn_complete(status: str, detail: str) -> bool:
    if status in DONE_OK:
        return True
    if detail in TURN_IDLE:
        return True
    return False


def _is_working(status: str, detail: str) -> bool:
    if detail == "working":
        return True
    return status in {"new", "claimed", "resuming"}


def _assistant_replied_since_user(job_id: str) -> bool:
    job = store.get(job_id)
    if job is None:
        return False
    last_user = None
    last_assistant = None
    for message in job.messages:
        if message.speaker == Speaker.user:
            last_user = message.created_at
        elif message.speaker != Speaker.system:
            last_assistant = message.created_at
    if last_assistant is None:
        return False
    if last_user is None:
        return True
    return last_assistant >= last_user


def _hold_for_confirm(job_id: str) -> None:
    job = store.get(job_id)
    already = job is not None and job.status == JobStatus.running and job.active_stage == NEEDS_CONFIRM
    store.update(job_id, status=JobStatus.running, active_stage=NEEDS_CONFIRM, error=None)
    if not already:
        store.add_event(job_id, new_event("stage.started", "Waiting for you to confirm the next step", NEEDS_CONFIRM))
    job = store.get(job_id)
    if job is None:
        return
    if any("confirm the next step" in message.body.lower() for message in job.messages):
        return
    store.add_message(job_id, new_message(Speaker.planner, CONFIRM_PROMPT, stage="confirm"))


def _set_stage(job_id: str, status: str, detail: str) -> None:
    job = store.get(job_id)
    stage = detail or status or "working"
    if job is not None and job.active_stage == stage:
        return
    label = STAGE_LABEL.get(stage, STAGE_LABEL.get("working", "Working in the sandbox"))
    store.update(job_id, active_stage=stage)
    store.add_event(job_id, new_event("stage.started", label, stage))


def _ingest_messages(job_id: str, client: SessionClient, session_id: str) -> list[str]:
    job = store.get(job_id)
    if job is None:
        return []
    seen = set(job.seen_devin_ids)
    added: list[str] = []
    for raw in client.list_messages(session_id):
        kind = str(raw.get("type") or raw.get("role") or raw.get("source") or "").lower()
        if kind in {"user_message", "user"}:
            continue
        text = _message_text(raw)
        parsed = _chat_message(text)
        if parsed is None:
            continue
        speaker, body = parsed
        keys = _message_keys(raw, speaker.value, body)
        source_id = str(raw.get("event_id") or raw.get("id") or raw.get("message_id") or "")
        job = store.get(job_id) or job
        existing = _existing_message(job, source_id, body)
        if existing is not None:
            if body != existing.body:
                store.replace_message(job_id, existing.id, body, source_id or existing.source_id)
                added.append(source_id or existing.id)
            seen.update(keys)
            continue
        if seen.intersection(keys) or _fingerprint(body) in {_fingerprint(item.body) for item in job.messages}:
            seen.update(keys)
            continue
        seen.update(keys)
        store.add_message(
            job_id,
            new_message(
                speaker,
                body,
                stage=_stage_for_message(speaker, body),
                source_id=source_id or None,
            ),
        )
        added.append(keys[0])
    store.update(job_id, seen_devin_ids=sorted(seen), active_agent=_latest_agent(job_id))
    return added


def _existing_message(job: object, source_id: str, body: str):
    messages = getattr(job, "messages", [])
    if source_id:
        for message in messages:
            if message.source_id == source_id:
                return message
    for message in reversed(messages):
        if message.speaker in {Speaker.user, Speaker.system}:
            continue
        if body.startswith(message.body) and len(body) > len(message.body):
            return message
    return None


def _message_keys(raw: dict[str, Any], speaker: str, body: str) -> list[str]:
    keys = [
        str(raw[field])
        for field in ("event_id", "id", "message_id")
        if raw.get(field)
    ]
    keys.append(f"{speaker}:{body[:120]}")
    keys.append(_fingerprint(body))
    return keys


def _fingerprint(text: str) -> str:
    return "fp:" + " ".join(text.split())[:180]


def _harvest(
    job_id: str,
    client: SessionClient,
    session_id: str,
    session: dict[str, Any],
    known_bytes: dict[str, int],
    *,
    force: bool = False,
    scan_messages: bool = False,
) -> dict[str, int]:
    out = job_dir(job_id)
    out.mkdir(parents=True, exist_ok=True)
    pending: list[tuple[str, str, int | None]] = []
    for item in client.list_attachments(session_id):
        name = str(item.get("name") or item.get("filename") or "")
        basename = Path(name).name
        url = item.get("url") or item.get("download_url")
        if is_allowed_artifact(basename) and url:
            pending.append((basename, str(url), _remote_size(item)))
    if scan_messages:
        for raw in client.list_messages(session_id):
            for url in ATTACHMENT_URL.findall(_message_text(raw)):
                basename = Path(url).name
                if is_allowed_artifact(basename):
                    pending.append((basename, url, None))
    seen_urls: set[str] = set()
    for basename, url, remote_size in pending:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        path = out / basename
        if path.is_file() and not force:
            local = path.stat().st_size
            if remote_size is None or remote_size == local:
                known_bytes[basename] = local
                continue
        try:
            data = client.download(url)
        except Exception as error:
            store.add_event(
                job_id,
                new_event("agent.error", f"{basename}: {error}", _stage_for_file(basename)),
            )
            continue
        known_bytes = _write_artifact(job_id, out, basename, data, known_bytes)
    payload = session.get("structured_output")
    if isinstance(payload, dict):
        job = store.get(job_id)
        objective = job.objective if job is not None else ""
        try:
            synthesis = validate_synthesis(payload, objective)
        except Exception as error:
            _record_validation_error(job_id, "synthesis.json", str(error))
        else:
            synthesis_path = out / "synthesis.json"
            if not _valid_synthesis_file(synthesis_path, objective):
                known_bytes = _write_artifact(
                    job_id,
                    out,
                    "synthesis.json",
                    json.dumps(synthesis.model_dump(mode="json")).encode("utf-8"),
                    known_bytes,
                )
    if isinstance(payload, dict):
        for key, value in payload.items():
            basename = Path(str(key)).name
            if not is_allowed_artifact(basename):
                continue
            if isinstance(value, (dict, list)):
                data = json.dumps(value).encode("utf-8")
            elif isinstance(value, str):
                data = value.encode("utf-8")
            else:
                continue
            known_bytes = _write_artifact(job_id, out, basename, data, known_bytes)
    artifacts = list_artifacts(job_id)
    limitations = _limitations(job_id)
    job = store.get(job_id)
    changed = (
        job is None
        or _artifact_signature(job.artifacts) != _artifact_signature(artifacts)
        or job.limitations != limitations
    )
    if changed:
        store.update(job_id, artifacts=artifacts, limitations=limitations)
    return known_bytes


def _selected_playbook(client: SessionClient, playbook_id: str) -> dict[str, Any] | None:
    for playbook in client.list_playbooks():
        if str(playbook.get("playbook_id") or "") == playbook_id:
            return playbook
    return None


def _valid_synthesis_file(path: Path, objective: str) -> bool:
    if not path.is_file():
        return False
    try:
        validate_synthesis(json.loads(path.read_text(encoding="utf-8")), objective)
    except Exception:
        return False
    return True


def _record_validation_error(job_id: str, filename: str, error: str) -> None:
    path = job_dir(job_id) / ".validation_errors.json"
    errors: dict[str, str] = {}
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                errors = {str(key): str(item) for key, item in value.items()}
        except (json.JSONDecodeError, OSError):
            pass
    errors[filename] = error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(errors, indent=2), encoding="utf-8")
    supabase.persist_validation_error(job_id, filename, error)


def _remote_size(item: dict[str, Any]) -> int | None:
    for key in ("size", "bytes", "content_length", "contentLength"):
        value = item.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _artifact_signature(items: list[Any]) -> tuple[tuple[str, int], ...]:
    return tuple((str(getattr(item, "filename", "")), int(getattr(item, "bytes", 0))) for item in items)


def _write_artifact(
    job_id: str,
    out: Path,
    basename: str,
    data: bytes,
    known_bytes: dict[str, int],
) -> dict[str, int]:
    path = out / basename
    if path.is_file() and path.stat().st_size == len(data):
        known_bytes[basename] = len(data)
        return known_bytes
    if known_bytes.get(basename) == len(data) and path.is_file():
        return known_bytes
    path.write_bytes(data)
    known_bytes[basename] = len(data)
    descriptor = artifact_descriptor(basename)
    job = store.get(job_id)
    if job is not None:
        supabase.persist_artifact(
            job,
            ArtifactInfo(
                id=f"art_{Path(basename).stem}",
                filename=basename,
                media_type=media_type(basename),
                bytes=len(data),
                stage=descriptor.stage,
                title=descriptor.title,
                purpose=descriptor.purpose,
            ),
            path,
        )
    store.add_event(
        job_id,
        new_event(
            "artifact.ready",
            FILE_LABEL.get(basename, _file_label(basename)),
            _stage_for_file(basename),
            f"art_{Path(basename).stem}",
        ),
    )
    return known_bytes


def _message_text(raw: dict[str, Any]) -> str:
    for key in ("message", "content", "text", "body"):
        value = raw.get(key)
        if isinstance(value, str):
            return value
    return ""


def _chat_message(text: str) -> tuple[Speaker, str] | None:
    if is_internal(text):
        return None
    speaker, body = _speaker_and_body(text)
    body = clean_body(body)
    if not body or is_internal(body):
        return None
    if speaker == Speaker.system:
        return None
    return speaker, body


def _speaker_and_body(text: str) -> tuple[Speaker, str]:
    stripped = text.strip()
    mapping = (
        ("[planner]", Speaker.planner),
        ("[search]", Speaker.search),
        ("[structure]", Speaker.structure),
        ("[design]", Speaker.design),
        ("[reviewer]", Speaker.reviewer),
        ("[system]", Speaker.system),
    )
    lowered = stripped.lower()
    for prefix, speaker in mapping:
        if lowered.startswith(prefix):
            return speaker, stripped[len(prefix) :].strip()
    return Speaker.planner, stripped


def _stage_for(speaker: Speaker) -> str:
    return {
        Speaker.planner: "plan",
        Speaker.search: "homolog-search",
        Speaker.structure: "structure",
        Speaker.design: "rank",
        Speaker.reviewer: "review",
        Speaker.system: "sandbox",
        Speaker.user: "follow-up",
    }.get(speaker, "sandbox")


def _stage_for_message(speaker: Speaker, body: str) -> str:
    text = body.lower()
    markers = (
        ("literature", "literature"),
        ("database search", "literature"),
        ("sequence analysis", "homolog-search"),
        ("homolog", "homolog-search"),
        ("alignment", "homolog-search"),
        ("conservation", "conservation"),
        ("structure analysis", "structure"),
        ("structure", "structure"),
        ("simulation", "simulation"),
        ("docking", "simulation"),
        ("molecular dynamics", "simulation"),
        ("candidate ranking", "rank"),
        ("shortlist", "rank"),
        ("data analysis", "analysis"),
        ("synthesis", "synthesis"),
    )
    matches = (
        (text.find(marker), stage)
        for marker, stage in markers
        if marker in text[:160]
    )
    first = min(matches, default=None, key=lambda item: item[0])
    if first is not None:
        return first[1]
    return _stage_for(speaker)


def _file_label(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
        return f"Figure {filename} arrived"
    if suffix in {".pdb", ".cif"}:
        return f"Structure {filename} arrived"
    if suffix in {".csv", ".tsv"}:
        return f"Table {filename} arrived"
    return f"{filename} arrived"


def _stage_for_file(filename: str) -> str:
    return artifact_descriptor(filename).stage


def _latest_agent(job_id: str) -> Speaker | None:
    job = store.get(job_id)
    if job is None:
        return None
    for message in reversed(job.messages):
        if message.speaker not in {Speaker.user, Speaker.system}:
            return message.speaker
    return Speaker.planner


def _has_science(artifacts: list[Any]) -> bool:
    names = {item.filename for item in artifacts}
    if names & {
        "conservation.json",
        "final_result.json",
        "homolog_search.json",
        "structure.pdb",
        "synthesis.json",
        "simulation_results.json",
        "analysis_results.json",
    }:
        return True
    return any(name.lower().endswith((".png", ".pdb", ".cif", ".csv")) for name in names)


def _limitations(job_id: str) -> list[str]:
    limitations: list[str] = []
    for filename in ("final_result.json", "synthesis.json"):
        path = job_dir(job_id) / filename
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        values = data.get("limitations") if isinstance(data, dict) else None
        if isinstance(values, list):
            limitations.extend(str(item) for item in values)
    if not limitations:
        limitations.append(
            "All reported evidence is retrieved, calculated, or simulated; none is experimental validation."
        )
    return list(dict.fromkeys(limitations))
