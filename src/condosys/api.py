"""Local HTTP API for the desktop app (Electron).

Security model: listens on the loopback interface only and every request must carry the
``X-Condosys-Token`` header with the token the desktop app generated for this session
(environment variable ``CONDOSYS_API_TOKEN``). That keeps other local programs and web
pages opened in a browser away from the certificates.

On start-up it prints one JSON line to stdout, ``{"event": "ready", "port": N}``, which
the desktop app waits for.
"""

import json
import logging
import os
import secrets
import socket
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from condosys import __version__
from condosys.config_loader import ConfigError, save_condominiums
from condosys.credentials import CredentialStoreError
from condosys.documents import format_cnpj, normalize_cnpj
from condosys.exporters.excel import build_output_path, export_results
from condosys.models import Competence, Condominium, RunResult
from condosys.services.certificates import (
    CertificateServiceError,
    CertificateStatus,
    add_certificate,
    certificate_status,
    forget_password,
    list_certificates,
)
from condosys.services.collect import collect_all
from condosys.services.condominiums import load_or_empty, sync_from_certificates
from condosys.settings import Settings

logger = logging.getLogger(__name__)

TOKEN_HEADER = "X-Condosys-Token"


# --- schemas --------------------------------------------------------------------------------


class CertificateOut(BaseModel):
    """Certificate row for the UI."""

    file_name: str
    state: str
    has_password: bool
    holder_name: str | None = None
    cnpj: str | None = None
    issuer: str | None = None
    not_after: str | None = None
    days_to_expire: int | None = None
    error: str | None = None


class CertificateIn(BaseModel):
    """A ``.pfx`` chosen in the UI (local path) and its password."""

    path: str
    password: str
    name: str | None = None
    overwrite: bool = False


class CondominiumOut(BaseModel):
    """Condominium row for the UI."""

    cnpj: str
    cnpj_formatted: str
    name: str
    active: bool
    certificate: str
    notes: str
    certificate_state: str
    certificate_message: str | None = None


class CondominiumUpdate(BaseModel):
    """Editable fields of a condominium."""

    active: bool | None = None
    notes: str | None = None


class CollectIn(BaseModel):
    """Collection request."""

    competence: str
    cnpjs: list[str] | None = None
    sync: bool = True


class JobOut(BaseModel):
    """Collection job state."""

    id: str
    status: Literal["running", "done", "error"]
    competence: str
    current: int
    total: int
    log: list[str]
    results: list[dict[str, Any]]
    output_file: str | None = None
    error: str | None = None


# --- jobs ---------------------------------------------------------------------------------


@dataclass
class _Job:
    id: str
    competence: Competence
    total: int
    status: Literal["running", "done", "error"] = "running"
    current: int = 0
    log: list[str] = field(default_factory=list)
    results: list[RunResult] = field(default_factory=list)
    output_file: Path | None = None
    error: str | None = None

    def out(self) -> JobOut:
        return JobOut(
            id=self.id,
            status=self.status,
            competence=self.competence.label,
            current=self.current,
            total=self.total,
            log=list(self.log),
            results=[_result_summary(r) for r in self.results],
            output_file=str(self.output_file) if self.output_file else None,
            error=self.error,
        )


def _result_summary(result: RunResult) -> dict[str, Any]:
    def total(attr: str) -> str:
        return str(sum((getattr(i, attr) for i in result.invoices), Decimal("0")))

    return {
        "name": result.condominium_name,
        "cnpj": format_cnpj(result.condominium_cnpj),
        "success": result.success,
        "error": result.error,
        "invoices": len(result.invoices),
        "amount": total("amount"),
        "inss": total("inss"),
        "csrf": total("social_contributions_withheld"),
        "iss_withheld": total("iss_withheld"),
    }


def _certificate_out(status: CertificateStatus) -> CertificateOut:
    info = status.info
    return CertificateOut(
        file_name=status.file_name,
        state=status.state,
        has_password=status.has_password,
        holder_name=info.holder_name if info else None,
        cnpj=format_cnpj(info.cnpj) if info and info.cnpj else None,
        issuer=info.issuer if info else None,
        not_after=info.not_after.date().isoformat() if info else None,
        days_to_expire=info.days_to_expire() if info else None,
        error=status.error,
    )


# --- app ------------------------------------------------------------------------------------


def create_app(settings: Settings, token: str) -> FastAPI:
    """Builds the API bound to one settings object and session token."""
    app = FastAPI(title="condosys", version=__version__, docs_url=None, redoc_url=None)
    jobs: dict[str, _Job] = {}
    lock = threading.Lock()

    def check_token(x_condosys_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_condosys_token, token):
            raise HTTPException(status_code=401, detail="token inválido")

    auth = [Depends(check_token)]

    def user_error(exc: Exception, status: int = 400) -> HTTPException:
        return HTTPException(status_code=status, detail=str(exc))

    @app.get("/api/health", dependencies=auth)
    def health() -> dict[str, str]:
        return {
            "version": __version__,
            "base_dir": str(settings.base_dir),
            "certs_dir": str(settings.certs_dir),
            "output_dir": str(settings.output_dir),
        }

    @app.get("/api/certificates", dependencies=auth)
    def get_certificates() -> list[CertificateOut]:
        try:
            return [_certificate_out(s) for s in list_certificates(settings)]
        except CredentialStoreError as exc:
            raise user_error(exc, 503) from exc

    @app.post("/api/certificates", dependencies=auth)
    def post_certificate(body: CertificateIn) -> CertificateOut:
        try:
            info = add_certificate(
                settings, Path(body.path), body.password, name=body.name, overwrite=body.overwrite
            )
            return _certificate_out(certificate_status(settings, info.file_name))
        except FileNotFoundError as exc:
            raise user_error(exc) from exc
        except CertificateServiceError as exc:
            raise user_error(exc) from exc
        except CredentialStoreError as exc:
            raise user_error(exc, 503) from exc

    @app.delete("/api/certificates/{file_name}/password", dependencies=auth)
    def delete_certificate_password(file_name: str) -> dict[str, bool]:
        try:
            return {"removed": forget_password(file_name)}
        except CredentialStoreError as exc:
            raise user_error(exc, 503) from exc

    def condominiums_out() -> list[CondominiumOut]:
        rows = []
        for c in load_or_empty(settings):
            status = certificate_status(settings, c.certificate)
            message = status.error
            state = status.state
            if (settings.certs_dir / c.certificate).is_file() is False:
                state, message = "erro", f"{c.certificate} não está em certs/"
            elif status.info and status.info.cnpj and status.info.cnpj[:8] != c.cnpj[:8]:
                state, message = "erro", f"certificado de outro CNPJ ({status.info.holder_name})"
            rows.append(
                CondominiumOut(
                    cnpj=c.cnpj,
                    cnpj_formatted=c.cnpj_formatted,
                    name=c.name,
                    active=c.active,
                    certificate=c.certificate,
                    notes=c.notes,
                    certificate_state=state,
                    certificate_message=message,
                )
            )
        return rows

    @app.get("/api/condominiums", dependencies=auth)
    def get_condominiums() -> list[CondominiumOut]:
        try:
            return condominiums_out()
        except ConfigError as exc:
            raise user_error(exc) from exc
        except CredentialStoreError as exc:
            raise user_error(exc, 503) from exc

    @app.post("/api/condominiums/sync", dependencies=auth)
    def post_sync() -> dict[str, Any]:
        try:
            summary = sync_from_certificates(settings)
        except ConfigError as exc:
            raise user_error(exc) from exc
        except CredentialStoreError as exc:
            raise user_error(exc, 503) from exc
        return {
            "added": [c.name for c in summary.added],
            "updated": [c.name for c in summary.updated],
            "skipped": summary.skipped,
        }

    @app.patch("/api/condominiums/{cnpj}", dependencies=auth)
    def patch_condominium(cnpj: str, body: CondominiumUpdate) -> CondominiumOut:
        key = normalize_cnpj(cnpj)
        try:
            current = load_or_empty(settings)
        except ConfigError as exc:
            raise user_error(exc) from exc
        changes: dict[str, Any] = body.model_dump(exclude_none=True)
        updated: list[Condominium] = []
        found = False
        for c in current:
            if c.cnpj == key:
                c = c.model_copy(update=changes)
                found = True
            updated.append(c)
        if not found:
            raise HTTPException(status_code=404, detail="condomínio não encontrado")
        save_condominiums(settings.config_file, updated)
        return next(r for r in condominiums_out() if r.cnpj == key)

    def run_job(job: _Job, targets: list[Condominium], sync: bool) -> None:
        def progress(index: int, total: int, condominium: Condominium, message: str) -> None:
            job.current = index
            job.log.append(f"[{index}/{total}] {condominium.name}: {message}")

        try:
            job.results = collect_all(
                settings, targets, job.competence, sync=sync, progress=progress
            )
            job.output_file = export_results(
                job.results,
                job.competence,
                build_output_path(settings.output_dir, job.competence, datetime.now()),
            )
            job.log.append(f"Planilha gerada: {job.output_file}")
            job.status = "done"
        except Exception as exc:  # report anything to the UI instead of a silent thread death
            logger.exception("Falha na coleta")
            job.error = str(exc)
            job.status = "error"

    @app.post("/api/jobs/collect", dependencies=auth)
    def post_collect(body: CollectIn) -> JobOut:
        try:
            competence = Competence.parse(body.competence)
        except ValueError as exc:
            raise user_error(exc) from exc
        with lock:
            if any(j.status == "running" for j in jobs.values()):
                raise HTTPException(status_code=409, detail="já existe uma coleta em andamento")
            try:
                rows = load_or_empty(settings)
            except ConfigError as exc:
                raise user_error(exc) from exc
            if body.cnpjs:
                wanted = {normalize_cnpj(c) for c in body.cnpjs}
                targets = [c for c in rows if c.cnpj in wanted]
            else:
                targets = [c for c in rows if c.active]
            if not targets:
                raise user_error(ValueError("nenhum condomínio selecionado/ativo"))
            job = _Job(id=uuid.uuid4().hex[:12], competence=competence, total=len(targets))
            jobs[job.id] = job
        threading.Thread(target=run_job, args=(job, targets, body.sync), daemon=True).start()
        return job.out()

    @app.get("/api/jobs/{job_id}", dependencies=auth)
    def get_job(job_id: str) -> JobOut:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="coleta não encontrada")
        return job.out()

    @app.get("/api/outputs", dependencies=auth)
    def get_outputs() -> list[dict[str, Any]]:
        if not settings.output_dir.is_dir():
            return []
        files = sorted(
            settings.output_dir.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        return [
            {
                "name": p.name,
                "path": str(p),
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes"),
            }
            for p in files[:50]
        ]

    return app


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        port: int = sock.getsockname()[1]
        return port


def _exit_on_stdin_eof() -> None:
    sys.stdin.read()
    os._exit(0)


def run_server(settings: Settings, port: int) -> None:
    """Runs the API until the process is stopped (the desktop app kills it on exit)."""
    if settings.api_host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("a API do condosys só pode escutar na própria máquina (127.0.0.1)")
    token = os.environ.get("CONDOSYS_API_TOKEN") or secrets.token_urlsafe(32)
    if port == 0:
        port = _free_port(settings.api_host)
    app = create_app(settings, token)
    if os.environ.get("CONDOSYS_EXIT_ON_STDIN_EOF") == "1":
        # Started by the desktop app: exit when it goes away, even if it crashed.
        threading.Thread(target=_exit_on_stdin_eof, daemon=True).start()
    print(json.dumps({"event": "ready", "port": port}), flush=True)
    if "CONDOSYS_API_TOKEN" not in os.environ:
        print(f"token desta sessão: {token}", file=sys.stderr, flush=True)
    uvicorn.run(app, host=settings.api_host, port=port, log_level="warning")
