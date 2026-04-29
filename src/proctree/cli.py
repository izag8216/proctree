"""CLI interface for proctree."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from rich import box

from . import __version__
from .tree import build_tree, get_root_processes
from .detect import find_zombies, find_orphans, find_resource_hogs, get_subtree_resources
from .render import (
    render_tree,
    render_summary_table,
    render_zombies,
    SortBy,
    cpu_color,
    mem_color,
)


console = Console()


def cmd_show(args: argparse.Namespace) -> int:
    """Show process tree."""
    proc_map = build_tree()
    tree = render_tree(
        proc_map,
        sort_by=SortBy(args.sort_by),
        max_depth=args.max_depth,
        show_resources=not args.no_resources,
        show_cmdline=args.show_cmdline,
        filter_user=args.user,
        filter_name=args.name,
        cpu_threshold=args.min_cpu,
        memory_threshold=args.min_mem,
        show_subtree_only=args.subtree,
    )
    console.print(tree)
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    """Find processes and optionally show their subtrees."""
    proc_map = build_tree()
    matching = [
        p for p in proc_map.values()
        if args.pattern.lower() in p.name.lower()
           or args.pattern in str(p.pid)
    ]

    if not matching:
        console.print(f"[yellow]No processes matching '{args.pattern}'[/yellow]")
        return 0

    console.print(f"[cyan]Found {len(matching)} matching processes:[/cyan]\n")
    for proc in matching[:20]:
        console.print(f"  [{proc.pid}] {proc.display_name} ({proc.username})")
        if args.show_subtree and proc.parent_pid in proc_map:
            console.print(f"    Parent: [{proc.parent_pid}] {proc_map[proc.parent_pid].display_name}")
        total_cpu, total_mem = get_subtree_resources(proc)
        console.print(f"    Subtree: CPU={total_cpu:.1f}% MEM={total_mem:.1f}%")
        console.print()

    return 0


def cmd_zombies(args: argparse.Namespace) -> int:
    """Find and display zombie processes."""
    proc_map = build_tree()
    zombies = find_zombies(proc_map)

    if not zombies:
        console.print("[green]No zombie processes found.[/green]")
        return 0

    console.print(render_zombies(zombies))

    if args.kill:
        for z in zombies:
            try:
                import os
                import signal
                console.print(f"[yellow]Sending SIGTERM to zombie [{z.pid}]...[/yellow]")
                os.kill(z.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError) as e:
                console.print(f"[red]Failed to kill [{z.pid}]: {e}[/red]")

    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Watch top processes in real-time."""
    def refresh():
        proc_map = build_tree()
        return proc_map

    with Live(
        refresh_per_second=args.refresh,
        console=console,
        transient=False,
    ) as live:
        for _ in range(args.count or 999999):
            proc_map = refresh()
            table = render_summary_table(
                proc_map,
                sort_by=SortBy(args.sort_by),
                limit=args.top,
            )
            live.update(Panel(
                table,
                title=f"proctree watch -- {time.strftime('%H:%M:%S')}",
                border_style="cyan",
            ))
            time.sleep(args.refresh)

    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export process tree as JSON."""
    proc_map = build_tree()

    def node_to_dict(node: ProcessNode) -> dict:
        return {
            "pid": node.pid,
            "name": node.name,
            "display_name": node.display_name,
            "username": node.username,
            "cpu_percent": node.cpu_percent,
            "memory_percent": node.memory_percent,
            "status": node.status,
            "is_zombie": node.is_zombie,
            "is_orphan": node.is_orphan,
            "parent_pid": node.parent_pid,
            "cmdline": node.cmdline,
            "children": [node_to_dict(c) for c in node.children],
        }

    roots = get_root_processes(proc_map)
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_processes": len(proc_map),
        "zombie_count": len(find_zombies(proc_map)),
        "orphan_count": len(find_orphans(proc_map)),
        "processes": [node_to_dict(r) for r in roots],
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        console.print(f"[green]Exported to {args.output}[/green]")
    else:
        console.print_json(json.dumps(output, indent=2))

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Show process statistics."""
    proc_map = build_tree()

    table = Table(
        title="Process Statistics",
        box=box.ROUNDED,
    )
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")

    table.add_row("Total Processes", str(len(proc_map)))

    zombies = find_zombies(proc_map)
    orphans = find_orphans(proc_map)
    table.add_row("Zombies", str(len(zombies)))
    table.add_row("Orphans", str(len(orphans)))

    if proc_map:
        avg_cpu = sum(p.cpu_percent for p in proc_map.values()) / len(proc_map)
        avg_mem = sum(p.memory_percent for p in proc_map.values()) / len(proc_map)
        table.add_row("Avg CPU %", f"{avg_cpu:.1f}")
        table.add_row("Avg Memory %", f"{avg_mem:.1f}")

        max_cpu = max(proc_map.values(), key=lambda p: p.cpu_percent)
        max_mem = max(proc_map.values(), key=lambda p: p.memory_percent)
        table.add_row("Max CPU Process", f"{max_cpu.display_name} ({max_cpu.cpu_percent:.1f}%)")
        table.add_row("Max Memory Process", f"{max_mem.display_name} ({max_mem.memory_percent:.1f}%)")

    console.print(table)
    return 0


def main() -> int:
    """Entry point for proctree CLI."""
    parser = argparse.ArgumentParser(
        prog="proctree",
        description="Process Tree Visualizer with resource annotations and zombie detection",
    )
    parser.add_argument("--version", action="version", version=f"proctree {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Display process tree")
    show_parser.add_argument("--sort-by", choices=["pid", "cpu", "memory", "name", "name_pid"],
                            default="pid", help="Sort order")
    show_parser.add_argument("--max-depth", type=int, default=None, help="Max tree depth")
    show_parser.add_argument("--no-resources", action="store_true", help="Hide resource bars")
    show_parser.add_argument("--show-cmdline", action="store_true", help="Show full command line")
    show_parser.add_argument("--user", type=str, default=None, help="Filter by username")
    show_parser.add_argument("--name", type=str, default=None, help="Filter by process name")
    show_parser.add_argument("--min-cpu", type=float, default=0.0, help="Min CPU %% to show")
    show_parser.add_argument("--min-mem", type=float, default=0.0, help="Min Memory %% to show")
    show_parser.add_argument("--subtree", type=int, metavar="PID", default=None,
                            help="Show only subtree of given PID")
    show_parser.set_defaults(func=cmd_show)

    find_parser = subparsers.add_parser("find", help="Find processes by name or PID")
    find_parser.add_argument("pattern", type=str, help="Pattern to search")
    find_parser.add_argument("--show-subtree", action="store_true", help="Show subtree info")
    find_parser.set_defaults(func=cmd_find)

    zombie_parser = subparsers.add_parser("zombies", help="Find zombie processes")
    zombie_parser.add_argument("--kill", action="store_true", help="Attempt to kill zombies")
    zombie_parser.set_defaults(func=cmd_zombies)

    watch_parser = subparsers.add_parser("watch", help="Watch top processes")
    watch_parser.add_argument("--top", type=int, default=15, help="Number of processes")
    watch_parser.add_argument("--sort-by", choices=["pid", "cpu", "memory"],
                              default="memory", help="Sort order")
    watch_parser.add_argument("--refresh", type=float, default=2.0, help="Refresh interval (s)")
    watch_parser.add_argument("--count", type=int, default=None, help="Number of refreshes")
    watch_parser.set_defaults(func=cmd_watch)

    export_parser = subparsers.add_parser("export", help="Export process tree as JSON")
    export_parser.add_argument("--output", "-o", type=str, default=None,
                               help="Output file (default: stdout)")
    export_parser.set_defaults(func=cmd_export)

    stats_parser = subparsers.add_parser("stats", help="Show process statistics")
    stats_parser.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
