"""Hermetic tests for SE Installer components catalog."""

from __future__ import annotations

import pytest

from se_installer.components import get_all_components, get_recommended_components, get_components_by_category
from se_installer.models import ComponentType, OSType


class TestComponentsCatalog:
    """Tests for the component catalog."""

    def test_all_components_loaded(self):
        components = get_all_components()
        assert len(components) >= 13  # at least the 13 defined

    def test_required_components_present(self):
        components = get_all_components()
        ids = {c.id for c in components}

        # Core
        assert "se_core" in ids
        assert "se_console" in ids
        # MCPs
        assert "context7" in ids
        assert "filesystem" in ids
        assert "playwright" in ids
        assert "firecrawl" in ids
        assert "codegraph" in ids
        # Runtime deps
        assert "node" in ids
        assert "rust" in ids
        # Runtimes
        assert "opencode" in ids
        assert "codex" in ids
        assert "claude_code" in ids

    def test_component_types_correct(self):
        components = get_all_components()
        type_map = {c.id: c.component_type for c in components}

        assert type_map["se_core"] == ComponentType.SE_CORE
        assert type_map["se_console"] == ComponentType.SE_CONSOLE
        assert type_map["context7"] == ComponentType.MCP
        assert type_map["opencode"] == ComponentType.RUNTIME

    def test_vendored_components_marked(self):
        components = get_all_components()
        vendored = [c for c in components if c.install_method == "vendored"]
        vendored_ids = {c.id for c in vendored}

        # Only se_console is vendored; se_core is installed via pip
        assert "se_console" in vendored_ids
        assert "se_core" not in vendored_ids

        # se_core should be pip
        core = next(c for c in components if c.id == "se_core")
        assert core.install_method == "pip"

    def test_node_conditional_requirement(self):
        """Test that node is required only for npx-based MCPs."""
        components = get_all_components()
        comp_map = {c.id: c for c in components}

        # These require node
        for mcp_id in ["context7", "filesystem", "playwright", "firecrawl"]:
            assert "node" in comp_map[mcp_id].requires, f"{mcp_id} should require node"

        # These do NOT require node
        for mcp_id in ["codegraph", "se_core", "se_console"]:
            assert "node" not in comp_map[mcp_id].requires, f"{mcp_id} should not require node"

    def test_recommended_components(self):
        recommended = get_recommended_components()
        rec_ids = {c.id for c in recommended}

        # Core always recommended
        assert "se_core" in rec_ids
        assert "se_console" in rec_ids
        assert "context7" in rec_ids
        assert "filesystem" in rec_ids
        assert "node" in rec_ids
        assert "opencode" in rec_ids

        # Optional not recommended
        assert "playwright" not in rec_ids
        assert "firecrawl" not in rec_ids
        assert "codegraph" not in rec_ids
        assert "rust" not in rec_ids
        assert "codex" not in rec_ids
        assert "claude_code" not in rec_ids

    def test_all_supported_on_windows(self):
        components = get_all_components()
        for comp in components:
            assert comp.is_supported_on(OSType.WINDOWS), f"{comp.id} should support Windows"

    def test_categories_present(self):
        by_cat = get_components_by_category()
        expected_cats = {"Core", "Documentation", "File Operations", "Browser Automation", "Web Scraping", "Code Intelligence", "Runtime"}
        assert expected_cats.issubset(set(by_cat.keys()))

    def test_no_duplicate_ids(self):
        components = get_all_components()
        ids = [c.id for c in components]
        assert len(ids) == len(set(ids)), "Duplicate component IDs found"

    def test_component_has_required_fields(self):
        components = get_all_components()
        for comp in components:
            assert comp.id, f"Missing id for {comp}"
            assert comp.name, f"Missing name for {comp.id}"
            assert comp.description, f"Missing description for {comp.id}"
            assert comp.component_type, f"Missing type for {comp.id}"
            assert comp.install_method, f"Missing install_method for {comp.id}"
            assert comp.verification_command is not None, f"Missing verification_command for {comp.id}"