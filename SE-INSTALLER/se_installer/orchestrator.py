"""Main installer orchestrator."""

from __future__ import annotations

from __future__ import annotations

from typing import Optional, Callable
from pathlib import Path
import time
import sys

from .models import InstallationPlan, InstallableComponent, InstallStatus, OSType, ComponentType
from .components import get_all_components
from .state import InstallationState
from .installers.base import BaseInstaller
from .installers.mcp import get_mcp_installer
from .installers.runtime import get_runtime_installer
from . import shortcuts


class InstallerOrchestrator:
    """Main orchestrator for the installation process."""
    
    def __init__(self, plan: Optional = None, dry_run: bool = False, progress_callback: Optional[Callable] = None):
        self.plan = plan or InstallationPlan()
        self.dry_run = dry_run
        self.progress_callback = progress_callback
        self.state = InstallationState()
        # Outcome of the install-time desktop shortcut, when one was asked for.
        self.shortcut: Optional[dict] = None
        
        # Initialize components if not already
        if not self.plan.components:
            self.plan.components = get_all_components()
        
        # Detect OS if not set
        if self.plan.os_type == OSType.WINDOWS:  # default
            self.plan.os_type = self._detect_os()
    
    @staticmethod
    def _detect_os() -> OSType:
        import sys
        if sys.platform.startswith("win"):
            return OSType.WINDOWS
        elif sys.platform == "darwin":
            return OSType.MACOS
        else:
            return OSType.LINUX
    
    def _emit(self, event: str, data: dict = None) -> None:
        """Emit progress event."""
        if self.progress_callback:
            self.progress_callback(event, data or {})
    
    def prepare_plan(self, selected_ids: list[str], target_runtimes: list[str] = None) -> None:
        """Prepare installation plan with selected components."""
        # Mark all as SKIPPED initially
        for comp in self.plan.components:
            comp.status = InstallStatus.SKIPPED
        
        # Mark selected and their dependencies
        self._mark_selected_with_deps(selected_ids)
        
        # Set target runtimes
        if target_runtimes:
            self.plan.target_runtimes = target_runtimes
        
        # Save initial plan
        self.plan.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.state.save_plan(self.plan)
    
    def _mark_selected_with_deps(self, selected_ids: list[str]) -> None:
        """Mark selected components and their dependencies as PENDING."""
        id_to_comp = {c.id: c for c in self.plan.components}
        
        def mark(id_: str):
            comp = self.plan.get_by_id(id_)
            if comp and comp.status == InstallStatus.SKIPPED:
                comp.status = InstallStatus.PENDING
                # Mark dependencies
                for dep_id in comp.requires:
                    mark(dep_id)
        
        for sid in selected_ids:
            mark(sid)
    
    def run_installation(self) -> bool:
        """Execute the full installation plan."""
        if self.dry_run:
            self._emit("started", {"total": len(self.plan.get_selected())})
            # Dry run: just validate and plan
            ordered = self.plan.topological_sort()
            for i, comp in enumerate(ordered):
                if comp.status == InstallStatus.SKIPPED:
                    continue
                self._emit("component_start", {"index": i, "total": len(ordered), "component": comp.id})
                comp.status = InstallStatus.SUCCESS
                comp.installed_version = "dry-run"
                self._emit("status_change", {"component": comp.id, "status": InstallStatus.SUCCESS.value, "version": "dry-run"})
            self.install_console_shortcut(succeeded=True)
            self._emit("completed", {"success": True})
            return True
        
        self._emit("started", {"total": len(self.plan.get_selected())})
        
        # Get installation order (topological sort)
        ordered = self.plan.topological_sort()
        
        success = True
        for i, comp in enumerate(ordered):
            if comp.status == InstallStatus.SKIPPED:
                continue
            
            self._emit("component_start", {"index": i, "total": len(ordered), "component": comp.id})
            
            try:
                success &= self._install_component(comp)
            except Exception as e:
                comp.status = InstallStatus.FAILED
                comp.error_message = str(e)
                self._emit("component_failed", {"component": comp.id, "error": str(e)})
                success = False
                if not self._should_continue_on_failure(comp):
                    break
            
            self.state.save_plan(self.plan)
        
        self.plan.completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.state.save_plan(self.plan)
        
        self.install_console_shortcut(succeeded=success)
        self._emit("completed", {"success": success})
        return success
    
    def _install_component(self, comp) -> bool:
        """Install a single component."""
        comp.status = InstallStatus.INSTALLING
        self._emit("status_change", {"component": comp.id, "status": InstallStatus.INSTALLING.value})
        self.state.save_plan(self.plan)
        
        # Handle vendored components (se_core, se_console) - they're part of the repo
        if comp.component_type in (ComponentType.SE_CORE, ComponentType.SE_CONSOLE):
            comp.status = InstallStatus.SUCCESS
            comp.installed_version = "vendored"
            comp.error_message = None
            self._emit("status_change", {"component": comp.id, "status": InstallStatus.SUCCESS.value, "version": "vendored"})
            return True
        
        # Check if already installed
        try:
            installer = self._get_installer(comp)
        except ValueError as exc:
            # A selectable component with no registered installer must fail
            # with a readable message, never an unhandled traceback.
            comp.status = InstallStatus.FAILED
            comp.error_message = f"No installer registered for component '{comp.id}': {exc}"
            self._emit("component_failed", {"component": comp.id, "error": comp.error_message})
            return False
        if installer:
            installed, version = installer.check_installed()
            if installed and not self.plan.force_reinstall:
                comp.status = InstallStatus.SUCCESS
                comp.installed_version = version
                self._emit("status_change", {"component": comp.id, "status": InstallStatus.SUCCESS.value, "version": version})
                return True
        
        # Install
        result = None
        if installer:
            comp.status = InstallStatus.INSTALLING
            self._emit("status_change", {"component": comp.id, "status": InstallStatus.INSTALLING.value})
            result = installer.install()
        
        if result and result.success:
            comp.status = InstallStatus.SUCCESS
            comp.installed_version = result.version
            comp.error_message = None
            self._emit("status_change", {"component": comp.id, "status": InstallStatus.SUCCESS.value, "version": result.version})
            
            # Verify
            if not self.plan.skip_verification and installer:
                comp.status = InstallStatus.VERIFYING
                self._emit("status_change", {"component": comp.id, "status": InstallStatus.VERIFYING.value})
                verified, version = installer.verify()
                if verified:
                    comp.installed_version = version
                else:
                    comp.status = InstallStatus.FAILED
                    comp.error_message = "Verification failed"
                    return False
            
            return True
        else:
            comp.status = InstallStatus.FAILED
            comp.error_message = result.error if result else "No installer available"
            self._emit("status_change", {"component": comp.id, "status": InstallStatus.FAILED.value, "error": comp.error_message})
            return False
    
    def install_console_shortcut(self, succeeded: bool = True) -> Optional[dict]:
        """Offer the SE Console desktop shortcut (DESIGN-5C phase 4).

        Returns ``None`` when the plan did not ask for a shortcut, otherwise the
        outcome, which is also recorded on ``self.shortcut`` and emitted as one
        ``shortcut`` event.

        Three things are deliberate: a shortcut is only useful if the console is
        actually part of this installation; a dry run reports the shortcut it
        would create and creates none; and a shortcut is only created after a
        successful install, so it never points at something that failed to land.
        """
        if not self.plan.create_shortcuts:
            return None

        console = self.plan.get_by_id("se_console")
        if console is None or console.status == InstallStatus.SKIPPED:
            data = {
                "created": False,
                "skipped": True,
                "reason": "SE Console is not part of this installation",
            }
        elif self.dry_run:
            planned = shortcuts.plan_shortcut(os_type=self.plan.os_type)
            data = {**planned.as_dict(), "created": False, "dry_run": True}
            if not planned.target.exists():
                data["error"] = f"the console entry point does not exist: {planned.target}"
        elif not succeeded:
            data = {
                "created": False,
                "skipped": True,
                "reason": "the installation did not succeed",
            }
        else:
            try:
                result = shortcuts.install_console_shortcut(os_type=self.plan.os_type)
            except shortcuts.ShortcutError as exc:
                data = {"created": False, "error": str(exc)}
            else:
                data = result.as_dict()

        self.shortcut = data
        self._emit("shortcut", data)
        return data

    def _get_installer(self, comp) -> Optional[BaseInstaller]:
        """Get appropriate installer for component."""
        if comp.component_type == ComponentType.MCP:
            return get_mcp_installer(comp.id, comp, dry_run=self.dry_run)
        elif comp.component_type == ComponentType.RUNTIME:
            return get_runtime_installer(comp.id, comp, dry_run=self.dry_run)
        elif comp.component_type in (ComponentType.SE_CORE, ComponentType.SE_CONSOLE):
            # SE Core and Console are handled specially (vendored)
            return None
        return None
    
    def _should_continue_on_failure(self, comp) -> bool:
        """Decide whether to continue after a failure."""
        # Continue if it's not a core component
        return comp.component_type not in (ComponentType.SE_CORE,)
    
    def get_summary(self) -> dict:
        """Get installation summary."""
        selected = self.plan.get_selected()
        return {
            "total": len(selected),
            "success": sum(1 for c in selected if c.status == InstallStatus.SUCCESS),
            "failed": sum(1 for c in selected if c.status == InstallStatus.FAILED),
            "skipped": sum(1 for c in self.plan.components if c.status == InstallStatus.SKIPPED),
            # None unless the plan asked for the SE Console shortcut, so an
            # install that never mentioned shortcuts keeps its old shape.
            "shortcut": self.shortcut,
            "components": [
                {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status.value,
                    "version": c.installed_version,
                    "error": c.error_message,
                }
                for c in selected
            ],
        }