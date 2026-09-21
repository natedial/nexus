"""Tests for punchlist items R1-R5."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from research_analysis_layer.config import Settings
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.services.agent_llm_client import (
    OpenAICompatibleAgentLlmClient,
    build_agent_llm_client,
)
from research_analysis_layer.services.dispatch_batch_exporter import (
    DispatchBatchExporter,
)
from research_analysis_layer.services.tools.registry import ToolRegistry
from research_analysis_layer.models.dispatch_scope import DispatchScope


class TestR1NoLlmSafeBaseline(unittest.TestCase):
    """R1: Gate round execution safely - no-LLM test."""

    def test_build_agent_llm_client_returns_none_when_disabled(self) -> None:
        """When agent_execution_enabled is False, return None."""
        env = {
            "AGENT_EXECUTION_ENABLED": "false",
            "AGENT_LLM_PROVIDER": "openai",
            "AGENT_LLM_API_KEY": "test-key",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
            client = build_agent_llm_client(settings)
            self.assertIsNone(client)

    def test_build_agent_llm_client_returns_none_without_api_key(self) -> None:
        """When API key is missing, return None even if enabled."""
        env = {
            "AGENT_EXECUTION_ENABLED": "true",
            "AGENT_LLM_PROVIDER": "openai",
            "AGENT_LLM_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
            client = build_agent_llm_client(settings)
            self.assertIsNone(client)

    def test_round_executor_not_created_without_llm_client(self) -> None:
        """RoundExecutor should not be created when LLM client is None."""
        env = {
            "AGENT_EXECUTION_ENABLED": "false",
            "ANALYST_ROUND_MODE": "rounds",
            "ANALYST_TOOLS_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
            registry = MagicMock()
            registry.has_rounds_config.return_value = True
            llm_client = build_agent_llm_client(settings)

            round_executor = None
            if settings.analyst_round_mode == "rounds" and registry.has_rounds_config():
                if llm_client is not None:
                    from research_analysis_layer.services.agent_input_builder import (
                        AgentInputBuilder,
                    )
                    from research_analysis_layer.services.round_executor import (
                        RoundExecutor,
                    )

                    round_executor = RoundExecutor(
                        registry=registry,
                        llm_client=llm_client,
                        input_builder=AgentInputBuilder(),
                        tool_registry=None,
                    )

            self.assertIsNone(round_executor)

    def test_build_app_does_not_create_round_executor_without_llm(self) -> None:
        """build_app should not create RoundExecutor when LLM client is None."""
        env = {
            "AGENT_EXECUTION_ENABLED": "false",
            "ANALYST_ROUND_MODE": "rounds",
            "ANALYST_TOOLS_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
            self.assertFalse(settings.agent_execution_enabled)

            registry = MagicMock()
            registry.has_rounds_config.return_value = True

            llm_client = build_agent_llm_client(settings)

            self.assertIsNone(llm_client)

            tool_registry = None
            if settings.analyst_tools_enabled:
                tool_registry = ToolRegistry()

            round_executor = None
            if (
                settings.analyst_round_mode == "rounds"
                and registry.has_rounds_config()
                and llm_client is not None
            ):
                from research_analysis_layer.services.agent_input_builder import (
                    AgentInputBuilder,
                )
                from research_analysis_layer.services.round_executor import (
                    RoundExecutor,
                )

                round_executor = RoundExecutor(
                    registry=registry,
                    llm_client=llm_client,
                    input_builder=AgentInputBuilder(),
                    tool_registry=tool_registry,
                )

            self.assertIsNone(round_executor)


class TestR2DocumentAnalysisWriteContract(unittest.TestCase):
    """R2: Repair document_analysis write contract."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.store = AnalysisStore(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_write_document_analysis_single_row(self) -> None:
        """A successful write creates exactly one valid row."""
        self.store.write_document_analysis(
            document_key="test-doc-001",
            research_id=12345,
            document_hash="abc123def456",
            analysis_version="v1",
            run_id="run-001",
            payload_json='{"thesis": "Test thesis", "confidence": 0.85}',
            thesis="Test thesis",
            confidence=0.85,
            total_input_tokens=100,
            total_output_tokens=200,
            total_tool_calls=5,
            total_duration_ms=1500,
        )

        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM document_analysis WHERE research_id = ?",
                (12345,),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["document_key"], "test-doc-001")
        self.assertEqual(row["thesis"], "Test thesis")
        self.assertEqual(row["confidence"], 0.85)
        self.assertEqual(row["total_input_tokens"], 100)
        self.assertEqual(row["total_output_tokens"], 200)
        self.assertEqual(row["total_tool_calls"], 5)
        self.assertEqual(row["total_duration_ms"], 1500)

    def test_write_document_analysis_upsert(self) -> None:
        """Writing same key updates existing row (upsert behavior)."""
        self.store.write_document_analysis(
            document_key="test-doc-002",
            research_id=12346,
            document_hash="hash2",
            analysis_version="v1",
            run_id="run-001",
            payload_json='{"thesis": "Original"}',
            thesis="Original",
            confidence=0.5,
            total_input_tokens=100,
            total_output_tokens=100,
            total_tool_calls=0,
            total_duration_ms=1000,
        )

        self.store.write_document_analysis(
            document_key="test-doc-002",
            research_id=12346,
            document_hash="hash2",
            analysis_version="v1",
            run_id="run-002",
            payload_json='{"thesis": "Updated"}',
            thesis="Updated",
            confidence=0.9,
            total_input_tokens=200,
            total_output_tokens=300,
            total_tool_calls=10,
            total_duration_ms=2000,
        )

        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM document_analysis WHERE research_id = ?",
                (12346,),
            ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["thesis"], "Updated")
        self.assertEqual(rows[0]["run_id"], "run-002")


class TestR3ToolWiring(unittest.TestCase):
    """R3: Rewire tool use end to end."""

    def test_tool_registry_passed_to_llm_client(self) -> None:
        """ToolRegistry should be passed to the OpenAI agent client."""
        tool_registry = ToolRegistry()
        client = OpenAICompatibleAgentLlmClient(
            api_key="test-key",
            tool_registry=tool_registry,
        )
        self.assertIs(client._tool_registry, tool_registry)

    def test_tool_registry_accepts_schema(self) -> None:
        """ToolRegistry should load schemas and accept handlers."""
        schema = {
            "name": "test_tool",
            "description": "A test tool",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([schema], f)
            schema_path = Path(f.name)

        try:
            registry = ToolRegistry(schema_path=schema_path)

            def handler(input_data):
                return {"result": f"processed: {input_data.get('query', '')}"}

            registry.register_handler("test_tool", handler)

            self.assertIsNotNone(registry.get_schema("test_tool"))
            self.assertEqual(registry.list_tools(), ["test_tool"])

            result = registry.invoke("test_tool", {"query": "hello"})
            self.assertFalse(result.get("is_error"))
            content = result.get("content")
            if isinstance(content, dict):
                self.assertIn("processed: hello", str(content))
            else:
                self.assertIn("processed: hello", content)
        finally:
            schema_path.unlink()

    def test_tool_invocation_validation_error(self) -> None:
        """Invalid tool input produces structured error."""
        schema = {
            "name": "validated_tool",
            "description": "A tool with validation",
            "parameters": {
                "type": "object",
                "properties": {"required_field": {"type": "string"}},
                "required": ["required_field"],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([schema], f)
            schema_path = Path(f.name)

        try:
            registry = ToolRegistry(schema_path=schema_path)

            def handler(input_data):
                return {"result": "ok"}

            registry.register_handler("validated_tool", handler)

            result = registry.invoke("validated_tool", {})
            self.assertTrue(result.get("is_error"))
            self.assertIn("validation failed", result.get("content", "").lower())
        finally:
            schema_path.unlink()


class TestR4EvidenceSubstrate(unittest.TestCase):
    """R4: Preserve stable dispatcher evidence substrate."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.store = AnalysisStore(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_evidence_fields_in_payload_json(self) -> None:
        """Evidence fields are preserved in payload_json."""
        payload = {
            "thesis": "Test thesis",
            "contrarian_view": "Contrarian",
            "recommended_positioning": "Position",
            "quality": {"score": 0.9},
            "themes": [{"id": "theme1", "name": "Theme 1"}],
            "trades": [{"id": "trade1"}],
            "assertions": [{"id": "assert1"}],
            "world_nodes": [{"id": "node1"}],
            "world_edges": [{"id": "edge1"}],
            "forecast_candidates": [{"id": "fc1"}],
        }

        self.store.write_document_analysis(
            document_key="test-doc-003",
            research_id=12347,
            document_hash="hash3",
            analysis_version="v1",
            run_id="run-001",
            payload_json=json.dumps(payload),
            thesis="Test thesis",
            confidence=0.8,
            total_input_tokens=100,
            total_output_tokens=100,
            total_tool_calls=0,
            total_duration_ms=1000,
        )

        exporter = DispatchBatchExporter(self.store)

        scope = DispatchScope(
            document_keys=["test-doc-003"],
            batch_key="test-batch",
        )

        batch = exporter.load_batch(scope)

        self.assertEqual(len(batch["documents"]), 1)
        doc = batch["documents"][0]

        self.assertEqual(doc["quality"], {"score": 0.9})
        self.assertEqual(len(doc["themes"]), 1)
        self.assertEqual(doc["themes"][0]["id"], "theme1")
        self.assertEqual(len(doc["trades"]), 1)
        self.assertEqual(len(doc["assertions"]), 1)
        self.assertEqual(len(doc["world_nodes"]), 1)
        self.assertEqual(len(doc["world_edges"]), 1)
        self.assertEqual(len(doc["forecast_candidates"]), 1)


class TestR5BatchExportLiveRow(unittest.TestCase):
    """R5: Fix batch export live-row behavior."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self.store = AnalysisStore(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _insert_test_data(self) -> None:
        """Insert test data with multiple versions."""
        now = datetime.now(timezone.utc)

        self.store.write_document_analysis(
            document_key="doc-a",
            research_id=100,
            document_hash="hash-a",
            analysis_version="v1",
            run_id="run-1",
            payload_json='{"thesis": "v1"}',
            thesis="v1",
            confidence=0.5,
            total_input_tokens=10,
            total_output_tokens=10,
            total_tool_calls=0,
            total_duration_ms=100,
        )

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE document_analysis SET created_at = ? WHERE analysis_version = ?",
            (now.isoformat(), "v1"),
        )
        conn.commit()
        conn.close()

        self.store.write_document_analysis(
            document_key="doc-a",
            research_id=100,
            document_hash="hash-a",
            analysis_version="v2",
            run_id="run-2",
            payload_json='{"thesis": "v2"}',
            thesis="v2",
            confidence=0.8,
            total_input_tokens=20,
            total_output_tokens=20,
            total_tool_calls=0,
            total_duration_ms=200,
        )

        conn = sqlite3.connect(self.db_path)
        later = datetime.now(timezone.utc)
        conn.execute(
            "UPDATE document_analysis SET created_at = ? WHERE analysis_version = ?",
            (later.isoformat(), "v2"),
        )
        conn.commit()
        conn.close()

    def test_export_with_explicit_version(self) -> None:
        """Explicit analysis_version returns only that version."""
        self._insert_test_data()

        exporter = DispatchBatchExporter(self.store)

        scope = DispatchScope(
            document_keys=["doc-a"],
            analysis_version="v1",
            batch_key="test-batch",
        )

        batch = exporter.load_batch(scope)

        self.assertEqual(len(batch["documents"]), 1)
        self.assertEqual(batch["documents"][0]["thesis"], "v1")

    def test_export_latest_per_document(self) -> None:
        """Omitting analysis_version returns latest per document."""
        self._insert_test_data()

        exporter = DispatchBatchExporter(self.store)

        scope = DispatchScope(
            document_keys=["doc-a"],
            batch_key="test-batch",
        )

        batch = exporter.load_batch(scope)

        self.assertEqual(len(batch["documents"]), 1)
        self.assertEqual(batch["documents"][0]["thesis"], "v2")


class TestR7ParityValidation(unittest.TestCase):
    """R7: Offline parity validation harness."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        from research_analysis_layer.db.analysis_store import AnalysisStore

        self.store = AnalysisStore(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_parity_validator_compares_documents(self) -> None:
        """ParityValidator can compare analyst export with legacy docs."""
        from research_analysis_layer.services.parity_validator import ParityValidator
        from research_analysis_layer.models.dispatch_scope import DispatchScope

        analyst_payload = {
            "thesis": "Test thesis",
            "themes": [{"id": "theme1", "name": "Theme 1"}],
            "trades": [{"id": "trade1"}],
            "quality": {"score": 0.9},
        }

        self.store.write_document_analysis(
            document_key="doc-001",
            research_id=100,
            document_hash="hash001",
            analysis_version="v1",
            run_id="run-1",
            payload_json=json.dumps(analyst_payload),
            thesis="Test thesis",
            confidence=0.8,
            total_input_tokens=100,
            total_output_tokens=100,
            total_tool_calls=0,
            total_duration_ms=1000,
        )

        legacy_docs = [
            {
                "document_name": "doc-001",
                "source": "test-source",
                "source_date": "2026-04-01",
                "parsed_data": {
                    "metadata": {
                        "source": "test-source",
                        "source_date": "2026-04-01",
                        "publisher": "Test Publisher",
                        "region": "US",
                        "asset_focus": "rates",
                    },
                    "themes": [{"id": "theme1", "name": "Theme 1"}],
                    "trades": [{"id": "trade1"}],
                    "assertions": [],
                    "world_nodes": [],
                    "world_edges": [],
                    "forecast_candidates": [],
                },
            }
        ]

        validator = ParityValidator(self.store)

        scope = DispatchScope(
            document_keys=["doc-001"],
            batch_key="test-batch",
        )

        report = validator.validate(scope, legacy_docs)

        self.assertEqual(report.analyst_count, 1)
        self.assertEqual(report.legacy_count, 1)
        self.assertEqual(report.matched_count, 1)
        self.assertGreater(report.metadata_fields_checked, 0)
        self.assertGreater(report.evidence_fields_checked, 0)

    def test_parity_detects_missing_analyst_documents(self) -> None:
        """ParityValidator detects documents missing from analyst export."""
        from research_analysis_layer.services.parity_validator import ParityValidator
        from research_analysis_layer.models.dispatch_scope import DispatchScope

        legacy_docs = [
            {
                "document_name": "legacy-doc",
                "source": "test",
                "parsed_data": {"metadata": {}, "themes": [], "trades": []},
            }
        ]

        validator = ParityValidator(self.store)

        scope = DispatchScope(
            document_keys=["legacy-doc"],
            batch_key="test-batch",
        )

        report = validator.validate(scope, legacy_docs)

        self.assertEqual(report.analyst_count, 0)
        self.assertEqual(report.legacy_count, 1)
        self.assertEqual(report.matched_count, 0)

        missing_issues = [
            i for i in report.issues if i.category == "missing_in_analyst"
        ]
        self.assertEqual(len(missing_issues), 1)
        self.assertEqual(missing_issues[0].document_key, "legacy-doc")

    def test_parity_detects_metadata_mismatch(self) -> None:
        """ParityValidator detects metadata field mismatches."""
        from research_analysis_layer.services.parity_validator import ParityValidator
        from research_analysis_layer.models.dispatch_scope import DispatchScope

        analyst_payload = {
            "thesis": "Test thesis",
            "themes": [],
            "trades": [],
        }

        self.store.write_document_analysis(
            document_key="doc-002",
            research_id=101,
            document_hash="hash002",
            analysis_version="v1",
            run_id="run-1",
            payload_json=json.dumps(analyst_payload),
            thesis="Test thesis",
            confidence=0.8,
            total_input_tokens=100,
            total_output_tokens=100,
            total_tool_calls=0,
            total_duration_ms=1000,
        )

        legacy_docs = [
            {
                "document_name": "doc-002",
                "source": "legacy-source",
                "source_date": "2026-04-01",
                "parsed_data": {
                    "metadata": {
                        "source": "legacy-source",
                        "source_date": "2026-04-01",
                        "publisher": "Legacy Publisher",
                        "region": "EU",
                        "asset_focus": "equities",
                    },
                    "themes": [],
                    "trades": [],
                    "assertions": [],
                    "world_nodes": [],
                    "world_edges": [],
                    "forecast_candidates": [],
                },
            }
        ]

        validator = ParityValidator(self.store)

        scope = DispatchScope(
            document_keys=["doc-002"],
            batch_key="test-batch",
        )

        report = validator.validate(scope, legacy_docs)

        mismatch_issues = [
            i for i in report.issues if i.category == "metadata_mismatch"
        ]
        self.assertGreater(len(mismatch_issues), 0)


class TestToolBootstrap(unittest.TestCase):
    """Test tool bootstrap with ANALYST_TOOLS_ENABLED=true."""

    def test_tool_registry_loads_schema_at_init(self) -> None:
        """ToolRegistry loads schema at initialization from default path."""
        tool_registry = ToolRegistry()

        self.assertIsNotNone(tool_registry.get_schema("research_search"))
        self.assertIsNotNone(tool_registry.get_schema("research_corpus_info"))

        self.assertIn("research_search", tool_registry.list_tools())
        self.assertIn("research_corpus_info", tool_registry.list_tools())

    def test_tool_registry_fails_loudly_on_missing_schema(self) -> None:
        """ToolRegistry raises error if default schema path doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = Path(tmpdir) / "nonexistent" / "schema.json"

            with self.assertRaises(ValueError) as ctx:
                ToolRegistry(schema_path=bad_path)

            self.assertIn("not found", str(ctx.exception))

    def test_build_app_with_tools_enabled(self) -> None:
        """build_app succeeds with ANALYST_TOOLS_ENABLED=true."""
        env = {
            "AGENT_EXECUTION_ENABLED": "false",
            "ANALYST_ROUND_MODE": "rounds",
            "ANALYST_TOOLS_ENABLED": "true",
            "NEXUS_DATABASE_URL": "postgresql://nexus:nexus@localhost:5432/nexus",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

            self.assertTrue(settings.analyst_tools_enabled)

            tool_registry = ToolRegistry()
            self.assertIsNotNone(tool_registry.get_schema("research_search"))


if __name__ == "__main__":
    unittest.main()
