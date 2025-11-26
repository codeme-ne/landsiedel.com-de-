"""Tests for path traversal vulnerability prevention in writer.map_paths()"""
import pytest
from pathlib import Path
from src.writer import map_paths


def test_blocks_parent_directory_traversal(tmp_path):
    """Block ../../../ traversal attempts"""
    output_dir = str(tmp_path)

    # Various traversal attack patterns
    traversal_urls = [
        'https://example.com/de/../../../etc/passwd',
        'https://example.com/de/../../sensitive.html',
        'https://example.com/de/page/../../../etc/malicious',
        'https://example.com/de/foo/bar/../../../sensitive',
    ]

    for url in traversal_urls:
        with pytest.raises(ValueError, match="Path traversal detected"):
            map_paths(url, output_dir)


def test_blocks_absolute_paths_in_urls(tmp_path):
    """Block absolute path references in URLs"""
    output_dir = str(tmp_path)

    # Absolute paths should fail safe character validation
    # Note: After stripping leading '/', these become relative
    # but may still contain unsafe patterns
    with pytest.raises(ValueError):
        # This becomes 'etc/passwd' after processing but is still suspicious
        map_paths('https://example.com//etc/passwd', output_dir)


def test_allows_valid_relative_paths(tmp_path):
    """Allow valid relative paths within output directory"""
    output_dir = str(tmp_path)

    valid_urls = [
        'https://example.com/de/page.html',
        'https://example.com/de/section/subsection/page.html',
        'https://example.com/de/about/',
        'https://example.com/de/products/item-123.html',
    ]

    for url in valid_urls:
        de_path, en_path = map_paths(url, output_dir)

        # Verify paths are constructed correctly
        assert de_path.startswith(output_dir)
        assert en_path.startswith(output_dir)
        assert '/de/' in de_path
        assert '/en/' in en_path


def test_output_stays_within_output_directory(tmp_path):
    """Ensure all output paths stay within the output directory"""
    output_dir = str(tmp_path)

    test_urls = [
        'https://example.com/de/page.html',
        'https://example.com/de/deep/nested/path/file.html',
        'https://example.com/de/',
    ]

    for url in test_urls:
        de_path, en_path = map_paths(url, output_dir)

        # Resolve paths and verify they're within output_dir
        de_resolved = Path(de_path).resolve()
        en_resolved = Path(en_path).resolve()
        base_resolved = tmp_path.resolve()

        assert str(de_resolved).startswith(str(base_resolved))
        assert str(en_resolved).startswith(str(base_resolved))


def test_blocks_dot_dot_in_path_components(tmp_path):
    """Block any path containing '..' components"""
    output_dir = str(tmp_path)

    dotdot_urls = [
        'https://example.com/de/page/../admin.html',
        'https://example.com/de/../config.html',
        'https://example.com/de/section/../../../etc/passwd',
    ]

    for url in dotdot_urls:
        with pytest.raises(ValueError, match="Path traversal detected"):
            map_paths(url, output_dir)


def test_blocks_unsafe_characters(tmp_path):
    """Validate path contains only safe characters"""
    output_dir = str(tmp_path)

    unsafe_urls = [
        'https://example.com/de/page;<script>alert(1)</script>',
        'https://example.com/de/file%00.html',  # Null byte
        'https://example.com/de/page|whoami',
        'https://example.com/de/file&command',
        'https://example.com/de/path\\windows\\system32',
    ]

    for url in unsafe_urls:
        with pytest.raises(ValueError, match="unsafe characters|Invalid path"):
            map_paths(url, output_dir)


def test_homepage_paths_are_safe(tmp_path):
    """Homepage URLs map safely to index.html"""
    output_dir = str(tmp_path)

    homepage_urls = [
        'https://example.com/',
        'https://example.com/de/',
    ]

    for url in homepage_urls:
        de_path, en_path = map_paths(url, output_dir)

        assert de_path.endswith('de/index.html')
        assert en_path.endswith('en/index.html')

        # Verify within output directory
        assert str(Path(de_path).resolve()).startswith(str(tmp_path.resolve()))
        assert str(Path(en_path).resolve()).startswith(str(tmp_path.resolve()))


def test_normal_nested_paths_work(tmp_path):
    """Normal nested paths should work without issues"""
    output_dir = str(tmp_path)

    de_path, en_path = map_paths(
        'https://example.com/de/products/category/item-123.html',
        output_dir
    )

    assert 'products/category/item-123.html' in de_path
    assert de_path.endswith('de/products/category/item-123.html')
    assert en_path.endswith('en/products/category/item-123.html')

    # Verify safety
    assert str(Path(de_path).resolve()).startswith(str(tmp_path.resolve()))


def test_edge_case_multiple_dots_in_filename(tmp_path):
    """Filenames with multiple dots (but not ..) should work"""
    output_dir = str(tmp_path)

    # This should work - dots in filename are OK, just not '..' component
    de_path, en_path = map_paths(
        'https://example.com/de/file.backup.html',
        output_dir
    )

    assert 'file.backup.html' in de_path
    assert str(Path(de_path).resolve()).startswith(str(tmp_path.resolve()))


def test_symlink_escape_attempt(tmp_path):
    """Test that symlinks cannot be used to escape output directory"""
    output_dir = str(tmp_path)

    # Create a directory outside tmp_path
    external_dir = tmp_path.parent / 'external_sensitive'
    external_dir.mkdir(exist_ok=True)

    try:
        # Try to create symlink (this is what an attacker might try)
        # We're testing that our validation catches the '..' pattern
        # before any file operations occur

        with pytest.raises(ValueError, match="Path traversal detected"):
            map_paths('https://example.com/de/../../external_sensitive/data.html', output_dir)
    finally:
        # Cleanup
        if external_dir.exists():
            external_dir.rmdir()
