"""Rich-based tree rendering for proctree."""

from __future__ import annotations

from typing import Optional
from dataclasses import dataclass
from enum import Enum

from rich.console import Console
from rich.tree import Tree
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich import box

from .tree import ProcessNode, build_tree, get_root_processes
from .detect import find_zombies, find_orphans, get_subtree_resources


class SortBy(Enum):
    """Sort options for process display."""
    PID = "pid"
    CPU = "cpu"
    MEMORY = "memory"
    NAME = "name"
    NAME_PID = "name_pid"


def cpu_color(cpu: float, threshold: float = 70.0) -> str:
    """Return color name based on CPU usage."""
    if cpu >= 80:
        return "red"
    elif cpu >= threshold:
        return "yellow"
    return "green"


def mem_color(mem: float, threshold: float = 70.0) -> str:
    """Return color name based on memory usage."""
    if mem >= 80:
        return "red"
    elif mem >= threshold:
        return "yellow"
    return "green"


def status_symbol(node: ProcessNode) -> str:
    """Return status indicator symbol."""
    if node.is_zombie:
        return "[Z]"
    if node.is_orphan:
        return "[O]"
    return ""


def resource_bar(node: ProcessNode, width: int = 8) -> Text:
    """Create a mini resource usage bar."""
    cpu_bar = int(node.cpu_percent / 12.5)
    cpu_bar = min(cpu_bar, 8)
    cpu_str = "█" * cpu_bar + "░" * (8 - cpu_bar)
    cpu_colored = Text(cpu_str, style=cpu_color(node.cpu_percent))

    mem_bar = int(node.memory_percent / 12.5)
    mem_bar = min(mem_bar, 8)
    mem_str = "█" * mem_bar + "░" * (8 - mem_bar)
    mem_colored = Text(mem_str, style=mem_color(node.memory_percent))

    return Text.assemble(
        cpu_colored, " ", mem_colored
    )


def render_process_node(
    node: ProcessNode,
    show_resources: bool = True,
    show_cmdline: bool = False,
    depth: int = 0,
    max_depth: Optional[int] = None,
) -> Text:
    """Render a single process node as colored text."""
    parts = []

    status = status_symbol(node)
    if status:
        parts.append(Text(status, style="bold red"))

    pid_text = Text(f"[{node.pid}]", style="cyan")
    parts.append(pid_text)

    name_text = Text(node.display_name, style="bold white")
    parts.append(Text(" "))
    parts.append(name_text)

    if show_resources:
        parts.append(Text(" "))
        parts.append(resource_bar(node))

    if show_cmdline and node.cmdline and len(node.cmdline) > 1:
        parts.append(Text(f" {' '.join(node.cmdline[1:4])}", style="dim"))

    if node.is_zombie:
        parts.append(Text(" [ZOMBIE]", style="bold red"))
    elif node.is_orphan:
        parts.append(Text(" [ORPHAN]", style="bold yellow"))

    return Text.assemble(*parts)


def render_tree(
    proc_map: dict[int, ProcessNode],
    sort_by: SortBy = SortBy.PID,
    max_depth: Optional[int] = None,
    show_resources: bool = True,
    show_cmdline: bool = False,
    filter_user: Optional[str] = None,
    filter_name: Optional[str] = None,
    cpu_threshold: float = 0.0,
    memory_threshold: float = 0.0,
    show_subtree_only: Optional[int] = None,
) -> Tree:
    """Build a rich Tree from the process map."""

    def node_matches(node: ProcessNode) -> bool:
        if filter_user and filter_user not in node.username:
            return False
        if filter_name and filter_name.lower() not in node.name.lower():
            return False
        if cpu_threshold and node.cpu_percent < cpu_threshold:
            return False
        if memory_threshold and node.memory_percent < memory_threshold:
            return False
        return True

    def _filter_subtree(node: ProcessNode, fmap: dict[int, ProcessNode]) -> bool:
        if node.pid not in fmap:
            return False
        has_match = node_matches(node)
        surviving_children = []
        for child in node.children:
            if _filter_subtree(child, fmap):
                surviving_children.append(child)
                has_match = True
        if node.pid in fmap:
            fmap[node.pid].children = surviving_children
        return has_match

    filtered = {
        pid: node for pid, node in proc_map.items()
        if node_matches(node)
    }

    if show_subtree_only and show_subtree_only in filtered:
        root_nodes = [filtered[show_subtree_only]]
    else:
        root_nodes = get_root_processes(filtered)
        for node in root_nodes:
            _filter_subtree(node, filtered)

    def sort_nodes(nodes: list[ProcessNode]) -> list[ProcessNode]:
        if sort_by == SortBy.PID:
            return sorted(nodes, key=lambda n: n.pid)
        elif sort_by == SortBy.CPU:
            return sorted(nodes, key=lambda n: n.cpu_percent, reverse=True)
        elif sort_by == SortBy.MEMORY:
            return sorted(nodes, key=lambda n: n.memory_percent, reverse=True)
        elif sort_by == SortBy.NAME:
            return sorted(nodes, key=lambda n: n.name.lower())
        elif sort_by == SortBy.NAME_PID:
            return sorted(nodes, key=lambda n: (n.name.lower(), n.pid))
        return sorted(nodes, key=lambda n: n.pid)

    def build_rich_tree(node: ProcessNode, tree: Tree, depth: int) -> None:
        label = render_process_node(
            node,
            show_resources=show_resources,
            show_cmdline=show_cmdline,
            depth=depth,
            max_depth=max_depth,
        )

        if not node.children or (max_depth is not None and depth >= max_depth):
            tree.add(label)
            return

        child_tree = Tree(label)
        sorted_children = sort_nodes(node.children)
        for child in sorted_children:
            build_rich_tree(child, child_tree, depth + 1)
        tree.add(child_tree)

    if not filtered:
        return Tree("No processes match filters")

    if len(root_nodes) == 1 and not show_subtree_only:
        root = root_nodes[0]
        label = render_process_node(
            root, show_resources=show_resources, show_cmdline=show_cmdline
        )
        tree = Tree(label)
        sorted_children = sort_nodes(root.children)
        for child in sorted_children:
            build_rich_tree(child, tree, 1)
    else:
        sorted_roots = sort_nodes(root_nodes)
        label_text = Text(f"Process Tree ({len(filtered)} processes)", style="bold cyan")
        tree = Tree(label_text)
        for root in sorted_roots:
            root_label = render_process_node(
                root, show_resources=show_resources, show_cmdline=show_cmdline
            )
            subtree = Tree(root_label)
            sorted_children = sort_nodes(root.children)
            for child in sorted_children:
                build_rich_tree(child, subtree, 1)
            if len(root_nodes) > 1:
                tree.add(subtree)
            else:
                for child in sorted_children:
                    build_rich_tree(child, tree, 1)

    return tree


def render_summary_table(
    proc_map: dict[int, ProcessNode],
    sort_by: SortBy = SortBy.MEMORY,
    limit: int = 20,
) -> Table:
    """Render a summary table of top processes."""
    table = Table(
        title="Top Processes by Resource Usage",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("PID", style="cyan", width=7)
    table.add_column("NAME", style="white", width=20)
    table.add_column("USER", style="blue", width=15)
    table.add_column("CPU %", justify="right", width=8)
    table.add_column("MEM %", justify="right", width=8)
    table.add_column("STATUS", style="dim", width=10)

    sorted_procs = sorted(
        proc_map.values(),
        key=lambda p: (
            p.cpu_percent if sort_by == SortBy.CPU else p.memory_percent
        ),
        reverse=True,
    )[:limit]

    for proc in sorted_procs:
        status = "ZOMBIE" if proc.is_zombie else proc.status.upper()
        table.add_row(
            str(proc.pid),
            proc.display_name[:20],
            proc.username[:15],
            f"{proc.cpu_percent:.1f}",
            f"{proc.memory_percent:.1f}",
            status[:10],
        )

    return table


def render_zombies(zombies: list[ProcessNode]) -> Table:
    """Render a table of zombie processes."""
    table = Table(
        title=f"Zombie Processes ({len(zombies)} found)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold red",
    )
    table.add_column("PID", style="cyan", width=7)
    table.add_column("NAME", style="white", width=20)
    table.add_column("PPID", style="yellow", width=7)
    table.add_column("STATUS", style="red", width=10)

    for z in zombies:
        table.add_row(str(z.pid), z.name, str(z.parent_pid) if z.parent_pid else "?", z.status)

    return table
