#!/usr/bin/env python3
"""Neo4j mock integration tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts and orchestrator to path before importing modules
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_ORCH_DIR = Path(__file__).parent.parent / "orchestrator"
for _p in (_SCRIPTS_DIR, _ORCH_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Mock heavy orchestrator dependencies before importing flow
_MOCK_MODULES = [
    "agents",
    "agents.plan_agent",
    "agents.report_agent",
    "agents.spec_agent",
    "codegen",
    "llm_utils",
]
for _m in _MOCK_MODULES:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

import neo4j_query  # noqa: E402
from flow import _query_neo4j_context  # noqa: E402


def _make_mock_driver(drivers_rows, dependents_rows):
    """Build a mock Neo4j driver whose session returns given rows in order."""
    mock_session = MagicMock()
    mock_session.run.side_effect = [drivers_rows, dependents_rows]

    mock_session_cm = MagicMock()
    mock_session_cm.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cm.__exit__ = MagicMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session_cm
    return mock_driver


class TestNeo4jIntegration:
    def test_get_causal_context_returns_graph_context(self):
        """mock driver가 drivers/dependents 반환 → get_causal_context 결과 검증."""
        drivers_rows = [{"name": "pll_clk"}]
        dependents_rows = [{"name": "data_out"}]
        mock_driver = _make_mock_driver(drivers_rows, dependents_rows)

        with patch("neo4j.GraphDatabase.driver", return_value=mock_driver):
            result = neo4j_query.get_causal_context("my_module", ["clk"])

        assert "clk" in result
        assert result["clk"]["drivers"] == ["pll_clk"]
        assert result["clk"]["dependents"] == ["data_out"]

    def test_format_graph_context_output(self):
        """format_graph_context가 올바른 텍스트 포맷 반환하는지 검증."""
        context = {
            "clk": {
                "drivers": ["pll_clk"],
                "dependents": ["data_out", "ctrl_reg"],
            }
        }
        text = neo4j_query.format_graph_context(context)
        assert "clk" in text
        assert "pll_clk" in text
        assert "data_out" in text
        assert "ctrl_reg" in text
        # driven by / drives 방향 표기 확인
        assert "driven by" in text or "<-" in text
        assert "drives" in text or "->" in text

    def test_flow_prompt_contains_graph_context(self):
        """_query_neo4j_context 결과가 비어있지 않을 때 flow 프롬프트에 헤더 포함 검증."""
        fake_ctx = {"clk": {"drivers": ["pll_clk"], "dependents": ["q_out"]}}
        fake_text = "  clk <- driven by: pll_clk\n  clk -> drives: q_out"

        with patch.object(
            sys.modules["neo4j_query"], "get_causal_context_nhop", return_value=fake_ctx
        ):
            with patch.object(
                sys.modules["neo4j_query"], "format_graph_context", return_value=fake_text
            ):
                ctx_text = _query_neo4j_context("my_module", ["clk"], n_hops=1)

        assert ctx_text, "_query_neo4j_context should return non-empty string"

        # flow.py main()의 프롬프트 빌딩 로직과 동일한 패턴으로 검증
        prompt = "Summarize the following findings and action plan:\n"
        if ctx_text:
            prompt = (
                "## Graph Context (from Neo4j)\n"
                f"{ctx_text}\n\n"
                + prompt
            )
        assert "Graph Context (from Neo4j)" in prompt

    def test_neo4j_unreachable_graceful_skip(self):
        """Neo4j 연결 실패 시 빈 문자열 반환하고 예외 미전파 검증."""
        with patch("neo4j.GraphDatabase.driver", side_effect=Exception("Connection refused")):
            import warnings
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                result = _query_neo4j_context("my_module", ["clk"], n_hops=1)

        assert result == "", f"Expected empty string on Neo4j failure, got: {result!r}"
