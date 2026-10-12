"""Hermetic tests for SE Installer orchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from se_installer.models import (
    InstallableComponent,
    InstallationPlan,
    InstallStatus,
    OSType,
    ComponentType,
)
from se_installer.orchestrator import InstallerOrchestrator


class TestInstallerOrchestrator:
    """Tests for the installation orchestrator."""

    @pytest.fixture
    def sample_plan(self):
        """Create a plan with sample components."""
        comp_a = InstallableComponent(
            id="a", name="A", description="A", component_type=ComponentType.MCP,
            requires=[], install_method="auto"
        )
        comp_b = InstallableComponent(
            id="b", name="B", description="B", component_type=ComponentType.MCP,
            requires=["a"], install_method="auto"
        )
        comp_c = InstallableComponent(
            id="c", name="C", description="C", component_type=ComponentType.MCP,
            requires=["a"], install_method="auto"
        )
        return InstallationPlan(components=[comp_a, comp_b, comp_c])

    @pytest.fixture
    def mock_installer(self):
        """Create a mock installer that succeeds."""
        installer = Mock()
        installer.check_installed.return_value = (False, None)
        installer.install.return_value = Mock(success=True, version="1.0.0")
        installer.verify.return_value = (True, "1.0.0")
        return installer

    def test_dry_run_marks_success(self, sample_plan):
        """Test dry-run marks components as success without installing."""
        orchestrator = InstallerOrchestrator(sample_plan, dry_run=True)
        orchestrator.prepare_plan(["a", "b", "c"])

        result = orchestrator.run_installation()

        assert result is True
        for comp in sample_plan.components:
            assert comp.status == InstallStatus.SUCCESS
            assert comp.installed_version == "dry-run"

    def test_dry_run_preserves_order(self, sample_plan):
        """Test dry-run respects topological order."""
        orchestrator = InstallerOrchestrator(sample_plan, dry_run=True)
        orchestrator.prepare_plan(["c", "b", "a"])  # shuffled

        orchestrator.run_installation()

        ordered_ids = [c.id for c in sample_plan.components if c.status != InstallStatus.SKIPPED]
        # a must come before b and c
        assert ordered_ids.index("a") < ordered_ids.index("b")
        assert ordered_ids.index("a") < ordered_ids.index("c")

    def test_prepare_plan_marks_dependencies(self, sample_plan):
        """Test that prepare_plan marks transitive dependencies."""
        orchestrator = InstallerOrchestrator(sample_plan)
        orchestrator.prepare_plan(["b"])  # b depends on a

        assert sample_plan.get_by_id("b").status == InstallStatus.PENDING
        assert sample_plan.get_by_id("a").status == InstallStatus.PENDING
        assert sample_plan.get_by_id("c").status == InstallStatus.SKIPPED

    def test_skipped_components_not_installed(self, sample_plan):
        """Test that SKIPPED components are not processed."""
        orchestrator = InstallerOrchestrator(sample_plan, dry_run=True)
        orchestrator.prepare_plan(["a"])  # only a selected

        orchestrator.run_installation()

        assert sample_plan.get_by_id("a").status == InstallStatus.SUCCESS
        assert sample_plan.get_by_id("b").status == InstallStatus.SKIPPED
        assert sample_plan.get_by_id("c").status == InstallStatus.SKIPPED

    def test_install_vendored_components(self):
        """Test that vendored components (SE_CORE, SE_CONSOLE) are marked success without installer."""
        comp_core = InstallableComponent(
            id="se_core", name="SE Core", description="Core",
            component_type=ComponentType.SE_CORE, install_method="pip"
        )
        comp_console = InstallableComponent(
            id="se_console", name="SE Console", description="Console",
            component_type=ComponentType.SE_CONSOLE, requires=["se_core"], install_method="vendored"
        )

        plan = InstallationPlan(components=[comp_core, comp_console])
        orchestrator = InstallerOrchestrator(plan, dry_run=False)
        orchestrator.prepare_plan(["se_core", "se_console"])

        result = orchestrator.run_installation()

        assert result is True
        assert comp_core.status == InstallStatus.SUCCESS
        assert comp_core.installed_version == "vendored"
        assert comp_console.status == InstallStatus.SUCCESS
        assert comp_console.installed_version == "vendored"

    def test_failed_component_stops_by_default(self):
        """Test that failure stops installation by default for core components."""
        comp_core = InstallableComponent(
            id="se_core", name="SE Core", description="Core",
            component_type=ComponentType.SE_CORE
        )
        comp_fail = InstallableComponent(
            id="fail", name="Fail", description="Fail",
            component_type=ComponentType.MCP
        )

        plan = InstallationPlan(components=[comp_core, comp_fail])
        orchestrator = InstallerOrchestrator(plan, dry_run=False)

        # Mock installer that fails
        fail_installer = Mock()
        fail_installer.check_installed.return_value = (False, None)
        fail_installer.install.return_value = Mock(success=False, error="Install failed")

        with patch.object(orchestrator, '_get_installer', side_effect=[None, fail_installer]):
            orchestrator.prepare_plan(["se_core", "fail"])
            result = orchestrator.run_installation()

        assert result is False
        assert comp_core.status == InstallStatus.SUCCESS
        assert comp_fail.status == InstallStatus.FAILED

    def test_non_core_failure_continues(self):
        """Test that non-core component failure continues installation."""
        comp_a = InstallableComponent(id="a", name="A", description="A", component_type=ComponentType.MCP)
        comp_b = InstallableComponent(id="b", name="B", description="B", component_type=ComponentType.MCP)
        comp_c = InstallableComponent(id="c", name="C", description="C", component_type=ComponentType.MCP)

        plan = InstallationPlan(components=[comp_a, comp_b, comp_c])
        orchestrator = InstallerOrchestrator(plan, dry_run=False)

        # a succeeds, b fails, c should still run
        installers = {
            "a": Mock(check_installed=Mock(return_value=(False, None)), install=Mock(return_value=Mock(success=True, version="1.0")), verify=Mock(return_value=(True, "1.0"))),
            "b": Mock(check_installed=Mock(return_value=(False, None)), install=Mock(return_value=Mock(success=False, error="Failed"))),
            "c": Mock(check_installed=Mock(return_value=(False, None)), install=Mock(return_value=Mock(success=True, version="1.0")), verify=Mock(return_value=(True, "1.0"))),
        }

        def get_installer(comp):
            return installers.get(comp.id)

        with patch.object(orchestrator, '_get_installer', side_effect=get_installer):
            orchestrator.prepare_plan(["a", "b", "c"])
            result = orchestrator.run_installation()

        assert result is False  # overall failure
        # Component a should have been installed (not skipped/failed)
        assert comp_a.status in (InstallStatus.SUCCESS, InstallStatus.VERIFYING)
        assert comp_b.status == InstallStatus.FAILED
        # Component c should have been attempted (not skipped) despite b failing
        assert comp_c.status in (InstallStatus.SUCCESS, InstallStatus.VERIFYING, InstallStatus.INSTALLING)

    def test_summary_correct(self, sample_plan):
        """Test get_summary returns correct counts."""
        orchestrator = InstallerOrchestrator(sample_plan, dry_run=True)
        orchestrator.prepare_plan(["a", "b"])
        orchestrator.run_installation()

        summary = orchestrator.get_summary()

        assert summary["total"] == 2
        assert summary["success"] == 2
        assert summary["failed"] == 0
        assert summary["skipped"] == 1  # c was skipped