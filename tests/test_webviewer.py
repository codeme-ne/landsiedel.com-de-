import errno
from pathlib import Path
from zipfile import ZipFile

import pytest

from src.webviewer import (
    ViewerState,
    _safe_relative_path,
    build_file_tree,
    create_http_server,
    ensure_packages,
    load_document,
    resolve_language_dir,
)


def test_build_file_tree_orders_directories_before_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "b_file.html").write_text("file", encoding="utf-8")
    subdir = root / "a_dir"
    subdir.mkdir()
    (subdir / "inner.html").write_text("inner", encoding="utf-8")

    tree = build_file_tree(root)
    assert len(tree) == 2
    assert tree[0]["type"] == "directory"
    assert tree[0]["name"] == "a_dir"
    assert tree[1]["type"] == "file"
    assert tree[1]["name"] == "b_file.html"
    assert tree[0]["children"][0]["path"] == "a_dir/inner.html"


def test_safe_relative_path_rejects_traversal():
    with pytest.raises(ValueError):
        _safe_relative_path("../etc/passwd")


def test_load_document_reads_html(tmp_path):
    source_dir = tmp_path / "de"
    target_dir = tmp_path / "en"
    source_dir.mkdir()
    target_dir.mkdir()

    (source_dir / "page.html").write_text("<p>DE</p>", encoding="utf-8")
    (target_dir / "page.html").write_text("<p>EN</p>", encoding="utf-8")

    state = ViewerState(source_dir=source_dir, target_dir=target_dir)
    result = load_document(state, Path("page.html"))

    assert result["source"]["html"] == "<p>DE</p>"
    assert result["target"]["html"] == "<p>EN</p>"


def test_load_document_missing_target(tmp_path):
    source_dir = tmp_path / "de"
    target_dir = tmp_path / "en"
    source_dir.mkdir()
    target_dir.mkdir()

    (source_dir / "page.html").write_text("content", encoding="utf-8")

    state = ViewerState(source_dir=source_dir, target_dir=target_dir)

    with pytest.raises(FileNotFoundError):
        load_document(state, Path("page.html"))


def test_resolve_language_dir_prefers_new(tmp_path):
    output_dir = tmp_path
    (output_dir / "de_NEW").mkdir()
    resolved = resolve_language_dir(output_dir, None, ("de_NEW", "de"), "source")
    assert resolved.name == "de_NEW"


def test_resolve_language_dir_falls_back(tmp_path):
    output_dir = tmp_path
    (output_dir / "de").mkdir()
    resolved = resolve_language_dir(output_dir, None, ("de_NEW", "de"), "source")
    assert resolved.name == "de"


def test_create_http_server_retries_on_busy_port(tmp_path, monkeypatch):
    source_dir = tmp_path / "de"
    target_dir = tmp_path / "en"
    source_dir.mkdir()
    target_dir.mkdir()
    state = ViewerState(source_dir=source_dir, target_dir=target_dir)

    calls = []

    class DummyServer:
        def __init__(self, address, handler):
            calls.append(address)
            if len(calls) == 1:
                raise OSError(errno.EADDRINUSE, "busy")

        def server_close(self):
            pass

    monkeypatch.setattr("src.webviewer.ThreadingHTTPServer", DummyServer)

    httpd, bound_port = create_http_server("127.0.0.1", 8000, 2, state, [])
    assert calls == [("127.0.0.1", 8000), ("127.0.0.1", 8001)]
    assert bound_port == 8001
    assert getattr(httpd, "viewer_state") is state
    assert getattr(httpd, "viewer_packages") == []
    httpd.server_close()


def test_create_http_server_raises_after_attempts(tmp_path, monkeypatch):
    source_dir = tmp_path / "de"
    target_dir = tmp_path / "en"
    source_dir.mkdir()
    target_dir.mkdir()
    state = ViewerState(source_dir=source_dir, target_dir=target_dir)

    class DummyServer:
        def __init__(self, address, handler):
            raise OSError(errno.EADDRINUSE, "busy")

    monkeypatch.setattr("src.webviewer.ThreadingHTTPServer", DummyServer)

    with pytest.raises(OSError):
        create_http_server("127.0.0.1", 9000, 2, state, [])


def test_ensure_packages_creates_archives(tmp_path):
    root = tmp_path
    source_dir = root / "de_NEW"
    target_dir = root / "en_NEW"
    source_dir.mkdir()
    target_dir.mkdir()

    (source_dir / "index.html").write_text("<p>DE</p>", encoding="utf-8")
    (target_dir / "index.html").write_text("<p>EN</p>", encoding="utf-8")

    state = ViewerState(source_dir=source_dir, target_dir=target_dir)
    packages = ensure_packages(state, root)

    assert (root / "packages").is_dir()
    assert {package.language for package in packages} == {"de", "en"}

    for package in packages:
        assert package.archive_path.exists()
        assert package.directory.name in package.label
        with ZipFile(package.archive_path) as zf:
            entries = zf.namelist()
            assert any(name.startswith(f"{package.directory.name}/") for name in entries)
