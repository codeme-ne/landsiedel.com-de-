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


FRONTEND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Translation Viewer</title>
    <style>
        :root {
            color-scheme: light dark;
            --sidebar-width: 320px;
            --border-color: #d0d7de;
            --accent: #2563eb;
            --bg-muted: rgba(37, 99, 235, 0.12);
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        body {
            margin: 0;
            height: 100vh;
            display: flex;
            overflow: hidden;
            background-color: #f1f5f9;
        }
        .sidebar {
            width: var(--sidebar-width);
            border-right: 1px solid var(--border-color);
            overflow-y: auto;
            padding: 1rem;
            background-color: #1f2937;
            color: #f8fafc;
        }
        .sidebar h1 {
            font-size: 1.1rem;
            margin: 0 0 1rem;
            color: #f8fafc;
        }
        .tree {
            font-size: 0.93rem;
        }
        .tree details {
            margin-bottom: 0.35rem;
            padding-left: 0.4rem;
        }
        .tree summary {
            cursor: pointer;
            font-weight: 600;
            color: #e2e8f0;
        }
        .tree summary::marker {
            color: #94a3b8;
        }
        .tree-file {
            width: 100%;
            text-align: left;
            padding: 0.3rem 0.6rem;
            margin: 0.2rem 0;
            cursor: pointer;
            border-radius: 6px;
            border: 1px solid rgba(148, 163, 184, 0.4);
            background-color: rgba(15, 23, 42, 0.35);
            color: #f1f5f9;
            font-size: 0.9rem;
        }
        .tree-file:hover {
            background-color: rgba(37, 99, 235, 0.35);
            border-color: rgba(37, 99, 235, 0.6);
        }
        .tree-file.active {
            border-color: #ffffff;
            background-color: rgba(37, 99, 235, 0.55);
            color: #ffffff;
            font-weight: 600;
        }
        .content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .toolbar {
            border-bottom: 1px solid var(--border-color);
            padding: 1rem 1.25rem;
            background-color: #ffffff;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
        }
        .title-row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
        }
        .toolbar h2 {
            margin: 0;
            font-size: 1.05rem;
            font-weight: 600;
            color: #0f172a;
        }
        .controls {
            display: flex;
            gap: 0.5rem;
            align-items: center;
            flex-wrap: wrap;
        }
        .lang-switch {
            display: inline-flex;
            border: 1px solid var(--border-color);
            border-radius: 999px;
            padding: 0.2rem;
            background-color: #e2e8f0;
        }
        .lang-button {
            border: none;
            background: transparent;
            padding: 0.35rem 0.9rem;
            border-radius: 999px;
            cursor: pointer;
            font-weight: 600;
            color: #1f2937;
        }
        .lang-button.active {
            background-color: var(--accent);
            color: #ffffff;
        }
        .lang-button:not(.active):hover {
            background-color: rgba(37, 99, 235, 0.16);
            color: #1e3a8a;
        }
        .ghost-button {
            padding: 0.4rem 0.9rem;
            border-radius: 8px;
            border: 1px solid var(--accent);
            background-color: transparent;
            color: var(--accent);
            cursor: pointer;
            font-weight: 600;
        }
        .ghost-button:hover:not(:disabled) {
            background-color: var(--bg-muted);
        }
        .ghost-button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .downloads {
            margin-top: 0.85rem;
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        .download-link {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            padding: 0.4rem 0.75rem;
            border-radius: 8px;
            border: 1px solid var(--accent);
            background-color: #ffffff;
            color: var(--accent);
            text-decoration: none;
            font-weight: 600;
            font-size: 0.9rem;
        }
        .download-link:hover {
            background-color: var(--bg-muted);
        }
        .viewer {
            flex: 1;
            background-color: #ffffff;
            border-left: 1px solid var(--border-color);
        }
        iframe {
            width: 100%;
            height: 100%;
            border: none;
            background-color: white;
        }
        .message {
            padding: 0.9rem 1.25rem;
            font-size: 0.95rem;
            border-top: 1px solid var(--border-color);
            background-color: #ffffff;
            min-height: 2.25rem;
        }
        .message.error {
            color: #b91c1c;
        }
    </style>
</head>
<body>
    <aside class="sidebar">
        <h1>Auswahl</h1>
        <div id="tree" class="tree">Lade Struktur…</div>
    </aside>
    <main class="content">
        <div class="toolbar">
            <div class="title-row">
                <h2 id="current-path">Datei auswählen…</h2>
                <div class="controls">
                    <div class="lang-switch" id="language-switch">
                        <button type="button" class="lang-button active" data-lang="en">English</button>
                        <button type="button" class="lang-button" data-lang="de">Deutsch</button>
                    </div>
                    <button type="button" id="open-tab" class="ghost-button" disabled>Im neuen Tab</button>
                </div>
            </div>
            <div class="downloads" id="downloads">Downloads werden geladen …</div>
        </div>
        <div class="viewer">
            <iframe id="frame" sandbox="allow-same-origin"></iframe>
        </div>
        <div id="message" class="message">Wähle links eine Datei aus, um die Vorschau zu laden.</div>
    </main>
    <script>
        const treeContainer = document.getElementById("tree");
        const frame = document.getElementById("frame");
        const currentPathEl = document.getElementById("current-path");
        const messageEl = document.getElementById("message");
        const downloadsEl = document.getElementById("downloads");
        const openTabBtn = document.getElementById("open-tab");
        const langSwitch = document.getElementById("language-switch");
        let activePath = null;
        let currentDocument = null;
        let currentLanguage = "en";

        function renderTree(node, container, depth = 0) {
            if (!node) return;
            if (node.type === "directory") {
                const details = document.createElement("details");
                if (depth === 0) {
                    details.open = true;
                }

                const summary = document.createElement("summary");
                summary.textContent = node.name || "/";
                details.appendChild(summary);

                const wrapper = document.createElement("div");
                if (node.children) {
                    node.children.forEach(child => renderTree(child, wrapper, depth + 1));
                }

                details.appendChild(wrapper);
                container.appendChild(details);
            } else if (node.type === "file") {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "tree-file";
                button.textContent = node.name;
                button.dataset.path = node.path;
                button.addEventListener("click", () => onFileClick(button));
                container.appendChild(button);
            }
        }

        function clearActive() {
            const current = treeContainer.querySelector(".tree-file.active");
            if (current) {
                current.classList.remove("active");
            }
        }

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
        }

        async function onFileClick(element) {
            const path = element.dataset.path;
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
            }
        }

        function showMessage(text) {
            messageEl.textContent = text;
            messageEl.classList.remove("error");
        }

        function showError(text) {
            messageEl.textContent = text;
            messageEl.classList.add("error");
        }

        function clearMessage() {
            messageEl.textContent = "";
            messageEl.classList.remove("error");
        }

        async function loadTree() {
            try {
                const response = await fetch("/api/tree");
                if (!response.ok) {
                    throw new Error("Tree request failed");
                }
                const tree = await response.json();
                treeContainer.innerHTML = "";
                renderTree(tree, treeContainer);
            } catch (error) {
                console.error(error);
                treeContainer.textContent = "Baum konnte nicht geladen werden.";
            }
        }

        async function loadMeta() {
            try {
                const response = await fetch("/api/meta");
                if (!response.ok) {
                    throw new Error("Meta request failed");
                }
                const meta = await response.json();
                renderDownloads(meta.packages || []);
            } catch (error) {
                console.error(error);
                downloadsEl.textContent = "Downloads konnten nicht geladen werden.";
            }
        }

        function renderDownloads(items) {
            downloadsEl.innerHTML = "";
            if (!items.length) {
                downloadsEl.textContent = "Keine Downloads verfügbar.";
                return;
            }
            items.forEach(item => {
                const link = document.createElement("a");
                link.href = item.url;
                link.className = "download-link";
                link.textContent = item.label;
                link.setAttribute("download", item.filename);
                downloadsEl.appendChild(link);
            });
        }

        function setLanguage(language) {
            if (!language || currentLanguage === language) {
                return;
            }
            currentLanguage = language;
            updateLanguageButtons();
            if (currentDocument) {
                applyCurrentDocument();
            }
        }

        function updateLanguageButtons() {
            const buttons = langSwitch.querySelectorAll(".lang-button");
            buttons.forEach(button => {
                if (button.dataset.lang === currentLanguage) {
                    button.classList.add("active");
                } else {
                    button.classList.remove("active");
                }
            });
        }

        langSwitch.querySelectorAll(".lang-button").forEach(button => {
            button.addEventListener("click", () => setLanguage(button.dataset.lang));
        });

        openTabBtn.addEventListener("click", () => {
            if (!currentDocument) return;
            const html = getDocumentHtml(currentLanguage);
            const newWindow = window.open();
            if (newWindow) {
                newWindow.document.write(html);
                newWindow.document.close();
            } else {
                showError("Pop-up blockiert – bitte Pop-ups erlauben.");
            }
        });

        loadTree();
        loadMeta();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
