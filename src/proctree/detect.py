"""Zombie and orphan process detection."""

from __future__ import annotations

from typing import Optional
from .tree import ProcessNode, build_tree


def find_zombies(proc_map: Optional[dict[int, ProcessNode]] = None) -> list[ProcessNode]:
    """Find all zombie processes."""
    if proc_map is None:
        proc_map = build_tree()
    return [p for p in proc_map.values() if p.is_zombie]


def find_orphans(proc_map: Optional[dict[int, ProcessNode]] = None) -> list[ProcessNode]:
    """Find all orphaned processes (parent is gone but process is alive)."""
    if proc_map is None:
        proc_map = build_tree()
    return [p for p in proc_map.values() if p.is_orphan]


def find_resource_hogs(
    proc_map: Optional[dict[int, ProcessNode]] = None,
    cpu_threshold: float = 50.0,
    memory_threshold: float = 50.0,
) -> list[ProcessNode]:
    """Find processes exceeding resource thresholds."""
    if proc_map is None:
        proc_map = build_tree()
    return [
        p for p in proc_map.values()
        if p.cpu_percent >= cpu_threshold or p.memory_percent >= memory_threshold
    ]


def get_subtree_resources(node: ProcessNode) -> tuple[float, float]:
    """Get total CPU and memory for a subtree (node + all descendants)."""
    total_cpu = node.cpu_percent
    total_mem = node.memory_percent
    for child in node.children:
        child_cpu, child_mem = get_subtree_resources(child)
        total_cpu += child_cpu
        total_mem += child_mem
    return total_cpu, total_mem
