"""Registry-parity contract between the installer's component palette and the
canonical capability registry (``CORE/capabilities/capabilities.json``).

The registry is the single source of truth for the providers (MCP servers and
tools) the toolchain can use, and it must never be duplicated as hard-coded
strings. This suite keeps the installer and the registry in agreement:

* every registry provider is either installable through the installer or listed
  in :data:`REGISTRY_ONLY` with a recorded reason;
* every external server/tool the installer can install (the component ids that
  are not SE product surfaces or toolchains) is either a registry provider or
  listed in :data:`INSTALLER_EXTRA` with a recorded reason.

Adding or removing a provider on either side without updating this contract
(and its allowlists) fails the installer suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from se_installer.components import get_all_components

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "CORE" / "capabilities" / "capabilities.json"

# Registry providers that intentionally have no installer step. Reason still
# must be recorded here so the divergence is deliberate, not accidental.
REGISTRY_ONLY: dict[str, str] = {
    "perplexity": (
        "Remote MCP behind api.perplexity.ai; needs an API key and is "
        "registered (never installed) via `se install --with perplexity`."
    ),
    "deepseek-vision": (
        "Hosted vision tool on api.deepseek.com; availability: unknown; "
        "requires a provider key; no local install step."
    ),
}

# Installer server/tool components that intentionally sit outside the registry.
INSTALLER_EXTRA: dict[str, str] = {
    "engram": (
        "Persistent cross-session memory backend owned by the orchestrator "
        "memory contract; not exposed as a toolchain capability provider."
    ),
    "codegraph": (
        "Optional code-intelligence indexer (Rust); not exposed as a toolchain "
        "capability; SE degrades to syntactic analysis without it."
    ),
}

# SE product surfaces and toolchain components never need a registry entry:
# they are backends/installers, not external capability providers.
PRODUCT_AND_TOOLCHAIN_IDS = {
    "se_core",
    "se_console",
    "node",
    "rust",
    "opencode",
    "codex",
    "claude_code",
}


def _registry_providers() -> set[str]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {provider["id"] for provider in data["providers"]}


def _component_ids() -> set[str]:
    return {component.id for component in get_all_components()}


def _drift_message(what: str, drift: list[str], allowlist: dict[str, str]) -> str:
    lines = [f"installer/registry drift in '{what}':"]
    for item in drift:
        lines.append(f"  - {item}: {allowlist.get(item, '<no recorded reason>')}")
    return "\n".join(lines)


def test_every_registry_provider_is_installable_or_explicitly_registry_only():
    providers = _registry_providers()
    installed = _component_ids()
    missing = sorted(providers - installed)
    assert missing == sorted(REGISTRY_ONLY), _drift_message(
        "registry providers without installer coverage", missing, REGISTRY_ONLY
    )


def test_every_installer_server_is_a_provider_or_explicitly_extra():
    providers = _registry_providers()
    installed = _component_ids()
    servers = sorted(installed - PRODUCT_AND_TOOLCHAIN_IDS)
    extra = sorted(set(servers) - providers)
    assert extra == sorted(INSTALLER_EXTRA), _drift_message(
        "installer servers without a registry entry", extra, INSTALLER_EXTRA
    )


def test_allowlist_entries_are_still_true():
    """The documented exceptions must match reality, so the allowlists cannot
    silently grow stale."""
    providers = _registry_providers()
    installed = _component_ids()

    for provider_id in REGISTRY_ONLY:
        assert provider_id in providers, (
            f"{provider_id} is no longer a registry provider; drop it from REGISTRY_ONLY"
        )
        assert provider_id not in installed, (
            f"{provider_id} is now an installer component; drop it from REGISTRY_ONLY"
        )

    for component_id in INSTALLER_EXTRA:
        assert component_id in installed, (
            f"{component_id} is no longer a component; drop it from INSTALLER_EXTRA"
        )
        assert component_id not in providers, (
            f"{component_id} is now a registry provider; add an installer entry "
            "or move it out of INSTALLER_EXTRA"
        )


def test_sequential_thinking_gap_is_closed():
    """The canonical registry declares the standard sequential-thinking MCP;
    the installer must install it, not silently ignore it."""
    installed = _component_ids()
    assert "sequential-thinking" in installed