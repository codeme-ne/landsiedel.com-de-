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

from src.templates import render_template
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


def _get_static_index_html() -> str:
    """Generate the static site index HTML."""
    meta_tags = """<meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" href="data:,">"""

    script_functions = """
        function updateViewer() {
            if (!activePath) {
                frame.src = "";
                openTabBtn.disabled = true;
                return;
            }
            frame.src = `${currentLanguage}/${activePath}`;
            openTabBtn.disabled = false;
        }"""

    on_file_click = """activePath = element.dataset.path;
            clearActive();
            element.classList.add("active");
            currentPathEl.textContent = activePath;
            showMessage(`Öffne ${currentLanguage.toUpperCase()} …`);
            updateViewer();
            clearMessage();"""

    on_lang_change = "updateViewer();"

    on_open_tab = """if (!activePath) return;
            const location = `${currentLanguage}/${activePath}`;
            const newWindow = window.open(location, "_blank");
            if (!newWindow) {
                showError("Pop-up blockiert – bitte Pop-ups erlauben.");
            }"""

    return render_template(
        "viewer.html",
        META_TAGS=meta_tags,
        IFRAME_ATTRS='src="" title="Dokumenten-Vorschau"',
        SCRIPT_VARS="",
        SCRIPT_FUNCTIONS=script_functions,
        ON_FILE_CLICK=on_file_click,
        TREE_URL="data/tree.json",
        META_URL="data/meta.json",
        ON_LANG_CHANGE=on_lang_change,
        ON_OPEN_TAB=on_open_tab,
    )


STATIC_INDEX_HTML = _get_static_index_html()


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

