#!/usr/bin/env python3
"""Tests for three bug fixes:
  A. graph_ctx_text → codegen prompt delivery
  B. PlanItem action field
  C. spec_agent LLM optional
  D. plan_agent LLM optional
"""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup — must happen before importing orchestrator modules
# ---------------------------------------------------------------------------
_ORCH_DIR = Path(__file__).parent.parent / "orchestrator"
_AGENTS_DIR = _ORCH_DIR / "agents"
for _p in (_ORCH_DIR, _AGENTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Mock heavy dependencies before importing modules
for _m in ["llm_utils", "verify", "context_selector"]:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

import codegen  # noqa: E402
import plan_agent  # noqa: E402
import spec_agent  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rtl_inputs(tmp_path: Path):
    """Create minimal temp input files for build_prompt / generate_rtl_with_retry."""
    rtl_dir = tmp_path / "rtl"
    rtl_dir.mkdir()
    (rtl_dir / "test.v").write_text("module test(); endmodule")
    uarch_origin = tmp_path / "uarch_origin.txt"
    uarch_origin.write_text("origin uarch")
    uarch_new = tmp_path / "uarch_new.txt"
    uarch_new.write_text("new uarch")
    algo_origin = tmp_path / "algo_origin.py"
    algo_origin.write_text("# origin algo")
    algo_new = tmp_path / "algo_new.py"
    algo_new.write_text("# new algo")
    return rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new


# ---------------------------------------------------------------------------
# A. graph_ctx_text → codegen build_prompt / generate_rtl_with_retry
# ---------------------------------------------------------------------------

class TestGraphCtxTextCodegen:

    def test_build_prompt_includes_signal_causal_context(self, tmp_path):
        """graph_ctx_text 넘기면 프롬프트에 'Signal Causal Context' 와 해당 텍스트 포함 확인."""
        rtl_dir, ua_o, ua_n, al_o, al_n = _make_rtl_inputs(tmp_path)

        prompt = codegen.build_prompt(
            rtl_dir, ua_o, ua_n, al_o, al_n,
            graph_ctx_text="clk <- pll_clk",
        )

        assert "Signal Causal Context" in prompt
        assert "clk <- pll_clk" in prompt

    def test_build_prompt_empty_ctx_has_no_signal_section(self, tmp_path):
        """graph_ctx_text 비어있으면 'Signal Causal Context' 섹션 없음 확인."""
        rtl_dir, ua_o, ua_n, al_o, al_n = _make_rtl_inputs(tmp_path)

        prompt = codegen.build_prompt(
            rtl_dir, ua_o, ua_n, al_o, al_n,
            graph_ctx_text="",
        )

        assert "Signal Causal Context" not in prompt

    def test_generate_rtl_with_retry_passes_graph_ctx_text(self, tmp_path):
        """generate_rtl_with_retry가 graph_ctx_text를 build_prompt_chunked에 전달하는지 mock으로 확인."""
        rtl_dir, ua_o, ua_n, al_o, al_n = _make_rtl_inputs(tmp_path)
        output = tmp_path / "output.v"

        # Configure mocks
        sys.modules["verify"].run_checks.return_value = {"status": "pass", "results": {}}

        captured: dict = {}

        def mock_bpc(*args, **kwargs):
            captured["graph_ctx_text"] = kwargs.get("graph_ctx_text", "__NOT_FOUND__")
            return ("module out(); endmodule", False)

        with patch.object(codegen, "build_prompt_chunked", side_effect=mock_bpc):
            with patch.object(codegen, "call_llm", return_value="module out(); endmodule"):
                codegen.generate_rtl_with_retry(
                    cfg={"model": "test"},
                    origin_rtl_dir=rtl_dir,
                    uarch_origin=ua_o,
                    uarch_new=ua_n,
                    algo_origin=al_o,
                    algo_new=al_n,
                    output=output,
                    graph_ctx_text="clk <- pll_clk",
                )

        assert captured.get("graph_ctx_text") == "clk <- pll_clk", (
            f"Expected graph_ctx_text='clk <- pll_clk', got {captured.get('graph_ctx_text')!r}"
        )


# ---------------------------------------------------------------------------
# B. PlanItem action 필드
# ---------------------------------------------------------------------------

class TestPlanItemActionField:

    def test_plan_item_dataclass_has_action_field(self):
        """PlanItem dataclass에 'action' 필드 존재 확인."""
        field_names = {f.name for f in fields(plan_agent.PlanItem)}
        assert "action" in field_names, f"PlanItem fields: {field_names}"

    def test_build_plan_action_not_empty_for_each_item(self):
        """build_plan() 반환 PlanItem들의 action 필드가 모두 빈 문자열이 아닌지 확인."""
        rtl_modules = [
            {"module": "my_module", "ports": [{"name": "clk"}, {"name": "rst"}]},
        ]
        spec_findings = ["Add ROI gate signal"]

        items = plan_agent.build_plan(rtl_modules, spec_findings, model_cfg=None)

        assert len(items) >= 1
        for item in items:
            assert item.action != "", (
                f"action should not be empty for PlanItem title='{item.title}'"
            )


# ---------------------------------------------------------------------------
# C. spec_agent LLM optional
# ---------------------------------------------------------------------------

class TestSpecAgentLLMOptional:

    def test_analyze_without_model_cfg_uses_slicing(self):
        """model_cfg=None이면 LLM 없이 content[:200] 슬라이싱 동작 확인."""
        chunks = [{"ref": "uarch.txt:1", "content": "A" * 300}]
        pseudo_diff = "B" * 300

        findings = spec_agent.analyze(chunks, pseudo_diff, model_cfg=None)

        assert len(findings) == 2
        assert findings[0].summary == "A" * 200
        assert findings[1].summary == "B" * 200

    def test_analyze_with_model_cfg_calls_llm(self):
        """model_cfg 제공 시 call_llm이 호출되고 그 반환값이 summary에 사용되는지 확인."""
        mock_llm_module = MagicMock()
        mock_llm_module.call_llm.return_value = "LLM summary"
        sys.modules["llm_utils"] = mock_llm_module

        chunks = [{"ref": "uarch.txt:1", "content": "some content"}]
        pseudo_diff = "some diff"

        findings = spec_agent.analyze(chunks, pseudo_diff, model_cfg={"model": "test"})

        assert mock_llm_module.call_llm.called, "call_llm should have been called"
        assert len(findings) == 2
        assert findings[0].summary == "LLM summary"
        assert findings[1].summary == "LLM summary"


# ---------------------------------------------------------------------------
# D. plan_agent LLM optional
# ---------------------------------------------------------------------------

class TestPlanAgentLLMOptional:

    def test_build_plan_without_model_cfg_action_equals_title(self):
        """model_cfg=None이면 LLM 없이 action = title 동작 확인."""
        rtl_modules = [{"module": "top", "ports": [{"name": "clk"}]}]

        items = plan_agent.build_plan(rtl_modules, [], model_cfg=None)

        assert len(items) == 1
        assert items[0].action == items[0].title

    def test_build_plan_with_model_cfg_calls_llm(self):
        """model_cfg 제공 시 call_llm이 호출되고 그 반환값이 action에 사용되는지 확인."""
        mock_llm_module = MagicMock()
        mock_llm_module.call_llm.return_value = "LLM action"
        sys.modules["llm_utils"] = mock_llm_module

        rtl_modules = [{"module": "top", "ports": [{"name": "clk"}]}]
        spec_findings = ["spec delta"]

        items = plan_agent.build_plan(
            rtl_modules, spec_findings, model_cfg={"model": "test"}
        )

        assert mock_llm_module.call_llm.called, "call_llm should have been called"
        assert len(items) >= 1
        for item in items:
            assert item.action == "LLM action", (
                f"Expected action='LLM action', got {item.action!r} for '{item.title}'"
            )
