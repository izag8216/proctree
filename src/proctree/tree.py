"""Process tree data structures and construction using psutil."""

from __future__ import annotations

import psutil
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessNode:
    """A single process node in the tree."""

    pid: int
    name: str
    username: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    status: str = ""
    create_time: float = 0.0
    cmdline: list[str] = field(default_factory=list)
    parent_pid: Optional[int] = None
    children: list[ProcessNode] = field(default_factory=list)
    _is_zombie: bool = field(default=False, repr=False)
    _is_orphan: bool = field(default=False, repr=False)

    @property
    def is_zombie(self) -> bool:
        """True if process is in zombie state."""
        return self._is_zombie or self.status == psutil.STATUS_ZOMBIE

    @is_zombie.setter
    def is_zombie(self, value: bool) -> None:
        self._is_zombie = value

    @property
    def is_orphan(self) -> bool:
        """True if process parent is gone but process is still alive."""
        return self._is_orphan

    @is_orphan.setter
    def is_orphan(self, value: bool) -> None:
        self._is_orphan = value

    @property
    def display_name(self) -> str:
        """Return display name, falling back to cmdline[0] or name."""
        if self.cmdline:
            return self.cmdline[0].split("/")[-1]
        return self.name

    @property
    def memory_mb(self) -> float:
        """Return memory in MB (approximate from memory_percent)."""
        try:
            mem_info = psutil.Process(self.pid).memory_info()
            return mem_info.rss / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0


def build_tree() -> dict[int, ProcessNode]:
    """
    Build complete process tree from psutil.

    Returns:
        Dict mapping pid -> ProcessNode for all processes.
    """
    proc_map: dict[int, ProcessNode] = {}

    for proc in psutil.process_iter(
        ["pid", "name", "username", "cpu_percent", "memory_percent",
         "status", "create_time", "cmdline", "ppid"]
    ):
        try:
            info = proc.info
            pid = info["pid"]
            node = ProcessNode(
                pid=pid,
                name=info["name"] or "",
                username=info["username"] or "",
                cpu_percent=info["cpu_percent"] or 0.0,
                memory_percent=info["memory_percent"] or 0.0,
                status=info["status"] or "",
                create_time=info["create_time"] or 0.0,
                cmdline=info["cmdline"] or [],
                parent_pid=info["ppid"],
            )
            node._is_zombie = info["status"] == psutil.STATUS_ZOMBIE
            proc_map[pid] = node
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    all_pids = set(proc_map.keys())

    for pid, node in proc_map.items():
        parent_pid = node.parent_pid
        if parent_pid and parent_pid in proc_map:
            proc_map[parent_pid].children.append(node)
        elif parent_pid and parent_pid not in all_pids:
            node.is_orphan = True

    return proc_map


def get_root_processes(proc_map: dict[int, ProcessNode]) -> list[ProcessNode]:
    """Get processes that have no parent in our map (roots of the tree)."""
    roots = []
    for node in proc_map.values():
        ppid = node.parent_pid
        if ppid is None or ppid == 0 or ppid not in proc_map:
            if ppid is not None and ppid != 0 and node.is_orphan:
                continue
            roots.append(node)
    return sorted(roots, key=lambda n: n.pid)
