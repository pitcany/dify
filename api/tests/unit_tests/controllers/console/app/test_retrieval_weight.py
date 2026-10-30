"""Console retrieval weight report keeps the message-log admission policy and its wire contract."""

import random
from collections.abc import Sequence
from datetime import datetime, timedelta
from inspect import unwrap
from types import SimpleNamespace
from uuid import UUID

import pytest
from flask import Flask
from werkzeug.exceptions import Forbidden

from controllers.console import flask_admission
from controllers.console.app import retrieval_weight as retrieval_weight_module
from controllers.console.app.error import AppNotFoundError
from controllers.console.app.retrieval_weight import RetrievalWeightRecommendationApi
from domain.retrieval_weight_tuning.weight_recommendation import TuningPolicy
from libs.login import AccountWithTenant
from models.account import TenantAccountRole
from services.knowledge.retrieval.weight_recommendations import (
    RetrievalWeightRecommendationService,
    RunFeedbackRecord,
    TraceCandidateRecord,
    WeightTraceRecord,
)
from tests.helpers.unit.config_override import apply_config_overrides
from tests.helpers.unit.model_factories import make_account

WORKSPACE_ID = "tenant-123"
APP_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 10, 30, 12)
ROBUST = (TraceCandidateRecord(0.9, 0.9, True), TraceCandidateRecord(0.5, 0.1, False))
VECTOR_FAVOURED = (TraceCandidateRecord(0.9, 0.1, True), TraceCandidateRecord(0.5, 0.8, False))


def _trace(run_id: str, candidates: tuple[TraceCandidateRecord, ...], dataset_id: str | None) -> WeightTraceRecord:
    return WeightTraceRecord(
        workflow_run_id=run_id,
        node_id="knowledge",
        stage="dataset" if dataset_id else "cross_dataset",
        dataset_id=dataset_id,
        embedding_provider_name="provider",
        embedding_model_name="embedding",
        vector_weight=0.7,
        keyword_weight=0.3,
        score_threshold=None,
        top_n=1,
        candidates=candidates,
        created_at=NOW - timedelta(hours=1),
    )


class _Evidence:
    def __init__(self) -> None:
        self.feedback = [
            RunFeedbackRecord("liked-1", "like", "user"),
            RunFeedbackRecord("liked-2", "like", "user"),
            RunFeedbackRecord("disliked-1", "dislike", "user"),
            RunFeedbackRecord("disliked-2", "dislike", "admin"),
        ]
        self.traces = [
            _trace("liked-1", ROBUST, None),
            _trace("liked-2", ROBUST, None),
            _trace("disliked-1", VECTOR_FAVOURED, None),
            _trace("disliked-2", VECTOR_FAVOURED, None),
            _trace("liked-1", ROBUST, "dataset-1"),
        ]

    def app_exists(self, *, tenant_id: str, app_id: str) -> bool:
        return (tenant_id, app_id) == (WORKSPACE_ID, str(APP_ID))

    def run_feedback(self, *, tenant_id: str, app_id: str, since: datetime, limit: int) -> Sequence[RunFeedbackRecord]:
        assert (tenant_id, app_id, since, limit) == (WORKSPACE_ID, str(APP_ID), NOW - timedelta(days=30), 100)
        return self.feedback

    def traces_for_runs(
        self, *, tenant_id: str, app_id: str, workflow_run_ids: Sequence[str]
    ) -> Sequence[WeightTraceRecord]:
        assert (tenant_id, app_id) == (WORKSPACE_ID, str(APP_ID))
        return [trace for trace in self.traces if trace.workflow_run_id in workflow_run_ids]


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> RetrievalWeightRecommendationService:
    recommendations = RetrievalWeightRecommendationService(
        evidence=_Evidence(),
        policy=TuningPolicy(
            grid_step=0.05,
            min_runs_per_rating=2,
            min_shift=0.1,
            stability_radius=0.1,
            min_stability=0.6,
            confidence=0.9,
            resamples=20,
        ),
        window_days=30,
        max_feedback=100,
        now=lambda: NOW,
        new_sampler=lambda: random.Random(0).randrange,  # noqa: S311 - deterministic resampling
        tracing_enabled=True,
    )
    monkeypatch.setattr(
        retrieval_weight_module,
        "application_services",
        lambda: SimpleNamespace(retrieval_weight_recommendations=recommendations),
    )
    return recommendations


def _admit(monkeypatch: pytest.MonkeyPatch, role: TenantAccountRole) -> None:
    apply_config_overrides(monkeypatch, RBAC_ENABLED=False)
    monkeypatch.setattr(
        flask_admission,
        "current_account_with_tenant",
        lambda: AccountWithTenant(make_account(account_id="account-123", role=role), WORKSPACE_ID),
    )
    monkeypatch.setattr(flask_admission, "get_trace_id", lambda: None)


def _get(app: Flask, app_id: UUID) -> object:
    view = unwrap(
        RetrievalWeightRecommendationApi.get, stop=lambda view: "inject_request_context" in view.__code__.co_qualname
    )
    with app.test_request_context(method="GET"):
        return view(None, app_id=app_id)


@pytest.mark.usefixtures("service")
@pytest.mark.parametrize("role", [TenantAccountRole.NORMAL, TenantAccountRole.DATASET_OPERATOR])
def test_read_only_roles_are_rejected(app: Flask, monkeypatch: pytest.MonkeyPatch, role: TenantAccountRole) -> None:
    _admit(monkeypatch, role)

    with pytest.raises(Forbidden):
        _get(app, APP_ID)


@pytest.mark.usefixtures("service")
def test_unknown_app_is_not_found(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    _admit(monkeypatch, TenantAccountRole.EDITOR)

    with pytest.raises(AppNotFoundError):
        _get(app, UUID("22222222-2222-2222-2222-222222222222"))


@pytest.mark.usefixtures("service")
def test_report_flattens_each_verdict(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    _admit(monkeypatch, TenantAccountRole.EDITOR)

    body = _get(app, APP_ID)

    assert isinstance(body, dict)
    assert (body["app_id"], body["tracing_enabled"], body["rated_runs"]) == (str(APP_ID), True, 4)
    assert body["window_start"] == int((NOW - timedelta(days=30)).timestamp())
    cross_dataset, dataset = body["units"]
    assert cross_dataset["stage"] == "cross_dataset"
    assert cross_dataset["dataset_id"] is None
    assert cross_dataset["verdict"] == "recommend_change"
    assert cross_dataset["recommended_vector_weight"] == pytest.approx(0.6)
    assert cross_dataset["required_per_rating"] is None
    assert cross_dataset["analysis"]["interval_low"] == pytest.approx(1.0)
    assert {"vector_weight": 0.7, "improvement": 0.0} in cross_dataset["analysis"]["curve"]
    assert dataset == {
        "node_id": "knowledge",
        "stage": "dataset",
        "dataset_id": "dataset-1",
        "embedding_provider_name": "provider",
        "embedding_model_name": "embedding",
        "current_vector_weight": pytest.approx(0.7),
        "weights_changed_in_window": False,
        "verdict": "insufficient_evidence",
        "recommended_vector_weight": None,
        "liked_runs": 1,
        "disliked_runs": 0,
        "required_per_rating": 2,
        "analysis": None,
    }
