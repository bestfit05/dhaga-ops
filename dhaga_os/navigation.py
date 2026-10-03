"""Streamlit-safe workspace navigation state helpers."""

from __future__ import annotations

from typing import MutableMapping


WORKSPACES = ("Overview", "Product listings", "Customer messages", "Saved approvals", "Future scopes")
WORKSPACE_KEY = "workspace_v2"
PENDING_WORKSPACE_KEY = "pending_workspace"
LEGACY_WORKSPACE_KEY = "workspace"


def request_workspace(state: MutableMapping[str, object], workspace: str) -> None:
    """Record a button navigation request without mutating a rendered widget key."""
    if workspace not in WORKSPACES:
        raise ValueError(f"Unknown workspace: {workspace}")
    state[PENDING_WORKSPACE_KEY] = workspace


def prepare_workspace_widget(state: MutableMapping[str, object]) -> str:
    """Apply any pending selection before creating the radio widget for this run."""
    if WORKSPACE_KEY not in state:
        legacy = state.get(LEGACY_WORKSPACE_KEY, "Overview")
        state[WORKSPACE_KEY] = legacy if legacy in WORKSPACES else "Overview"
    pending = state.pop(PENDING_WORKSPACE_KEY, None)
    if pending in WORKSPACES:
        state[WORKSPACE_KEY] = pending
    # The prior app version used this as a widget key. Remove it during migration.
    state.pop(LEGACY_WORKSPACE_KEY, None)
    return str(state[WORKSPACE_KEY])
