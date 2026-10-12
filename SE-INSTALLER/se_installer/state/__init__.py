"""Installation state persistence."""

from __future__ import annotations

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional
from dataclasses import asdict

from ..models import InstallationPlan, InstallableComponent, InstallStatus, OSType


class InstallationState:
    """Manages installation state persistence."""
    
    def __init__(self, state_dir: Optional[Path] = None):
        if state_dir is None:
            state_dir = Path.home() / ".se-installer" / "state"
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "installation_state.json"
        self.history_file = self.state_dir / "installation_history.jsonl"
    
    def save_plan(self, plan) -> None:
        """Save installation plan to disk."""
        data = {
            "os_type": plan.os_type.value,
            "target_dir": str(plan.target_dir),
            "target_runtimes": plan.target_runtimes,
            "dry_run": plan.dry_run,
            "force_reinstall": plan.force_reinstall,
            "skip_verification": plan.skip_verification,
            "created_at": plan.created_at,
            "completed_at": plan.completed_at,
            "components": [
                {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status.value,
                    "installed_version": c.installed_version,
                    "error_message": c.error_message,
                }
                for c in plan.components
            ],
        }
        self.state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    
    def load_plan(self, plan) -> bool:
        """Load installation plan from disk."""
        if not self.state_file.exists():
            return False
        
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            
            plan.os_type = OSType(data["os_type"])
            plan.target_dir = Path(data["target_dir"])
            plan.target_runtimes = data.get("target_runtimes", ["opencode"])
            plan.dry_run = data.get("dry_run", False)
            plan.force_reinstall = data.get("force_reinstall", False)
            plan.skip_verification = data.get("skip_verification", False)
            plan.created_at = data.get("created_at", "")
            plan.completed_at = data.get("completed_at")
            
            # Restore component statuses
            id_to_comp = {c.id: c for c in plan.components}
            for comp_data in data.get("components", []):
                comp = id_to_comp.get(comp_data["id"])
                if comp:
                    comp.status = type(plan.components[0].status)(comp_data["status"])
                    comp.installed_version = comp_data.get("installed_version")
                    comp.error_message = comp_data.get("error_message")
            
            return True
        except Exception:
            return False
    
    def log_event(self, event: dict) -> None:
        """Log an event to history."""
        event["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    
    def get_history(self, limit: int = 100) -> list:
        """Get installation history."""
        if not self.history_file.exists():
            return []
        
        events = []
        with open(self.history_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return events[-limit:]
    
    def clear(self) -> None:
        """Clear all state."""
        self.state_file.unlink(missing_ok=True)
        self.history_file.unlink(missing_ok=True)