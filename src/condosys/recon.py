"""Reconnaissance recorder: saves HTML + screenshot of every page the browser loads.

The material in ``debug/recon/<timestamp>/`` is used to write ``selectors.py``,
``docs/issnet-mapa.md`` and the parser test fixtures. It contains fiscal data: the folder
is git-ignored and must not be shared.

Saved files:
    * ``NNN_<kind>_<slug>.html`` / ``.png`` — main document and full-page screenshot.
    * ``NNN_<kind>_<slug>.frameK.html`` — HTML of each child frame.
    * ``index.jsonl`` — one line per capture (time, kind, URL, title, files).
    * ``requests.log`` — method, type, status and URL of each request (no headers,
      cookies or bodies).
    * ``downloads/`` — files downloaded during the session (e.g. invoice XML/PDF).

Captures happen on every ``load`` event and when the "Capturar" button injected at the
bottom-right of the page is clicked (useful after ASP.NET partial postbacks, which do not
fire ``load``).
"""

import json
import logging
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Download, Page, Request
from playwright.sync_api import Error as PlaywrightError

logger = logging.getLogger(__name__)

BINDING_NAME = "__condosysCapture"
_BUTTON_TAG = "condosys-recon"
_BUTTON_RE = re.compile(rf"<{_BUTTON_TAG}\b[^>]*>.*?</{_BUTTON_TAG}>", re.DOTALL)
_SKIPPED_RESOURCES = {"image", "font", "stylesheet", "media"}
# Short, so a capture racing with the next navigation gives up instead of blocking.
_SCREENSHOT_TIMEOUT_MS = 10_000

# Injected in every page. The button lives in a shadow root so it does not inherit or
# change the portal styles; its element is stripped from the saved HTML.
_BUTTON_SCRIPT = f"""
(() => {{
  if (window.top !== window) return;
  const collect = () => {{
    const frames = [];
    for (const frame of document.querySelectorAll('iframe, frame')) {{
      try {{ frames.push(frame.contentDocument.documentElement.outerHTML); }}
      catch (e) {{ frames.push('<!-- cross-origin frame: ' + frame.src + ' -->'); }}
    }}
    return {{
      url: location.href,
      title: document.title,
      html: '<!DOCTYPE html>\\n' + document.documentElement.outerHTML,
      frames,
    }};
  }};
  const install = () => {{
    if (!document.body || document.querySelector('{_BUTTON_TAG}')) return;
    const host = document.createElement('{_BUTTON_TAG}');
    host.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2147483647';
    const root = host.attachShadow({{mode: 'open'}});
    const button = document.createElement('button');
    button.textContent = 'Capturar';
    button.title = 'condosys recon: salvar HTML desta tela';
    button.style.cssText = 'font:13px sans-serif;padding:6px 10px;border-radius:6px;' +
      'border:1px solid #1f4e78;background:#1f4e78;color:#fff;cursor:pointer;opacity:.85';
    button.addEventListener('click', async (event) => {{
      event.preventDefault();
      event.stopPropagation();
      button.textContent = 'Salvando...';
      await window.{BINDING_NAME}(collect());
      button.textContent = 'Capturado';
      setTimeout(() => (button.textContent = 'Capturar'), 1200);
    }});
    root.appendChild(button);
    document.body.appendChild(host);
  }};
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', install);
  }} else {{
    install();
  }}
}})();
"""


def _slug(url: str) -> str:
    parts = urlsplit(url)
    last = parts.path.rstrip("/").rsplit("/", 1)[-1] or parts.netloc or parts.scheme
    slug = re.sub(r"[^0-9A-Za-z]+", "-", last).strip("-").lower()
    return slug[:60] or "page"


def _strip_button(html: str) -> str:
    return _BUTTON_RE.sub("", html)


class PageRecorder:
    """Records every page of a browser context into a directory."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.downloads_dir = output_dir / "downloads"
        self.count = 0
        self.captures: list[dict[str, Any]] = []
        self._pending_screenshots: deque[tuple[Page, Path]] = deque()
        self._requests_log = output_dir / "requests.log"
        self._index = output_dir / "index.jsonl"

    def attach(self, context: BrowserContext) -> None:
        """Starts recording the context (call before opening pages)."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        context.expose_binding(BINDING_NAME, self._on_button)
        context.add_init_script(_BUTTON_SCRIPT)
        context.on("page", self._attach_page)
        for page in context.pages:
            self._attach_page(page)
        logger.info("Recon gravando em %s", self.output_dir)

    def _attach_page(self, page: Page) -> None:
        page.on("load", self._on_load)
        page.on("requestfinished", self._log_request)
        page.on("requestfailed", self._log_request)
        page.on("download", self._save_download)

    # --- captures ----------------------------------------------------------------------

    def _on_load(self, page: Page) -> None:
        self.capture(page, "load")

    def _next_stem(self, kind: str, url: str) -> str:
        self.count += 1
        return f"{self.count:03d}_{kind}_{_slug(url)}"

    def capture(self, page: Page, kind: str = "manual") -> Path | None:
        """Saves the page HTML, the HTML of its frames and a full-page screenshot.

        Errors (e.g. the page navigated away mid-capture) are logged, never raised.

        Returns:
            Path of the saved main HTML, or None on failure.
        """
        try:
            url = page.url
            stem = self._next_stem(kind, url)
            html_path = self.output_dir / f"{stem}.html"
            html_path.write_text(_strip_button(page.content()), encoding="utf-8")
            files = [html_path.name]
            for number, frame in enumerate(page.frames[1:], start=1):
                try:
                    frame_path = self.output_dir / f"{stem}.frame{number}.html"
                    frame_path.write_text(frame.content(), encoding="utf-8")
                    files.append(frame_path.name)
                except PlaywrightError:
                    continue
            shot_path = self.output_dir / f"{stem}.png"
            page.screenshot(path=shot_path, full_page=True, timeout=_SCREENSHOT_TIMEOUT_MS)
            files.append(shot_path.name)
            self._write_index(kind, url, page.title(), files)
        except PlaywrightError as exc:
            logger.warning("Recon: captura falhou (%s)", str(exc).splitlines()[0])
            return None
        logger.info("Recon: %s capturada (%s)", stem, url[:120])
        return html_path

    def _on_button(self, source: dict[str, Any], snapshot: dict[str, Any]) -> None:
        # Runs inside a binding callback: calling the Playwright API here would deadlock,
        # so the page sends its own HTML and the screenshot is taken later.
        url = str(snapshot.get("url", ""))
        stem = self._next_stem("manual", url)
        html_path = self.output_dir / f"{stem}.html"
        html_path.write_text(_strip_button(str(snapshot.get("html", ""))), encoding="utf-8")
        files = [html_path.name]
        for number, frame_html in enumerate(snapshot.get("frames", []), start=1):
            frame_path = self.output_dir / f"{stem}.frame{number}.html"
            frame_path.write_text(str(frame_html), encoding="utf-8")
            files.append(frame_path.name)
        self._write_index("manual", url, str(snapshot.get("title", "")), files)
        self._pending_screenshots.append((source["page"], self.output_dir / f"{stem}.png"))
        logger.info("Recon: %s capturada pelo botão (%s)", stem, url[:120])

    def flush(self) -> None:
        """Takes the screenshots requested by the "Capturar" button."""
        while self._pending_screenshots:
            page, path = self._pending_screenshots.popleft()
            try:
                page.screenshot(path=path, full_page=True, timeout=_SCREENSHOT_TIMEOUT_MS)
            except PlaywrightError:
                continue

    def _write_index(self, kind: str, url: str, title: str, files: list[str]) -> None:
        entry = {
            "n": self.count,
            "time": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "url": url,
            "title": title,
            "files": files,
        }
        self.captures.append(entry)
        with self._index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # --- network and downloads ---------------------------------------------------------

    def _log_request(self, request: Request) -> None:
        if request.resource_type in _SKIPPED_RESOURCES:
            return
        if request.failure is not None:
            status = f"FAILED {request.failure}"
        else:
            try:
                response = request.response()
            except PlaywrightError:
                response = None
            status = str(response.status) if response is not None else "-"
        line = (
            f"{datetime.now():%H:%M:%S} {request.method:<6} {request.resource_type:<9} "
            f"{status:<6} {request.url}\n"
        )
        with self._requests_log.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _save_download(self, download: Download) -> None:
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*]', "_", download.suggested_filename) or "download"
        target = self.downloads_dir / f"{self.count:03d}_{name}"
        try:
            download.save_as(target)
        except PlaywrightError as exc:
            logger.warning("Recon: download falhou (%s)", str(exc).splitlines()[0])
            return
        logger.info("Recon: download salvo em %s", target)


def new_recon_dir(debug_dir: Path, now: datetime | None = None) -> Path:
    """Returns ``debug/recon/<AAAAMMDD-HHMMSS>/`` (Windows-safe name)."""
    return debug_dir / "recon" / f"{(now or datetime.now()):%Y%m%d-%H%M%S}"
