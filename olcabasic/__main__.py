"""
olcaBASIC — entry point.

Usage:
    python -m olcabasic              Interactive REPL
    python -m olcabasic run file.baslca  Run a program
    python -m olcabasic --port 8090   Connect on a different port
"""

import argparse
import sys
import logging

# Suppress noisy 404 warnings from olca-ipc internals
logging.basicConfig(level=logging.ERROR)

BANNER = r"""
            ___  _     ____    _    ____    _    ____  _  ____
           / _ \| |   / ___|  / \  | __ )  / \  / ___|| |/ ___|
          | | | | |  | |     / _ \ |  _ \ / _ \ \___ \| | |
          | |_| | |__| |___ / ___ \| |_) / ___ \ ___) | | |___
           \___/|_____\____/_/   \_\____/_/   \_\____/|_|\____|

     A simplified language to control openLCA, borrowing heavily
              from the BASIC programming language (1964)

                         by Below280
"""

from . import __version__ as VERSION


def main():
    parser = argparse.ArgumentParser(
        description="olcaBASIC — BASIC-like language for openLCA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command", nargs="?", default=None,
        help="'run' to execute a .baslca file",
    )
    parser.add_argument(
        "file", nargs="?", default=None,
        help="Path to .baslca file (used with 'run')",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="openLCA IPC port (default: 8080)",
    )
    parser.add_argument(
        "--no-connect", action="store_true",
        help="Start without connecting to openLCA (offline mode)",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"olcaBASIC {VERSION}",
    )

    args = parser.parse_args()

    print(BANNER)
    print(f"  olcaBASIC v{VERSION}")

    # Import here so startup errors are caught cleanly
    from .repl import REPL
    from .interpreter import Interpreter
    from .bridge import LCABridge

    # Connect to openLCA
    bridge = None
    if not args.no_connect:
        bridge = LCABridge(port=args.port)
        if bridge.connect():
            info = bridge.database_info()
            family = info.get("database_family", "unknown")
            procs = info.get("processes", "?")
            methods = info.get("impact_methods", "?")
            print(f"  Connected to openLCA on port {args.port}")
            print(f"  Database: {procs} processes, {methods} methods")
            print(f"  Family:   {family} (auto-detected)")
        else:
            print(f"\n  WARNING: Cannot connect to openLCA on port {args.port}")
            print("  Start the IPC server in openLCA:")
            print("    Tools > Developer Tools > IPC Server > play button")
            print("  Running in offline mode (search/build/calculate disabled)\n")
            bridge = None
    else:
        print("  Offline mode (no openLCA connection)")

    print("  Ready.\n")

    interpreter = Interpreter(bridge)

    if args.command == "run" and args.file:
        # Program mode: run a .baslca file
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                source = f.read()
            interpreter.run_program(source, filename=args.file)
        except FileNotFoundError:
            print(f"File not found: {args.file}")
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        # Interactive REPL
        repl = REPL(interpreter)
        repl.run()


if __name__ == "__main__":
    main()
