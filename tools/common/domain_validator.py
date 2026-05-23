"""FQDN validation with SSRF protection."""
import ipaddress
import re

# Strict FQDN regex : minimum 2 labels, last label is alphabetic TLD
_FQDN_STRICT = re.compile(
    r"^(?=.{1,253}$)"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)

_FORBIDDEN_LABELS = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "broadcasthost",
}


def validate_fqdn(domain: str) -> tuple[bool, str]:
    """Return (is_valid, error_message).

    Rejects:
    - IPv4 / IPv6 literals in standard decimal notation (via ipaddress)
    - IPv4 octal/hex variants and packed-decimal (caught by regex/single-label checks)
    - Single-label hostnames (localhost, intranet)
    - Forbidden well-known internal names
    - Reserved TLDs (local, localhost, invalid, test, example)

    Returns (True, "") if valid public FQDN.
    Note: punycode labels (xn--) with ASCII TLDs are accepted; IDN TLDs are not.
    """
    if not domain or not isinstance(domain, str):
        return False, "domain must be a non-empty string"

    d = domain.strip().lower()

    if not d:
        return False, "domain must be a non-empty string"

    # Reject forbidden labels
    if d in _FORBIDDEN_LABELS:
        return False, f"domain '{d}' is a reserved internal name"

    # Reject standard decimal IPv4 and any IPv6 notation.
    # Octal/hex IPv4 variants (0177.0.0.1, 2130706433) are not parsed by
    # ipaddress but are blocked downstream by the FQDN regex or single-label check.
    try:
        ip = ipaddress.ip_address(d)
        return False, f"IP literal not allowed (parsed as {ip})"
    except ValueError:
        pass

    # Reject single-label (no dot)
    if "." not in d:
        return False, "single-label hostnames not allowed"

    # Strict FQDN match
    if not _FQDN_STRICT.fullmatch(d):
        return False, "invalid FQDN format"

    # Reject reserved TLDs (RFC 6761/2606)
    tld = d.rsplit(".", 1)[-1]
    if tld in {"local", "localhost", "invalid", "test", "example"}:
        return False, f"reserved TLD '.{tld}' not allowed"

    return True, ""
