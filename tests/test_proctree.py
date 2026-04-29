"""Tests for proctree."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import psutil

from proctree.tree import ProcessNode, build_tree, get_root_processes
from proctree.detect import find_zombies, find_orphans, find_resource_hogs, get_subtree_resources
from proctree.render import (
    SortBy,
    cpu_color,
    mem_color,
    status_symbol,
    resource_bar,
)


class TestProcessNode:
    def test_display_name_from_cmdline(self):
        node = ProcessNode(
            pid=1, name="bash", username="root",
            cmdline=["/bin/bash", "-c", "echo hello"]
        )
        assert node.display_name == "bash"

    def test_display_name_no_cmdline(self):
        node = ProcessNode(pid=1, name="kernel_task", username="root")
        assert node.display_name == "kernel_task"

    def test_display_name_path_stripping(self):
        node = ProcessNode(
            pid=1, name="python", username="root",
            cmdline=["/usr/bin/python3.12", "-m", "http.server"]
        )
        assert node.display_name == "python3.12"

    def test_is_zombie_detection(self):
        node = ProcessNode(
            pid=1, name="zombie", username="root",
            status=psutil.STATUS_ZOMBIE
        )
        assert node.is_zombie is True


class TestCpuColor:
    def test_low_cpu_green(self):
        assert cpu_color(30.0) == "green"

    def test_medium_cpu_yellow(self):
        assert cpu_color(75.0) == "yellow"

    def test_high_cpu_red(self):
        assert cpu_color(90.0) == "red"


class TestMemColor:
    def test_low_mem_green(self):
        assert mem_color(30.0) == "green"

    def test_high_mem_red(self):
        assert mem_color(90.0) == "red"


class TestStatusSymbol:
    def test_zombie_symbol(self):
        node = ProcessNode(pid=1, name="z", username="u", _is_zombie=True)
        assert status_symbol(node) == "[Z]"

    def test_orphan_symbol(self):
        node = ProcessNode(pid=1, name="o", username="u", _is_orphan=True)
        assert status_symbol(node) == "[O]"

    def test_normal_no_symbol(self):
        node = ProcessNode(pid=1, name="n", username="u")
        assert status_symbol(node) == ""


class TestGetSubtreeResources:
    def test_single_node(self):
        node = ProcessNode(pid=1, name="p", username="u", cpu_percent=10.0, memory_percent=5.0)
        cpu, mem = get_subtree_resources(node)
        assert cpu == 10.0
        assert mem == 5.0

    def test_with_children(self):
        child = ProcessNode(pid=2, name="c", username="u", cpu_percent=20.0, memory_percent=10.0)
        parent = ProcessNode(pid=1, name="p", username="u", cpu_percent=10.0, memory_percent=5.0)
        parent.children = [child]
        cpu, mem = get_subtree_resources(parent)
        assert cpu == 30.0
        assert mem == 15.0

    def test_nested_children(self):
        grandchild = ProcessNode(pid=3, name="gc", username="u", cpu_percent=5.0, memory_percent=2.0)
        child = ProcessNode(pid=2, name="c", username="u", cpu_percent=10.0, memory_percent=5.0)
        child.children = [grandchild]
        parent = ProcessNode(pid=1, name="p", username="u", cpu_percent=15.0, memory_percent=8.0)
        parent.children = [child]
        cpu, mem = get_subtree_resources(parent)
        assert cpu == 30.0
        assert mem == 15.0


class TestBuildTree:
    @patch("proctree.tree.psutil.process_iter")
    def test_build_tree_basic(self, mock_iter):
        mock_proc1 = Mock()
        mock_proc1.info = {
            "pid": 1,
            "name": "init",
            "username": "root",
            "cpu_percent": 0.5,
            "memory_percent": 1.2,
            "status": psutil.STATUS_RUNNING,
            "create_time": 1000.0,
            "cmdline": ["/sbin/init"],
            "ppid": 0,
        }
        mock_proc2 = Mock()
        mock_proc2.info = {
            "pid": 2,
            "name": "bash",
            "username": "user",
            "cpu_percent": 2.0,
            "memory_percent": 0.8,
            "status": psutil.STATUS_RUNNING,
            "create_time": 1010.0,
            "cmdline": ["/bin/bash"],
            "ppid": 1,
        }
        mock_iter.return_value = [mock_proc1, mock_proc2]

        proc_map = build_tree()

        assert len(proc_map) == 2
        assert 1 in proc_map
        assert 2 in proc_map
        assert proc_map[2].parent_pid == 1

    @patch("proctree.tree.psutil.process_iter")
    def test_zombie_detection(self, mock_iter):
        mock_proc = Mock()
        mock_proc.info = {
            "pid": 1,
            "name": "defunct",
            "username": "root",
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "status": psutil.STATUS_ZOMBIE,
            "create_time": 1000.0,
            "cmdline": [],
            "ppid": 1,
        }
        mock_iter.return_value = [mock_proc]

        proc_map = build_tree()
        assert proc_map[1].is_zombie is True


class TestFindZombies:
    @patch("proctree.detect.build_tree")
    def test_find_zombies(self, mock_build):
        mock_build.return_value = {
            1: ProcessNode(pid=1, name="z1", username="u", status=psutil.STATUS_ZOMBIE),
            2: ProcessNode(pid=2, name="r1", username="u", status=psutil.STATUS_RUNNING),
        }
        zombies = find_zombies()
        assert len(zombies) == 1
        assert zombies[0].name == "z1"


class TestFindResourceHogs:
    @patch("proctree.detect.build_tree")
    def test_find_hogs_cpu(self, mock_build):
        mock_build.return_value = {
            1: ProcessNode(pid=1, name="high", username="u", cpu_percent=80.0, memory_percent=10.0),
            2: ProcessNode(pid=2, name="low", username="u", cpu_percent=5.0, memory_percent=2.0),
        }
        hogs = find_resource_hogs(cpu_threshold=50.0)
        assert len(hogs) == 1
        assert hogs[0].name == "high"

    @patch("proctree.detect.build_tree")
    def test_find_hogs_memory(self, mock_build):
        mock_build.return_value = {
            1: ProcessNode(pid=1, name="high", username="u", cpu_percent=5.0, memory_percent=80.0),
            2: ProcessNode(pid=2, name="low", username="u", cpu_percent=2.0, memory_percent=2.0),
        }
        hogs = find_resource_hogs(memory_threshold=50.0)
        assert len(hogs) == 1


class TestGetRootProcesses:
    def test_root_with_no_parent(self):
        proc_map = {
            1: ProcessNode(pid=1, name="init", username="root", parent_pid=None),
            2: ProcessNode(pid=2, name="bash", username="user", parent_pid=1),
        }
        roots = get_root_processes(proc_map)
        assert len(roots) == 1
        assert roots[0].pid == 1

    def test_orphan_not_root(self):
        proc_map = {
            1: ProcessNode(pid=1, name="init", username="root", parent_pid=None),
            999: ProcessNode(pid=999, name="orphan", username="user", parent_pid=9999, _is_orphan=True),
        }
        roots = get_root_processes(proc_map)
        assert len(roots) == 1
        assert roots[0].pid == 1


class TestCliIntegration:
    def test_import_main(self):
        from proctree.cli import main, console
        assert callable(main)

    def test_sort_by_enum(self):
        assert SortBy.PID.value == "pid"
        assert SortBy.CPU.value == "cpu"
        assert SortBy.MEMORY.value == "memory"
