"""Hermetic tests for SE Installer models."""

from __future__ import annotations

import pytest

from se_installer.models import (
    InstallableComponent,
    InstallationPlan,
    InstallStatus,
    OSType,
    ComponentType,
)


class TestInstallableComponent:
    """Tests for InstallableComponent model."""

    def test_component_creation(self):
        comp = InstallableComponent(
            id="test",
            name="Test Component",
            description="A test component",
            component_type=ComponentType.MCP,
            requires=["dep1"],
            supported_os=[OSType.WINDOWS, OSType.LINUX],
        )
        assert comp.id == "test"
        assert comp.name == "Test Component"
        assert comp.component_type == ComponentType.MCP
        assert comp.requires == ["dep1"]
        assert OSType.WINDOWS in comp.supported_os

    def test_is_supported_on(self):
        comp = InstallableComponent(
            id="test",
            name="Test",
            description="Test",
            component_type=ComponentType.MCP,
            supported_os=[OSType.WINDOWS, OSType.LINUX],
        )
        assert comp.is_supported_on(OSType.WINDOWS) is True
        assert comp.is_supported_on(OSType.LINUX) is True
        assert comp.is_supported_on(OSType.MACOS) is False


class TestInstallationPlan:
    """Tests for InstallationPlan model."""

    def test_plan_creation(self):
        plan = InstallationPlan()
        assert plan.components == []
        assert plan.os_type == OSType.WINDOWS
        assert plan.target_runtimes == ["opencode"]
        assert plan.dry_run is False

    def test_topological_sort_simple(self):
        """Test topological sort with simple dependencies."""
        comp_a = InstallableComponent(
            id="a", name="A", description="A", component_type=ComponentType.MCP, requires=[]
        )
        comp_b = InstallableComponent(
            id="b", name="B", description="B", component_type=ComponentType.MCP, requires=["a"]
        )
        comp_c = InstallableComponent(
            id="c", name="C", description="C", component_type=ComponentType.MCP, requires=["b"]
        )

        plan = InstallationPlan(components=[comp_c, comp_a, comp_b])  # shuffled
        ordered = plan.topological_sort()

        assert [c.id for c in ordered] == ["a", "b", "c"]

    def test_topological_sort_multiple_deps(self):
        """Test topological sort with multiple dependencies."""
        comp_a = InstallableComponent(id="a", name="A", description="A", component_type=ComponentType.MCP, requires=[])
        comp_b = InstallableComponent(id="b", name="B", description="B", component_type=ComponentType.MCP, requires=["a"])
        comp_c = InstallableComponent(id="c", name="C", description="C", component_type=ComponentType.MCP, requires=["a"])
        comp_d = InstallableComponent(id="d", name="D", description="D", component_type=ComponentType.MCP, requires=["b", "c"])

        plan = InstallationPlan(components=[comp_d, comp_b, comp_c, comp_a])
        ordered = plan.topological_sort()

        # a must be first, d must be last, b and c in between (order between b/c deterministic)
        ids = [c.id for c in ordered]
        assert ids[0] == "a"
        assert ids[-1] == "d"
        assert set(ids[1:3]) == {"b", "c"}

    def test_topological_sort_cycle_fallback(self):
        """Test that cycle detection returns original order as fallback."""
        comp_a = InstallableComponent(id="a", name="A", description="A", component_type=ComponentType.MCP, requires=["b"])
        comp_b = InstallableComponent(id="b", name="B", description="B", component_type=ComponentType.MCP, requires=["a"])

        plan = InstallationPlan(components=[comp_a, comp_b])
        ordered = plan.topological_sort()

        # Should return original selection order as fallback
        assert len(ordered) == 2
        assert {c.id for c in ordered} == {"a", "b"}

    def test_topological_sort_skips_skipped(self):
        """Test that SKIPPED components are excluded from sort."""
        comp_a = InstallableComponent(id="a", name="A", description="A", component_type=ComponentType.MCP, requires=[])
        comp_b = InstallableComponent(id="b", name="B", description="B", component_type=ComponentType.MCP, requires=["a"])
        comp_b.status = InstallStatus.SKIPPED

        plan = InstallationPlan(components=[comp_a, comp_b])
        ordered = plan.topological_sort()

        assert [c.id for c in ordered] == ["a"]

    def test_get_selected_excludes_skipped(self):
        """Test get_selected excludes SKIPPED components."""
        comp_a = InstallableComponent(id="a", name="A", description="A", component_type=ComponentType.MCP)
        comp_b = InstallableComponent(id="b", name="B", description="B", component_type=ComponentType.MCP)
        comp_b.status = InstallStatus.SKIPPED

        plan = InstallationPlan(components=[comp_a, comp_b])
        selected = plan.get_selected()

        assert len(selected) == 1
        assert selected[0].id == "a"

    def test_get_by_id(self):
        comp_a = InstallableComponent(id="a", name="A", description="A", component_type=ComponentType.MCP)
        comp_b = InstallableComponent(id="b", name="B", description="B", component_type=ComponentType.MCP)

        plan = InstallationPlan(components=[comp_a, comp_b])
        found = plan.get_by_id("b")
        not_found = plan.get_by_id("c")

        assert found is comp_b
        assert not_found is None

    def test_get_dependencies(self):
        comp_a = InstallableComponent(id="a", name="A", description="A", component_type=ComponentType.MCP, requires=[])
        comp_b = InstallableComponent(id="b", name="B", description="B", component_type=ComponentType.MCP, requires=["a", "c"])
        comp_c = InstallableComponent(id="c", name="C", description="C", component_type=ComponentType.MCP, requires=[])

        plan = InstallationPlan(components=[comp_a, comp_b, comp_c])
        deps = plan.get_dependencies("b")

        assert len(deps) == 2
        assert {d.id for d in deps} == {"a", "c"}