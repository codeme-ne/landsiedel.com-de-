#!/usr/bin/env python3
"""Tests for batch processing module"""
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest
from lxml import etree

from src.batch import (
    load_sitemap_json, load_sitemap_xml, load_sitemap,
    process_single_url, run_batch
)
from src.fetcher import FetchError


class TestSitemapLoading:
    """Test sitemap loading functions"""
    
    def test_load_sitemap_json_valid(self, tmp_path):
        """Test loading valid JSON sitemap"""
        sitemap_path = tmp_path / "sitemap.json"
        data = [
            {"url": "https://www.landsiedel.com/de/page1.html"},
            {"url": "https://www.landsiedel.com/de/page2.html"},
            {"url": "https://www.landsiedel.com/en/page3.html"},  # Should filter out
            {"url": "https://example.com/de/page4.html"},  # Wrong domain
        ]
        sitemap_path.write_text(json.dumps(data), encoding='utf-8')
        
        urls = load_sitemap_json(str(sitemap_path))
        
        assert len(urls) == 2
        assert all('/de/' in url for url in urls)
        assert all('www.landsiedel.com' in url for url in urls)
    
    def test_load_sitemap_json_with_loc_field(self, tmp_path):
        """Test JSON with 'loc' field instead of 'url'"""
        sitemap_path = tmp_path / "sitemap.json"
        data = [
            {"loc": "https://www.landsiedel.com/de/test.html"},
        ]
        sitemap_path.write_text(json.dumps(data), encoding='utf-8')
        
        urls = load_sitemap_json(str(sitemap_path))
        
        assert len(urls) == 1
        assert urls[0] == "https://www.landsiedel.com/de/test.html"
    
    def test_load_sitemap_json_deduplication(self, tmp_path):
        """Test that duplicate URLs are deduplicated"""
        sitemap_path = tmp_path / "sitemap.json"
        data = [
            {"url": "https://www.landsiedel.com/de/page.html"},
            {"url": "https://www.landsiedel.com/de/page.html"},  # Duplicate
        ]
        sitemap_path.write_text(json.dumps(data), encoding='utf-8')
        
        urls = load_sitemap_json(str(sitemap_path))
        
        assert len(urls) == 1
    
    def test_load_sitemap_json_invalid_format(self, tmp_path):
        """Test error handling for invalid JSON format"""
        sitemap_path = tmp_path / "sitemap.json"
        sitemap_path.write_text("{}", encoding='utf-8')  # Not an array
        
        with pytest.raises(ValueError, match="must contain an array"):
            load_sitemap_json(str(sitemap_path))
    
    def test_load_sitemap_xml_valid(self, tmp_path):
        """Test loading valid XML sitemap"""
        sitemap_path = tmp_path / "sitemap.xml"
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.landsiedel.com/de/page1.html</loc>
  </url>
  <url>
    <loc>https://www.landsiedel.com/de/page2.html</loc>
  </url>
  <url>
    <loc>https://www.landsiedel.com/en/page3.html</loc>
  </url>
</urlset>"""
        sitemap_path.write_text(xml_content, encoding='utf-8')
        
        urls = load_sitemap_xml(str(sitemap_path))
        
        assert len(urls) == 2
        assert all('/de/' in url for url in urls)
        assert all('www.landsiedel.com' in url for url in urls)
    
    def test_load_sitemap_xml_without_namespace(self, tmp_path):
        """Test XML sitemap without namespace"""
        sitemap_path = tmp_path / "sitemap.xml"
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset>
  <url>
    <loc>https://www.landsiedel.com/de/test.html</loc>
  </url>
</urlset>"""
        sitemap_path.write_text(xml_content, encoding='utf-8')
        
        urls = load_sitemap_xml(str(sitemap_path))
        
        assert len(urls) == 1
        assert urls[0] == "https://www.landsiedel.com/de/test.html"
    
    def test_load_sitemap_auto_detect_json(self, tmp_path):
        """Test auto-detection for .json extension"""
        sitemap_path = tmp_path / "sitemap.json"
        data = [{"url": "https://www.landsiedel.com/de/page.html"}]
        sitemap_path.write_text(json.dumps(data), encoding='utf-8')
        
        urls = load_sitemap(str(sitemap_path))
        
        assert len(urls) == 1
    
    def test_load_sitemap_auto_detect_xml(self, tmp_path):
        """Test auto-detection for .xml extension"""
        sitemap_path = tmp_path / "sitemap.xml"
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.landsiedel.com/de/test.html</loc></url>
</urlset>"""
        sitemap_path.write_text(xml_content, encoding='utf-8')
        
        urls = load_sitemap(str(sitemap_path))
        
        assert len(urls) == 1
    
    def test_load_sitemap_fallback_json_to_xml(self, tmp_path):
        """Test fallback from JSON to XML when no extension"""
        sitemap_path = tmp_path / "sitemap"
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.landsiedel.com/de/test.html</loc></url>
</urlset>"""
        sitemap_path.write_text(xml_content, encoding='utf-8')
        
        urls = load_sitemap(str(sitemap_path))
        
        assert len(urls) == 1
    
    def test_load_sitemap_file_not_found(self):
        """Test error when sitemap file doesn't exist"""
        with pytest.raises(FileNotFoundError):
            load_sitemap("/nonexistent/sitemap.json")
    
    def test_load_sitemap_invalid_format(self, tmp_path):
        """Test error when file is neither valid JSON nor XML"""
        sitemap_path = tmp_path / "sitemap.txt"
        sitemap_path.write_text("Not valid JSON or XML", encoding='utf-8')
        
        with pytest.raises(ValueError, match="Could not parse"):
            load_sitemap(str(sitemap_path))


class TestProcessSingleUrl:
    """Test single URL processing"""
    
    @patch('src.batch.fetch')
    @patch('src.batch.parse')
    @patch('src.batch.translate_batch')
    @patch('src.batch.save_html')
    def test_process_single_url_success(
        self, mock_save, mock_translate, mock_parse, mock_fetch, tmp_path
    ):
        """Test successful processing of single URL"""
        # Mock fetch
        mock_html = "<html><body>Test</body></html>"
        mock_fetch.return_value = (
            mock_html,
            {'final_url': 'https://www.landsiedel.com/de/test.html'}
        )
        
        # Mock parse
        mock_soup = MagicMock()
        mock_items = ["Text 1"]
        mock_parse.return_value = (mock_soup, mock_items)
        
        # Mock translate
        mock_translate.return_value = ["Text 1 translated"]
        
        # Process
        process_single_url(
            'https://www.landsiedel.com/de/test.html',
            str(tmp_path)
        )
        
        # Verify calls
        assert mock_fetch.called
        assert mock_parse.call_count == 2  # Once for EN, once for DE
        assert mock_translate.called
        assert mock_save.call_count == 2  # DE + EN
    
    @patch('src.batch.fetch')
    def test_process_single_url_fetch_error(self, mock_fetch, tmp_path):
        """Test that FetchError is propagated"""
        mock_fetch.side_effect = FetchError("Connection failed")
        
        with pytest.raises(FetchError):
            process_single_url(
                'https://www.landsiedel.com/de/test.html',
                str(tmp_path)
            )


class TestRunBatch:
    """Test batch orchestrator"""
    
    @patch('src.batch.process_single_url')
    @patch('src.batch.time.sleep')
    def test_run_batch_all_success(self, mock_sleep, mock_process, tmp_path):
        """Test batch with all URLs successful"""
        urls = [
            'https://www.landsiedel.com/de/page1.html',
            'https://www.landsiedel.com/de/page2.html',
        ]
        
        results = run_batch(urls, str(tmp_path), delay=0.1)
        
        assert results['success'] == 2
        assert results['failed'] == 0
        assert results['skipped'] == 0
        assert len(results['failed_urls']) == 0
        assert mock_sleep.call_count == 1  # Only between URLs, not after last
    
    @patch('src.batch.process_single_url')
    @patch('src.batch.time.sleep')
    def test_run_batch_with_fetch_errors(self, mock_sleep, mock_process, tmp_path):
        """Test batch with FetchError (should skip, not fail)"""
        urls = [
            'https://www.landsiedel.com/de/page1.html',
            'https://www.landsiedel.com/de/page2.html',
        ]
        
        # First URL succeeds, second raises FetchError
        mock_process.side_effect = [None, FetchError("Timeout")]
        
        results = run_batch(urls, str(tmp_path), delay=0.1)
        
        assert results['success'] == 1
        assert results['failed'] == 0
        assert results['skipped'] == 1
        assert len(results['failed_urls']) == 0
    
    @patch('src.batch.process_single_url')
    @patch('src.batch.time.sleep')
    def test_run_batch_with_exceptions(self, mock_sleep, mock_process, tmp_path):
        """Test batch with generic exceptions (should fail)"""
        urls = [
            'https://www.landsiedel.com/de/page1.html',
            'https://www.landsiedel.com/de/page2.html',
        ]
        
        # First URL succeeds, second raises Exception
        mock_process.side_effect = [None, ValueError("Parse error")]
        
        results = run_batch(urls, str(tmp_path), delay=0.1)
        
        assert results['success'] == 1
        assert results['failed'] == 1
        assert results['skipped'] == 0
        assert len(results['failed_urls']) == 1
        
        # Check failed_urls.txt was created
        failed_file = Path(tmp_path) / 'failed_urls.txt'
        assert failed_file.exists()
        content = failed_file.read_text()
        assert 'page2.html' in content
        assert 'Parse error' in content
    
    @patch('src.batch.process_single_url')
    @patch('src.batch.time.sleep')
    def test_run_batch_no_delay_after_last_url(self, mock_sleep, mock_process, tmp_path):
        """Test that delay is not applied after the last URL"""
        urls = ['https://www.landsiedel.com/de/page.html']
        
        run_batch(urls, str(tmp_path), delay=1.0)
        
        assert not mock_sleep.called  # No sleep for single URL
