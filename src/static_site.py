#!/usr/bin/env python3
"""Utilities for exporting a static viewer suitable for GitHub Pages."""
from __future__ import annotations

import argparse
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from src.webviewer import (
    ViewerState,
    build_file_tree,
    ensure_packages,
    resolve_language_dir,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticSiteConfig:
    """Resolved paths required to build the static site."""

    output_dir: Path
    site_dir: Path
    source_dir: Path
    target_dir: Path


def parse_arguments(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static viewer (docs/) for GitHub Pages hosting."
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Root directory containing translation outputs (default: output)",
    )
    parser.add_argument(
        "--site-dir",
        default="docs",
        help="Destination directory for the static site (default: docs)",
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
    return parser.parse_args(argv)


def prepare_config(args: argparse.Namespace) -> StaticSiteConfig:
    output_dir = Path(args.output_dir).expanduser().resolve()
    site_dir = Path(args.site_dir).expanduser().resolve()

    source_dir = resolve_language_dir(output_dir, args.source_subdir, ("de_NEW", "de"), "source")
    target_dir = resolve_language_dir(output_dir, args.target_subdir, ("en_NEW", "en"), "target")

    return StaticSiteConfig(
        output_dir=output_dir,
        site_dir=site_dir,
        source_dir=source_dir,
        target_dir=target_dir,
    )


def copy_language_trees(config: StaticSiteConfig) -> None:
    """Copy language directories into the static site structure."""
    for language, source in (("de", config.source_dir), ("en", config.target_dir)):
        destination = config.site_dir / language
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        LOGGER.info("Copied %s -> %s", source, destination)


def write_tree_json(config: StaticSiteConfig) -> None:
    """Emit the file tree JSON consumed by the static frontend."""
    tree = {
        "type": "directory",
        "name": config.source_dir.name,
        "path": "",
        "children": build_file_tree(config.source_dir),
    }
    data_dir = config.site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    tree_path = data_dir / "tree.json"
    tree_path.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
    LOGGER.info("Wrote tree data to %s", tree_path)


def write_meta_json(package_entries, site_dir: Path) -> None:
    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    meta_path = data_dir / "meta.json"
    meta_payload = {"packages": package_entries}
    meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False), encoding="utf-8")
    LOGGER.info("Wrote metadata to %s", meta_path)


def copy_packages(config: StaticSiteConfig) -> None:
    """Generate ZIP archives and copy them into the static site."""
    state = ViewerState(config.source_dir, config.target_dir)
    packages = ensure_packages(state, config.output_dir)
    site_packages_dir = config.site_dir / "packages"
    site_packages_dir.mkdir(parents=True, exist_ok=True)

    meta_entries = []
    for package in packages:
        target_name = f"{package.language}.zip"
        destination = site_packages_dir / target_name
        shutil.copy2(package.archive_path, destination)
        LOGGER.info("Copied %s -> %s", package.archive_path, destination)
        meta_entries.append(
            {
                "language": package.language,
                "label": package.label,
                "filename": target_name,
                "url": f"packages/{target_name}",
            }
        )

    write_meta_json(meta_entries, config.site_dir)


STATIC_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Translation Viewer</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" href="data:,">
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
            <iframe id="frame" src="" title="Dokumenten-Vorschau"></iframe>
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

        function updateViewer() {
            if (!activePath) {
                frame.src = "";
                openTabBtn.disabled = true;
                return;
            }
            frame.src = `${currentLanguage}/${activePath}`;
            openTabBtn.disabled = false;
        }

        async function onFileClick(element) {
            activePath = element.dataset.path;
            clearActive();
            element.classList.add("active");
            currentPathEl.textContent = activePath;
            showMessage(`Öffne ${currentLanguage.toUpperCase()} …`);
            updateViewer();
            clearMessage();
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
                const response = await fetch("data/tree.json");
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
                const response = await fetch("data/meta.json");
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
            updateViewer();
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
            if (!activePath) return;
            const location = `${currentLanguage}/${activePath}`;
            const newWindow = window.open(location, "_blank");
            if (!newWindow) {
                showError("Pop-up blockiert – bitte Pop-ups erlauben.");
            }
        });

        loadTree();
        loadMeta();
    </script>
</body>
</html>
"""


def write_index_html(site_dir: Path) -> None:
    index_path = site_dir / "index.html"
    index_path.write_text(STATIC_INDEX_HTML, encoding="utf-8")
    LOGGER.info("Wrote index page to %s", index_path)


def build_site(config: StaticSiteConfig) -> None:
    config.site_dir.mkdir(parents=True, exist_ok=True)

    copy_language_trees(config)
    write_tree_json(config)
    copy_packages(config)
    write_index_html(config.site_dir)


def main(argv: Optional[Iterable[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    args = parse_arguments(argv)
    try:
        config = prepare_config(args)
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 2
    build_site(config)
    LOGGER.info("Static site generated at %s", config.site_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

