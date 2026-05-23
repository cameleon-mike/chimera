"""Unit tests for SSRF-safe FQDN validator."""
import pytest
from tools.common.domain_validator import validate_fqdn


@pytest.mark.parametrize("domain", [
    "httpbin.org",
    "www.example.com",
    "sub.domain.co.uk",
    "my-site.io",
    "a.io",
    "xn--nxasmq6b.com",  # punycode — passes format check (ASCII labels ok)
])
def test_valid_fqdn(domain):
    valid, reason = validate_fqdn(domain)
    assert valid, f"Expected valid but got error: {reason}"


@pytest.mark.parametrize("domain", [
    "169.254.169.254",
    "10.0.0.1",
    "127.0.0.1",
    "192.168.1.1",
    "8.8.8.8",
])
def test_reject_ipv4(domain):
    valid, reason = validate_fqdn(domain)
    assert not valid
    assert "IP literal" in reason


@pytest.mark.parametrize("domain", [
    "::1",
    "fe80::1",
])
def test_reject_ipv6(domain):
    valid, reason = validate_fqdn(domain)
    assert not valid
    assert "IP literal" in reason


@pytest.mark.parametrize("domain", [
    "localhost",
    "intranet",
    "server",
])
def test_reject_single_label(domain):
    valid, reason = validate_fqdn(domain)
    assert not valid


@pytest.mark.parametrize("domain", [
    "myhost.local",
    "anything.localhost",
    "foo.invalid",
    "bar.test",
    "baz.example",
])
def test_reject_reserved_tld(domain):
    valid, reason = validate_fqdn(domain)
    assert not valid
    assert "reserved TLD" in reason or "reserved internal" in reason


@pytest.mark.parametrize("domain", [
    "",
    "   ",
    "..",
    ".com",
    "domain.",
    "-bad.com",
    None,
])
def test_reject_invalid_format(domain):
    valid, reason = validate_fqdn(domain)
    assert not valid


def test_forbidden_label_localhost():
    valid, reason = validate_fqdn("localhost")
    assert not valid
    # May be caught by single-label or forbidden-labels check
    assert reason


def test_ip6_loopback():
    valid, reason = validate_fqdn("ip6-localhost")
    assert not valid
    assert "reserved internal" in reason
