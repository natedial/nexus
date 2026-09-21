"""Evaluation infrastructure for analysis agents."""

from research_analysis_layer.evals.alerting import (
    Alert,
    AlertHandler,
    create_alert_handler,
)

from research_analysis_layer.evals.comparison import (
    compare_outputs,
    compute_confidence,
    compute_field_similarity,
    DEFAULT_FIELD_WEIGHTS,
    exact_match,
    list_match_rate,
    rouge_l,
)

from research_analysis_layer.evals.db import (
    EvalDatabase,
    compute_golden_set_hash,
)

from research_analysis_layer.evals.judge import (
    DEFAULT_ARGUMENT_JUDGE_WEIGHTS,
    ArgumentJudge,
    ArgumentJudgeScore,
    JudgeScore,
    LLMJudge,
)

from research_analysis_layer.evals.rubric_metrics import (
    PromotionGateDecision,
    RubricRates,
    aggregate_rubric_metrics,
    evaluate_promotion_gate,
)

from research_analysis_layer.evals.runner import (
    AgentEvalRunner,
    EvalResult,
    EvalSummary,
    RegressionReport,
    load_golden_annotations,
    load_golden_document,
    validate_schema,
)

from research_analysis_layer.evals.rubric_regression import (
    RubricRegressionReport,
    build_rubric_regression_report,
)

from research_analysis_layer.evals.training_capture import (
    CAPTURE_THRESHOLD,
    TrainingCapture,
    TrainingCaptureManager,
)

__all__ = [
    "Alert",
    "AlertHandler",
    "create_alert_handler",
    "compare_outputs",
    "compute_confidence",
    "compute_field_similarity",
    "DEFAULT_FIELD_WEIGHTS",
    "exact_match",
    "list_match_rate",
    "rouge_l",
    "EvalDatabase",
    "compute_golden_set_hash",
    "JudgeScore",
    "LLMJudge",
    "ArgumentJudge",
    "ArgumentJudgeScore",
    "DEFAULT_ARGUMENT_JUDGE_WEIGHTS",
    "PromotionGateDecision",
    "RubricRates",
    "aggregate_rubric_metrics",
    "evaluate_promotion_gate",
    "AgentEvalRunner",
    "EvalResult",
    "EvalSummary",
    "RegressionReport",
    "RubricRegressionReport",
    "build_rubric_regression_report",
    "load_golden_annotations",
    "load_golden_document",
    "validate_schema",
    "CAPTURE_THRESHOLD",
    "TrainingCapture",
    "TrainingCaptureManager",
]
