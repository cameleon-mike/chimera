#!/usr/bin/env python3
"""Standalone validator for the fingerprint pool.

Usage:
    python -m network.fingerprints.validator
    python -m network.fingerprints.validator --dir /path/to/fingerprints

Exit 0 if valid, 1 if errors found.
Output: JSON to stdout {"valid": bool, "errors": [...]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Chimera fingerprint pool")
    parser.add_argument(
        "--dir",
        default=str(Path(__file__).parent),
        help="Path to fingerprints directory (default: this package dir)",
    )
    args = parser.parse_args()

    from network.fingerprints.loader import FingerprintLoader
    try:
        loader = FingerprintLoader(fingerprints_dir=args.dir)
    except Exception as exc:
        result = {"valid": False, "errors": [f"Failed to load pool: {exc}"]}
        print(json.dumps(result, indent=2))
        return 1

    errors = loader.validate_pool()
    result = {"valid": len(errors) == 0, "errors": errors}
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
