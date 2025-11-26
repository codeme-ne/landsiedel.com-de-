#!/usr/bin/env python3
"""Interactive web interface for browsing translation outputs."""
from __future__ import annotations

import argparse
import errno
import json
import logging
import shutil
import sys
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from src.templates import render_template

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ViewerState:
    """Holds resolved directories for serving the web viewer."""

    source_dir: Path
    target_dir: Path

    def __post_init__(self) -> None:
        if not self.source_dir.is_dir():
            raise FileNotFoundError(
                f"Source directory not found: {self.source_dir!s}"
            )
        if not self.target_dir.is_dir():
            raise FileNotFoundError(
                f"Target directory not found: {self.target_dir!s}"
            )


LANGUAGE_LABELS = {
    "de": "Deutsch",
    "en": "English",
}


@dataclass(frozen=True)
class PackageInfo:
    """Metadata describing a downloadable archive for a language directory."""

    language: str
    directory: Path
    archive_path: Path

    @property
    def filename(self) -> str:
        return self.archive_path.name

    @property
    def label(self) -> str:
        base = LANGUAGE_LABELS.get(self.language, self.language.upper())
        return f"{base} ({self.directory.name})"

    @property
    def url(self) -> str:
        return f"/packages/{self.filename}"


def build_file_tree(directory: Path, *, base: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Build a tree representation of files under ``directory``.

    Args:
        directory: The directory to scan.
        base: Base path used to compute relative paths. Defaults to ``directory``.

    Returns:
        A list of dictionaries describing each entry in lexical order with
        directories preceding files.
    """
    if base is None:
        base = directory

    entries: List[Dict[str, Any]] = []
    for child in sorted(
        directory.iterdir(),
        key=lambda path: (path.is_file(), path.name.lower()),
    ):
        if child.is_dir():
            subtree = build_file_tree(child, base=base)
            entries.append(
                {
                    "type": "directory",
                    "name": child.name,
                    "path": str(child.relative_to(base).as_posix()),
                    "children": subtree,
                }
            )
        elif child.is_file():
            entries.append(
                {
                    "type": "file",
                    "name": child.name,
                    "path": str(child.relative_to(base).as_posix()),
                }
            )
    return entries


def _safe_relative_path(raw_path: str) -> Path:
    """
    Convert a user-provided path into a safe relative ``Path`` within the project.

    Raises:
        ValueError: If the path is absolute or attempts directory traversal.
    """
    try:
        pure = PurePosixPath(raw_path)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError("Invalid path encoding") from exc

    if pure.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    if any(part in ("..", "") for part in pure.parts):
        raise ValueError("Path traversal is not allowed")

    return Path(*pure.parts)


def load_document(state: ViewerState, relative_path: Path) -> Dict[str, Any]:
    """Load source and translated HTML for ``relative_path``."""
    source_file = (state.source_dir / relative_path).resolve()
    target_file = (state.target_dir / relative_path).resolve()

    if not source_file.is_file():
        raise FileNotFoundError(f"Source file missing: {relative_path!s}")
    if not target_file.is_file():
        raise FileNotFoundError(f"Target file missing: {relative_path!s}")

    if state.source_dir not in source_file.parents:
        raise ValueError("Source path escapes configured directory")
    if state.target_dir not in target_file.parents:
        raise ValueError("Target path escapes configured directory")

    return {
        "path": relative_path.as_posix(),
        "source": {
            "language": "de",
            "html": source_file.read_text(encoding="utf-8"),
        },
        "target": {
            "language": "en",
            "html": target_file.read_text(encoding="utf-8"),
        },
    }


def ensure_packages(state: ViewerState, output_root: Path) -> List[PackageInfo]:
    """
    Create ZIP archives for the source and target directories to enable downloads.
    """
    packages_dir = output_root / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)

    packages: List[PackageInfo] = []
    for language, directory in (("de", state.source_dir), ("en", state.target_dir)):
        base_name = f"{language}-{directory.name}"
        archive_base = packages_dir / base_name
        archive_path = shutil.make_archive(
            str(archive_base),
            "zip",
            root_dir=directory.parent,
            base_dir=directory.name,
        )
        packages.append(
            PackageInfo(
                language=language,
                directory=directory,
                archive_path=Path(archive_path),
            )
        )
    return packages


class ViewerRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves the interactive viewer."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_index()
        elif parsed.path == "/api/tree":
            self._serve_tree()
        elif parsed.path == "/api/meta":
            self._serve_meta()
        elif parsed.path == "/api/document":
            self._serve_document(parsed)
        elif parsed.path.startswith("/packages/"):
            self._serve_package(parsed.path.split("/packages/", 1)[1])
        else:
            self._send_not_found("Endpoint not found")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        LOGGER.info("%s - %s", self.client_address[0], format % args)

    @property
    def state(self) -> ViewerState:
        return getattr(self.server, "viewer_state")  # type: ignore[attr-defined]

    @property
    def packages(self) -> Sequence[PackageInfo]:
        return getattr(self.server, "viewer_packages", [])  # type: ignore[attr-defined]

    def _serve_index(self) -> None:
        content = FRONTEND_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_tree(self) -> None:
        tree = {
            "type": "directory",
            "name": self.state.source_dir.name,
            "path": "",
            "children": build_file_tree(self.state.source_dir),
        }
        self._send_json(tree)

    def _serve_meta(self) -> None:
        payload = {
            "packages": [
                {
                    "language": package.language,
                    "label": package.label,
                    "filename": package.filename,
                    "url": package.url,
                }
                for package in self.packages
            ]
        }
        self._send_json(payload)

    def _serve_document(self, parsed_url) -> None:
        params = parse_qs(parsed_url.query)
        raw_path = params.get("path", [""])[0]
        if not raw_path:
            self._send_error(400, "Missing 'path' parameter")
            return

        try:
            rel_path = _safe_relative_path(unquote(raw_path))
            payload = load_document(self.state, rel_path)
        except ValueError as exc:
            self._send_error(400, str(exc))
            return
        except FileNotFoundError as exc:
            self._send_error(404, str(exc))
            return

        self._send_json(payload)

    def _serve_package(self, package_fragment: str) -> None:
        package_name = PurePosixPath(package_fragment).name
        if not package_name:
            self._send_not_found("Package not found")
            return

        package = next(
            (pkg for pkg in self.packages if pkg.filename == package_name),
            None,
        )
        if not package or not package.archive_path.is_file():
            self._send_not_found("Package not found")
            return

        file_path = package.archive_path
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{file_path.name}"',
        )
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()

        with file_path.open("rb") as stream:
            shutil.copyfileobj(stream, self.wfile)

    def _send_not_found(self, message: str) -> None:
        self._send_error(404, message)

    def _send_error(self, status: int, message: str) -> None:
        payload = {"error": message}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def parse_arguments(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for the web viewer."""
    parser = argparse.ArgumentParser(
        description="Serve an interactive translation viewer."
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Root output directory containing language subdirectories (default: output)",
    )
    parser.add_argument(
        "--source-subdir",
        default=None,
        help="Original-language subdirectory. Auto-detects from de_NEW, de.",
    )
    parser.add_argument(
        "--target-subdir",
        default=None,
        help="Translated subdirectory. Auto-detects from en_NEW, en.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Automatically open the viewer in the default browser",
    )
    parser.add_argument(
        "--port-attempts",
        type=int,
        default=5,
        help="Number of consecutive ports to try if the preferred one is busy (default: 5)",
    )
    return parser.parse_args(argv)


def create_http_server(
    host: str,
    port: int,
    attempts: int,
    state: ViewerState,
    packages: Sequence[PackageInfo],
) -> tuple[ThreadingHTTPServer, int]:
    """
    Create an HTTP server, retrying consecutive ports if the preferred port is in use.
    """
    attempts = max(1, attempts)
    last_error: Optional[OSError] = None

    for offset in range(attempts):
        candidate = port + offset
        try:
            httpd = ThreadingHTTPServer((host, candidate), ViewerRequestHandler)
        except OSError as exc:
            last_error = exc
            if exc.errno == errno.EADDRINUSE:
                LOGGER.warning(
                    "Port %s is busy on %s – trying next port (attempt %s/%s)",
                    candidate,
                    host,
                    offset + 1,
                    attempts,
                )
                continue
            raise

        httpd.viewer_state = state  # type: ignore[attr-defined]
        httpd.viewer_packages = list(packages)  # type: ignore[attr-defined]
        return httpd, candidate

    assert last_error is not None  # pragma: no cover - defensive
    raise last_error


def resolve_language_dir(
    output_dir: Path,
    explicit: Optional[str],
    candidates: Sequence[str],
    role: str,
) -> Path:
    """
    Resolve a language directory based on CLI input or known candidate names.

    Args:
        output_dir: The root output directory.
        explicit: Optional explicit subdirectory supplied by the user.
        candidates: Preferred subdirectory names, in order.
        role: Human-readable label for error messages (e.g. ``"source"``).

    Raises:
        FileNotFoundError: If no matching directory can be resolved.
    """
    if explicit:
        return (output_dir / explicit).expanduser().resolve()

    for name in candidates:
        candidate = (output_dir / name)
        if candidate.is_dir():
            LOGGER.info("Resolved %s directory: %s", role, candidate)
            return candidate.resolve()

    raise FileNotFoundError(
        f"No {role} directory found under {output_dir}. "
        f"Provide --{'source' if role == 'source' else 'target'}-subdir."
    )


def run_server(
    state: ViewerState,
    host: str,
    port: int,
    open_browser: bool,
    port_attempts: int,
    packages: Sequence[PackageInfo],
) -> None:
    """Start the HTTP server and optionally open the browser."""
    httpd, bound_port = create_http_server(host, port, port_attempts, state, packages)

    LOGGER.info("Serving viewer at http://%s:%s", host, bound_port)
    LOGGER.info(
        "Source directory: %s", state.source_dir
    )
    LOGGER.info(
        "Target directory: %s", state.target_dir
    )
    for package in packages:
        LOGGER.info(
            "Download package ready: %s -> %s",
            package.label,
            package.archive_path,
        )

    if open_browser:
        threading.Thread(
            target=lambda: webbrowser.open(f"http://{host}:{bound_port}/"),
            daemon=True,
        ).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down viewer...")
    finally:
        httpd.server_close()


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Entry point for running the web viewer."""
    args = parse_arguments(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        source_dir = resolve_language_dir(
            output_dir, args.source_subdir, ("de_NEW", "de"), "source"
        )
        target_dir = resolve_language_dir(
            output_dir, args.target_subdir, ("en_NEW", "en"), "target"
        )
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 2

    state = ViewerState(source_dir=source_dir, target_dir=target_dir)

    try:
        packages = ensure_packages(state, output_dir)
    except OSError as exc:
        LOGGER.error("Failed to create download packages: %s", exc)
        return 4

    try:
        run_server(
            state,
            args.host,
            args.port,
            bool(args.open_browser),
            args.port_attempts,
            packages,
        )
    except OSError as exc:
        LOGGER.error(
            "Unable to start server after trying %s port(s): %s",
            args.port_attempts,
            exc,
        )
        return 3
    return 0


def _get_frontend_html() -> str:
    """Generate the frontend HTML for the web viewer."""
    script_vars = """
        let currentDocument = null;"""

    script_functions = """
        function getDocumentHtml(language) {
            if (!currentDocument) return "";
            if (language === "de") {
                return currentDocument.source.html;
            }
            return currentDocument.target.html;
        }

        function applyCurrentDocument() {
            if (!currentDocument) {
                frame.srcdoc = "";
                openTabBtn.disabled = true;
                return;
            }
            frame.srcdoc = getDocumentHtml(currentLanguage);
            openTabBtn.disabled = false;
        }"""

    on_file_click = """const path = element.dataset.path;
            clearActive();
            element.classList.add("active");
            activePath = path;
            currentPathEl.textContent = path;
            currentDocument = null;
            applyCurrentDocument();
            showMessage("Lade Inhalte …");
            try {
                const response = await fetch(`/api/document?path=${encodeURIComponent(path)}`);
                if (!response.ok) {
                    const error = await response.json();
                    showError(error.error || `Fehler ${response.status}`);
                    return;
                }
                const data = await response.json();
                currentDocument = data;
                applyCurrentDocument();
                clearMessage();
            } catch (error) {
                console.error(error);
                showError("Netzwerkfehler – bitte später erneut versuchen.");
            }"""

    on_lang_change = """if (currentDocument) {
                applyCurrentDocument();
            }"""

    on_open_tab = """if (!currentDocument) return;
            const html = getDocumentHtml(currentLanguage);
            const newWindow = window.open();
            if (newWindow) {
                newWindow.document.write(html);
                newWindow.document.close();
            } else {
                showError("Pop-up blockiert – bitte Pop-ups erlauben.");
            }"""

    return render_template(
        "viewer.html",
        META_TAGS="",
        IFRAME_ATTRS='sandbox="allow-same-origin"',
        SCRIPT_VARS=script_vars,
        SCRIPT_FUNCTIONS=script_functions,
        ON_FILE_CLICK=on_file_click,
        TREE_URL="/api/tree",
        META_URL="/api/meta",
        ON_LANG_CHANGE=on_lang_change,
        ON_OPEN_TAB=on_open_tab,
    )


FRONTEND_HTML = _get_frontend_html()


if __name__ == "__main__":
    sys.exit(main())
