#!/usr/bin/env python3
"""Readerme: fetch, curate, and serve your personalized reading feed."""

import argparse
import sys


def cmd_curate(args):
    from curator import curate, build_profile

    if args.profile_only:
        profile = build_profile(force_refresh=True)
        import json
        print(json.dumps(profile, ensure_ascii=False, indent=2))
        return

    result = curate(days=args.days, top_n=args.top)
    print(f"\n{len(result['articles'])} articles curated from {result['article_count_total']} candidates.")
    print("\nTop 5:")
    for a in result["articles"][:5]:
        print(f"  [{a['score']}] {a['title']}")
        print(f"       {a['reason']}\n")


def cmd_serve(args):
    from server import app
    ip = _local_ip()
    print(f"\nreaderme running at:")
    print(f"  Local:   http://localhost:{args.port}")
    if ip:
        print(f"  iPad:    http://{ip}:{args.port}")
    print()
    app.run(host="0.0.0.0", port=args.port, debug=args.debug)


def cmd_run(args):
    """Curate and then serve."""
    cmd_curate(args)
    print("\nStarting server...")
    cmd_serve(args)


def _local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="readerme — your personal content curator")
    sub = parser.add_subparsers(dest="command")

    # curate
    p_curate = sub.add_parser("curate", help="Fetch and curate articles")
    p_curate.add_argument("--days", type=int, default=2, help="How many days back to fetch (default: 2)")
    p_curate.add_argument("--top", type=int, default=7, help="Number of articles to curate (default: 7)")
    p_curate.add_argument("--profile-only", action="store_true", help="Only rebuild the profile")

    # serve
    p_serve = sub.add_parser("serve", help="Start the web server")
    p_serve.add_argument("--port", type=int, default=5555, help="Port (default: 5555)")
    p_serve.add_argument("--debug", action="store_true")

    # run (curate + serve)
    p_run = sub.add_parser("run", help="Curate and serve (default)")
    p_run.add_argument("--days", type=int, default=2)
    p_run.add_argument("--top", type=int, default=7)
    p_run.add_argument("--port", type=int, default=5555)
    p_run.add_argument("--debug", action="store_true")
    p_run.add_argument("--profile-only", action="store_true")

    # curate-spain
    sub.add_parser("curate-spain", help="Fetch and curate Spain political risk news")

    # nightly
    sub.add_parser("nightly", help="Run nightly cycle (process feedback + re-curate)")

    args = parser.parse_args()

    if args.command == "curate":
        cmd_curate(args)
    elif args.command == "curate-spain":
        from spain import curate_spain
        from polls import fetch_and_process
        curate_spain()
        fetch_and_process()
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "nightly":
        from nightly import run_nightly
        run_nightly()
    else:
        # Default: run
        args.days = 2
        args.top = 7
        args.port = 5555
        args.debug = False
        args.profile_only = False
        cmd_run(args)


if __name__ == "__main__":
    main()
