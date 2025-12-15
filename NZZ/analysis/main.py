"""Unified CLI wrapper for the analysis scripts.

Usage examples:
  python NZZ/analysis/main.py author-network --visualize --run-baseline
  python NZZ/analysis/main.py cluster-analysis --limit 2000
  python NZZ/analysis/main.py assortativity --limit 2000 --largest-component
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path
from textwrap import dedent


COMMAND_MODULES = {
    "author-network": "NZZ.analysis.author_network",
    "cluster-analysis": "NZZ.analysis.cluster_analysis",
    "assortativity": "NZZ.analysis.assortativity_multilayer",
    "average-path": "NZZ.analysis.average_path_length_diameter",
    "centralities": "NZZ.analysis.centralities",
    "analyser": "NZZ.analysis.analyser"
}

# Default arguments we want to inject when running everything sequentially.
RUN_ALL_DEFAULT_ARGS = {
    # show all three visual layers plus the random baseline
    "author-network": [
        "--visualize",
        "--visualize-target",
        "combined",
        "--visualize-weight-threshold",
        "1",
        "--run-baseline",
    ],
}


def build_parser() -> argparse.ArgumentParser:
    descriptions = "\n".join(
        f"  {name:<18} → {module}" for name, module in COMMAND_MODULES.items()
    )
    parser = argparse.ArgumentParser(
        description="Run any analysis/visualization script through a single entry point.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent(
            f"""
            Available commands:
            {descriptions}

            Pass the original script arguments after the command, e.g.
              python NZZ/analysis/main.py author-network --limit 2000 --visualize
            """
        ),
    )
    parser.add_argument(
        "command",
        choices=list(COMMAND_MODULES.keys()) + ["run-all"],
        help="Which analysis command to run, or 'run-all' to execute every script sequentially.",
    )
    parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded verbatim to the selected command.",
    )
    return parser


def dispatch(command: str, script_args: list[str]) -> None:
    module = COMMAND_MODULES[command]
    old_argv = sys.argv.copy()
    sys.argv = [module.rsplit(".", 1)[-1], *script_args]
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    finally:
        sys.argv = old_argv


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run-all":
        for name in COMMAND_MODULES:
            print(f"\n=== Running {name} ===")
            dispatch(name, RUN_ALL_DEFAULT_ARGS.get(name, []))
        return
    dispatch(args.command, args.script_args)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    main()
