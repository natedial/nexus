"""export-dispatch-batch must not require research_pipeline_ops at import time."""

from __future__ import annotations

import importlib
import sys


def test_main_imports_without_research_pipeline_ops():
    """Proey MA feed: export CLI must start when PipelineOpsClient is absent."""
    saved = sys.modules.pop("research_pipeline_ops", None)
    # Make "import research_pipeline_ops" fail for this process.
    sys.modules["research_pipeline_ops"] = None  # type: ignore[assignment]

    try:
        if "research_analysis_layer.main" in sys.modules:
            main = importlib.reload(sys.modules["research_analysis_layer.main"])
        else:
            main = importlib.import_module("research_analysis_layer.main")

        assert "PipelineOpsClient" not in vars(main)
        help_text = main.build_parser().format_help()
        assert "export-dispatch-batch" in help_text
        assert callable(main.command_export_dispatch_batch)
        # Docstring advertises store-only dependency.
        assert "research_pipeline_ops" in (main.command_export_dispatch_batch.__doc__ or "")
    finally:
        if saved is not None:
            sys.modules["research_pipeline_ops"] = saved
        else:
            sys.modules.pop("research_pipeline_ops", None)
        if "research_analysis_layer.main" in sys.modules:
            importlib.reload(sys.modules["research_analysis_layer.main"])


def test_build_app_requires_pipeline_ops_lazily():
    """Only build_app pulls PipelineOpsClient; missing package raises ImportError."""
    from unittest.mock import MagicMock, patch

    import research_analysis_layer.main as m

    saved = sys.modules.get("research_pipeline_ops")
    sys.modules["research_pipeline_ops"] = None  # type: ignore[assignment]
    settings = MagicMock()
    settings.analyst_tools_enabled = False
    settings.analyst_round_mode = "off"
    settings.eval_capture_enabled = False
    settings.pipeline_ops_spool_path.return_value = "/tmp/ops.db"
    settings.analysis_version = "argmap-v1"
    settings.referent_granularity = "coarse"
    settings.analyst_debate_mode = "off"
    settings.analyst_debate_judge_model = None
    settings.analyst_max_debate_arguments = 8
    settings.state_db_path = "/tmp/state.db"

    try:
        with (
            patch.object(m, "StateDbReader", return_value=MagicMock()),
            patch.object(m, "open_parsed_db_client", return_value=MagicMock()),
            patch.object(m, "open_calendar_db_client", return_value=MagicMock()),
            patch.object(
                m, "open_analysis_store_from_settings", return_value=MagicMock()
            ),
            patch.object(m, "build_agent_llm_client", return_value=None),
            patch.object(m, "Selector", return_value=MagicMock()),
            patch.object(m, "Hydrator", return_value=MagicMock()),
            patch.object(m, "AnalyzeDocumentPipeline", return_value=MagicMock()),
            patch.object(m, "get_registry") as reg,
        ):
            reg.return_value.has_rounds_config.return_value = False
            try:
                m.build_app(settings)
                raised = False
            except ImportError as exc:
                raised = True
                assert "export-dispatch-batch" in str(exc)
            assert raised, "build_app must fail closed without research_pipeline_ops"
    finally:
        if saved is not None:
            sys.modules["research_pipeline_ops"] = saved
        else:
            sys.modules.pop("research_pipeline_ops", None)
