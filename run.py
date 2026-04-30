#!/usr/bin/env python3
"""Readerme: fetch, curate, and serve your personalized reading feed."""

import argparse
import sys


def cmd_curate(args):
    from curator import curate

    result = curate()
    print(f"\n{len(result['articles'])} articles in main.json.")
    print("\nLatest 5:")
    for a in result["articles"][:5]:
        print(f"  [{a.get('site_name', '?')}] {a['title'][:80]}")


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
    sub.add_parser("curate", help="Fetch RSS deltas and update main.json")

    # serve
    p_serve = sub.add_parser("serve", help="Start the web server")
    p_serve.add_argument("--port", type=int, default=5555, help="Port (default: 5555)")
    p_serve.add_argument("--debug", action="store_true")

    # run (curate + serve)
    p_run = sub.add_parser("run", help="Curate and serve (default)")
    p_run.add_argument("--port", type=int, default=5555)
    p_run.add_argument("--debug", action="store_true")

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
        args.port = 5555
        args.debug = False
        cmd_run(args)


if __name__ == "__main__":
    main()
