from pathlib import Path
import json
import zipfile

from src.static_site import StaticSiteConfig, build_site


def test_build_site_generates_static_viewer(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    de_dir = output_dir / "de_NEW"
    en_dir = output_dir / "en_NEW"
    de_dir.mkdir()
    en_dir.mkdir()

    (de_dir / "index.html").write_text("<p>DE</p>", encoding="utf-8")
    (en_dir / "index.html").write_text("<p>EN</p>", encoding="utf-8")

    site_dir = tmp_path / "docs"
    config = StaticSiteConfig(
        output_dir=output_dir,
        site_dir=site_dir,
        source_dir=de_dir,
        target_dir=en_dir,
    )

    build_site(config)

    assert (site_dir / "index.html").exists()
    assert (site_dir / "de" / "index.html").exists()
    assert (site_dir / "en" / "index.html").exists()

    tree_path = site_dir / "data" / "tree.json"
    meta_path = site_dir / "data" / "meta.json"
    assert tree_path.exists()
    assert meta_path.exists()

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    assert tree["name"] == "de_NEW"
    assert tree["children"][0]["name"] == "index.html"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert {pkg["language"] for pkg in meta["packages"]} == {"de", "en"}

    for lang in ("de", "en"):
        archive = site_dir / "packages" / f"{lang}.zip"
        assert archive.exists()
        with zipfile.ZipFile(archive) as zip_file:
            assert any(name.endswith("index.html") for name in zip_file.namelist())
