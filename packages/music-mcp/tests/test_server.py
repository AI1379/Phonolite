"""MCP catalog contract tests."""

from __future__ import annotations

import asyncio
import warnings


def test_mcp_catalog_exposes_only_workbench_domain_tools() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from music_mcp.server import mcp

    async def names() -> set[str]:
        return {tool.name for tool in await mcp.list_tools()}

    assert asyncio.run(names()) == {
        "project_status",
        "get_score",
        "inspect_score",
        "compare_versions",
        "apply_transformation",
        "render_score",
        "export_score",
        "memory_query",
        "memory_record_episode",
        "learning_record_outcome",
    }
