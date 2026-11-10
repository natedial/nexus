"""Swappable model configuration for agent-reference runs.

Two pieces keep providers and models easy to swap:

- A **model catalog** (JSON) lists every usable ``provider:model`` entry with
  its family, price card, and sampling controls. It also names the default
  model for each role.
- A **client registry** maps a provider name to a function that builds a
  single-attempt client for one catalog entry.

To swap a model, change the role's catalog key in the JSON file or pass
``--role annotator=openai:gpt-5.6-sol`` on the command line. To add a model,
add a catalog entry. To add a provider, register a client builder in
``CLIENT_BUILDERS``.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_analysis_layer.evals.decision_agent_provider import TokenPricing
from research_analysis_layer.evals.decision_agent_reference_run import Role
from research_analysis_layer.evals.decision_agent_references import ModelIdentity

MODEL_CATALOG_SCHEMA = "decision-agent-model-catalog-v1"
ROLES: tuple[Role, ...] = ("annotator", "reviewer", "adjudicator")


def default_model_catalog_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "evals"
        / "decision_pilot"
        / "models.json"
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogModel(StrictModel):
    """One pinned model a role can use."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    resolved_version: str | None = None
    input_usd_per_million: float = Field(gt=0)
    output_usd_per_million: float = Field(gt=0)
    pricing_source: str = Field(min_length=1)
    sampling: dict[str, Any] = Field(default_factory=dict)
    max_output_tokens: int = Field(default=16_000, gt=0)
    api_key_env: str | None = None
    base_url: str | None = None

    def identity(self) -> ModelIdentity:
        return ModelIdentity(
            provider=self.provider,
            model=self.model,
            model_family=self.model_family,
            resolved_version=self.resolved_version or self.model,
        )

    def pricing(self) -> TokenPricing:
        return TokenPricing(
            input_usd_per_million=self.input_usd_per_million,
            output_usd_per_million=self.output_usd_per_million,
            source=self.pricing_source,
        )


class ModelCatalog(StrictModel):
    schema_version: Literal["decision-agent-model-catalog-v1"] = MODEL_CATALOG_SCHEMA
    roles: dict[Role, str]
    models: dict[str, CatalogModel]

    @model_validator(mode="after")
    def _roles_point_at_entries(self) -> ModelCatalog:
        for key, entry in self.models.items():
            expected = f"{entry.provider}:{entry.model}"
            if key != expected:
                raise ValueError(
                    f"catalog key {key!r} must be '<provider>:<model>' ({expected!r})"
                )
        unknown = {key for key in self.roles.values() if key not in self.models}
        if unknown:
            raise ValueError(f"roles reference unknown catalog entries: {sorted(unknown)}")
        return self


def load_model_catalog(path: Path | None = None) -> ModelCatalog:
    path = path or default_model_catalog_path()
    return ModelCatalog.model_validate_json(path.read_text(encoding="utf-8"))


def parse_role_overrides(values: Sequence[str]) -> dict[Role, str]:
    """Parse ``role=provider:model`` flags; a later flag for a role wins."""

    overrides: dict[Role, str] = {}
    for value in values:
        role, sep, key = value.partition("=")
        role = role.strip()
        key = key.strip()
        if not sep or not key:
            raise ValueError(f"role override must look like role=provider:model, got {value!r}")
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}; expected one of {list(ROLES)}")
        overrides[role] = key  # type: ignore[index]
    return overrides


@dataclass(frozen=True)
class ResolvedRoleModels:
    entries: dict[Role, CatalogModel]

    @property
    def role_models(self) -> dict[Role, ModelIdentity]:
        return {role: entry.identity() for role, entry in self.entries.items()}

    @property
    def pricing_by_role(self) -> dict[Role, TokenPricing]:
        return {role: entry.pricing() for role, entry in self.entries.items()}

    @property
    def sampling_by_role(self) -> dict[Role, dict[str, Any]]:
        return {role: dict(entry.sampling) for role, entry in self.entries.items()}

    def describe(self) -> dict[str, str]:
        return {
            role: f"{entry.provider}:{entry.model} ({entry.model_family})"
            for role, entry in self.entries.items()
        }


def resolve_role_models(
    catalog: ModelCatalog,
    overrides: Mapping[Role, str] | None = None,
    *,
    adjudicate: bool = False,
) -> ResolvedRoleModels:
    assignments: dict[Role, str] = dict(catalog.roles)
    assignments.update(overrides or {})
    required: list[Role] = ["annotator", "reviewer"]
    if adjudicate:
        required.append("adjudicator")
    entries: dict[Role, CatalogModel] = {}
    for role in required:
        key = assignments.get(role)
        if key is None:
            raise ValueError(f"no model assigned to role {role!r}")
        entry = catalog.models.get(key)
        if entry is None:
            raise ValueError(
                f"{role} model {key!r} is not in the catalog; add it with its "
                "family and price card first"
            )
        entries[role] = entry
    return ResolvedRoleModels(entries=entries)


# --- client registry -------------------------------------------------------

ClientBuilder = Callable[[CatalogModel], Any]


def _api_key(entry: CatalogModel, default_env: str) -> str:
    name = entry.api_key_env or default_env
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{entry.provider}:{entry.model} needs ${name} to be set")
    return value


def _build_openai(entry: CatalogModel) -> Any:
    from research_analysis_layer.services.agent_llm_client import (
        OpenAICompatibleAgentLlmClient,
    )

    effort = entry.sampling.get("reasoning_effort")
    unknown = set(entry.sampling) - {"reasoning_effort"}
    if unknown:
        raise ValueError(f"OpenAI clients cannot apply sampling keys {sorted(unknown)}")
    return OpenAICompatibleAgentLlmClient(
        api_key=_api_key(entry, "OPENAI_API_KEY"),
        base_url=entry.base_url,
        use_max_completion_tokens=entry.provider == "openai",
        max_output_tokens=entry.max_output_tokens,
        reasoning_effort=effort,
        max_transport_retries=0,
        report_response_model=True,
    )


def _build_openai_compatible(entry: CatalogModel) -> Any:
    if not entry.base_url or not entry.api_key_env:
        raise ValueError("openai_compatible entries need base_url and api_key_env")
    return _build_openai(entry)


def _build_anthropic(entry: CatalogModel) -> Any:
    from research_analysis_layer.evals.decision_agent_anthropic import (
        AnthropicReferenceClient,
    )

    return AnthropicReferenceClient(
        api_key=_api_key(entry, "ANTHROPIC_API_KEY"),
        sampling_by_model={entry.model: dict(entry.sampling)},
        max_output_tokens=entry.max_output_tokens,
    )


CLIENT_BUILDERS: dict[str, ClientBuilder] = {
    "anthropic": _build_anthropic,
    "openai": _build_openai,
    "openai_compatible": _build_openai_compatible,
}


def build_role_clients(
    resolved: ResolvedRoleModels,
    *,
    builders: Mapping[str, ClientBuilder] | None = None,
) -> dict[Role, Any]:
    """Build one client per role; roles on the same entry share a client."""

    registry = dict(CLIENT_BUILDERS if builders is None else builders)
    clients: dict[Role, Any] = {}
    built: dict[str, Any] = {}
    for role, entry in resolved.entries.items():
        key = f"{entry.provider}:{entry.model}"
        if key not in built:
            builder = registry.get(entry.provider)
            if builder is None:
                raise ValueError(
                    f"no client builder for provider {entry.provider!r}; "
                    f"known providers: {sorted(registry)}"
                )
            built[key] = builder(entry)
        clients[role] = built[key]
    return clients


def is_retryable_transport_error(exc: Exception) -> bool:
    """Transport failures the harness may retry within its fixed bound."""

    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    if isinstance(exc, (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError)):
        return True
    try:
        import anthropic
    except ImportError:  # pragma: no cover - dependency is declared
        return False
    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False


__all__ = [
    "CLIENT_BUILDERS",
    "CatalogModel",
    "ModelCatalog",
    "ResolvedRoleModels",
    "build_role_clients",
    "default_model_catalog_path",
    "is_retryable_transport_error",
    "load_model_catalog",
    "parse_role_overrides",
    "resolve_role_models",
]
