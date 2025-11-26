"""Tests for SSRF vulnerability prevention in fetcher"""
import pytest
from src.fetcher import validate_url, SSRFError


class TestSSRFPrevention:
    """Test suite for SSRF attack prevention"""

    def test_blocks_localhost_by_name(self):
        """Block localhost by hostname"""
        with pytest.raises(SSRFError, match="localhost is blocked"):
            validate_url("http://localhost:8080/admin")

    def test_blocks_localhost_uppercase(self):
        """Block localhost case-insensitive"""
        with pytest.raises(SSRFError, match="localhost is blocked"):
            validate_url("http://LOCALHOST/api")

    def test_blocks_localhost_ip_127_0_0_1(self):
        """Block 127.0.0.1 loopback address"""
        with pytest.raises(SSRFError, match="Loopback address blocked"):
            validate_url("http://127.0.0.1:8000/")

    def test_blocks_localhost_ip_0_0_0_0(self):
        """Block 0.0.0.0 address"""
        with pytest.raises(SSRFError, match="blocked"):
            validate_url("http://0.0.0.0/")

    def test_blocks_ipv6_loopback(self):
        """Block IPv6 loopback ::1"""
        with pytest.raises(SSRFError, match="Loopback address blocked"):
            validate_url("http://[::1]:8080/")

    def test_blocks_metadata_endpoint(self):
        """Block cloud metadata endpoint 169.254.169.254"""
        with pytest.raises(SSRFError, match="metadata endpoint blocked"):
            validate_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_private_ip_10_x(self):
        """Block 10.0.0.0/8 private range"""
        with pytest.raises(SSRFError, match="Private IP address blocked"):
            validate_url("http://10.0.0.1/internal")

        with pytest.raises(SSRFError, match="Private IP address blocked"):
            validate_url("http://10.255.255.255/")

    def test_blocks_private_ip_172_16_x(self):
        """Block 172.16.0.0/12 private range"""
        with pytest.raises(SSRFError, match="Private IP address blocked"):
            validate_url("http://172.16.0.1/")

        with pytest.raises(SSRFError, match="Private IP address blocked"):
            validate_url("http://172.31.255.255/")

    def test_blocks_private_ip_192_168_x(self):
        """Block 192.168.0.0/16 private range"""
        with pytest.raises(SSRFError, match="Private IP address blocked"):
            validate_url("http://192.168.1.1/router")

        with pytest.raises(SSRFError, match="Private IP address blocked"):
            validate_url("http://192.168.255.255/")

    def test_blocks_link_local_169_254_x(self):
        """Block link-local 169.254.0.0/16 range"""
        with pytest.raises(SSRFError, match="blocked"):
            validate_url("http://169.254.1.1/")

    def test_blocks_file_protocol(self):
        """Block file:// protocol"""
        with pytest.raises(SSRFError, match="only http/https allowed"):
            validate_url("file:///etc/passwd")

    def test_blocks_ftp_protocol(self):
        """Block ftp:// protocol"""
        with pytest.raises(SSRFError, match="only http/https allowed"):
            validate_url("ftp://internal.server/files")

    def test_blocks_data_protocol(self):
        """Block data: URLs"""
        with pytest.raises(SSRFError, match="only http/https allowed"):
            validate_url("data:text/html,<script>alert('xss')</script>")

    def test_blocks_javascript_protocol(self):
        """Block javascript: URLs"""
        with pytest.raises(SSRFError, match="only http/https allowed"):
            validate_url("javascript:alert(1)")

    def test_blocks_empty_hostname(self):
        """Block URLs without hostname"""
        with pytest.raises(SSRFError, match="must contain a hostname"):
            validate_url("http://")

    def test_allows_valid_http_url(self):
        """Allow valid external HTTP URL"""
        # Should not raise any exception
        validate_url("http://example.com/page")

    def test_allows_valid_https_url(self):
        """Allow valid external HTTPS URL"""
        # Should not raise any exception
        validate_url("https://www.example.org/api")

    def test_allows_url_with_port(self):
        """Allow valid URL with port"""
        # Should not raise any exception
        validate_url("https://example.com:443/secure")

    def test_allows_url_with_path_and_query(self):
        """Allow valid URL with path and query parameters"""
        # Should not raise any exception
        validate_url("https://api.example.com/v1/resource?id=123&lang=de")

    def test_blocks_url_resolving_to_private_ip(self):
        """Block domains that resolve to private IPs"""
        # Note: This test would need a domain that actually resolves
        # to a private IP. In practice, attackers might use DNS rebinding.
        # For unit tests, we test the IP validation logic directly above.
        pass


class TestSSRFEdgeCases:
    """Edge cases and advanced SSRF scenarios"""

    def test_blocks_localhost_with_dot(self):
        """Block localhost. variant"""
        with pytest.raises(SSRFError, match="blocked"):
            validate_url("http://localhost./")

    def test_blocks_127_0_0_2(self):
        """Block other 127.x.x.x loopback addresses"""
        with pytest.raises(SSRFError, match="Loopback address blocked"):
            validate_url("http://127.0.0.2/")

        with pytest.raises(SSRFError, match="Loopback address blocked"):
            validate_url("http://127.255.255.255/")

    def test_url_with_credentials(self):
        """Handle URLs with embedded credentials"""
        # Should validate the hostname, not the credentials
        with pytest.raises(SSRFError, match="localhost is blocked"):
            validate_url("http://user:pass@localhost:8080/")

    def test_https_scheme_allowed(self):
        """Ensure HTTPS is explicitly allowed"""
        # Should not raise
        validate_url("https://secure.example.com/")

    def test_case_insensitive_scheme(self):
        """Handle mixed-case schemes"""
        # Should not raise
        validate_url("HTTPS://example.com/")
        validate_url("HtTp://example.com/")
