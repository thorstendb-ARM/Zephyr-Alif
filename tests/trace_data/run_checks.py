#!/usr/bin/env python3
"""Run portable Trace Data checks, optionally with the pinned real browser."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import unittest


HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-checks", action="store_true",
                        help="Require actual Mermaid parsing and native DOM layout checks")
    parser.add_argument("--browser", type=Path,
                        help="Use this Chrome/Chromium instead of the pinned Playwright browser")
    parser.add_argument("--tools-dir", type=Path,
                        help="Directory containing validation node_modules (default: this test directory)")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if (args.browser or args.tools_dir) and not args.browser_checks:
        parser.error("--browser and --tools-dir require --browser-checks")
    if args.browser_checks:
        tools_dir = (args.tools_dir or HERE).expanduser().resolve()
        library = tools_dir / "node_modules/mermaid/dist/mermaid.esm.min.mjs"
        if not library.is_file():
            parser.error("Validation tools missing; follow the documented external setup and use --tools-dir")
        os.environ["TRACE_REQUIRE_BROWSER"] = "1"
        os.environ["TRACE_MERMAID_JS"] = str(library)
        if args.browser:
            browser = args.browser.resolve()
        else:
            cache = tools_dir / ".browser-cache"
            if cache.is_dir():
                os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(cache))
            result = subprocess.run(
                ["node", "-e", "console.log(require('playwright').chromium.executablePath())"],
                cwd=tools_dir, capture_output=True, text=True, check=True, timeout=15)
            browser = Path(result.stdout.strip())
        if not browser.is_file():
            parser.error("Browser missing; run the documented npm ci and playwright install steps")
        os.environ["TRACE_MERMAID_BROWSER"] = str(browser)
        print(subprocess.check_output([str(browser), "--version"], text=True).strip(), flush=True)
    else:
        os.environ.pop("TRACE_REQUIRE_BROWSER", None)
    suite = unittest.TestLoader().discover(str(HERE), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
