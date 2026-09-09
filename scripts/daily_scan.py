"""Build or send the FastComps Daily Clinic Market Scan."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

load_dotenv()

from newsletter import build_daily_scan, render_daily_scan_html, send_daily_scan, send_daily_scan_to_all


def main() -> int:
    parser = argparse.ArgumentParser(description="FastComps Daily Clinic Market Scan")
    parser.add_argument("--to", default=os.getenv("TO_EMAIL", ""))
    parser.add_argument("--all", action="store_true", help="Send to every registered user with daily scans enabled")
    parser.add_argument("--dry-run", action="store_true", help="Render without sending")
    args = parser.parse_args()
    if args.all:
        result = send_daily_scan_to_all()
    else:
        if not args.to:
            parser.error("--to or TO_EMAIL is required unless --all is used")
        scan = build_daily_scan()
        if args.dry_run:
            html = render_daily_scan_html(scan, recipient_email=args.to)
            print(f"daily_scan_ready bytes={len(html)} signals={len(scan['signals'])} recipient={args.to}")
            return 0
        result = send_daily_scan(args.to, scan=scan, record=False)
    print(f"ok={result.get('ok')} sent={result.get('sent', int(bool(result.get('ok'))))} total={result.get('total', 1)}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
