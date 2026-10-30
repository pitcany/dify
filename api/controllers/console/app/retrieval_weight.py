"""Console report of recommend-only keyword/vector weight tuning for a chatflow app."""

from datetime import datetime
from http import HTTPStatus
from typing import Literal
from uuid import UUID

from flask_restx import Resource
from pydantic import Field, field_validator

from controllers.common.rbac import PlainApp, RBACCheck
from controllers.common.schema import register_response_schema_models
from controllers.console import console_ns
from controllers.console.app.error import AppNotFoundError
from controllers.console.flask_admission import console_account_admission
from controllers.console.wraps import RBACPermission
from domain.retrieval_weight_tuning.weight_recommendation import (
    InsufficientEvidence,
    KeepCurrentWeight,
    RecommendWeightChange,
    WeightAnalysis,
)
from enums.account import TenantAccountRole
from extensions.ext_application_services import application_services
from fields.base import ResponseModel
from libs.external_api import error_responses
from libs.helper import dump_response, to_timestamp
from machinery.context import RequestContext
from services.knowledge.retrieval.weight_recommendations import (
    RecommendationAppNotFoundError,
    RetrievalWeightReport,
    UnitRecommendation,
)


class RetrievalWeightCurvePointResponse(ResponseModel):
    vector_weight: float
    improvement: float


class RetrievalWeightAnalysisResponse(ResponseModel):
    best_vector_weight: float
    improvement: float = Field(description="Liked minus disliked retention at the best weight; 0 is what users saw.")
    interval_low: float
    interval_high: float
    stability: float = Field(description="Share of bootstrap resamples whose best weight is near the best weight.")
    affected_share: float = Field(description="Share of rated runs that would lose at least one shown result.")
    curve: list[RetrievalWeightCurvePointResponse]


class RetrievalWeightUnitResponse(ResponseModel):
    node_id: str
    stage: Literal["dataset", "cross_dataset"]
    dataset_id: str | None = Field(description="Set for the dataset stage; null for the cross-dataset merge.")
    embedding_provider_name: str
    embedding_model_name: str
    current_vector_weight: float
    weights_changed_in_window: bool
    verdict: Literal["insufficient_evidence", "keep_current", "recommend_change"]
    recommended_vector_weight: float | None = Field(description="Set only when the verdict is recommend_change.")
    liked_runs: int
    disliked_runs: int
    required_per_rating: int | None = Field(description="Set only when the verdict is insufficient_evidence.")
    analysis: RetrievalWeightAnalysisResponse | None = Field(
        description="Null when the verdict is insufficient_evidence."
    )


class RetrievalWeightReportResponse(ResponseModel):
    app_id: str
    tracing_enabled: bool
    window_start: int
    rated_runs: int
    units: list[RetrievalWeightUnitResponse]

    @field_validator("window_start", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | int) -> int | None:
        return to_timestamp(value)


register_response_schema_models(
    console_ns,
    RetrievalWeightCurvePointResponse,
    RetrievalWeightAnalysisResponse,
    RetrievalWeightUnitResponse,
    RetrievalWeightReportResponse,
)


@console_ns.route("/apps/<uuid:app_id>/retrieval-weight-recommendations")
class RetrievalWeightRecommendationApi(Resource):
    @error_responses(AppNotFoundError)
    @console_ns.doc("get_retrieval_weight_recommendations")
    @console_ns.doc(
        description="Advisory keyword/vector weight recommendations for weighted-score retrieval, from message "
        "feedback. Nothing is applied."
    )
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.response(HTTPStatus.OK, "Success", console_ns.models[RetrievalWeightReportResponse.__name__])
    @console_account_admission(
        allowed_roles=frozenset({TenantAccountRole.OWNER, TenantAccountRole.ADMIN, TenantAccountRole.EDITOR}),
        rbac_checks=(RBACCheck(RBACPermission.APP_VIEW_LAYOUT, PlainApp()),),
    )
    def get(self, context: RequestContext, app_id: UUID) -> dict[str, object]:
        try:
            report = application_services().retrieval_weight_recommendations.recommend(context, str(app_id))
        except RecommendationAppNotFoundError as exc:
            raise AppNotFoundError() from exc
        return dump_response(RetrievalWeightReportResponse, _report_payload(report))


def _report_payload(report: RetrievalWeightReport) -> dict[str, object]:
    return {
        "app_id": report.app_id,
        "tracing_enabled": report.tracing_enabled,
        "window_start": report.window_start,
        "rated_runs": report.rated_runs,
        "units": [_unit_payload(entry) for entry in report.units],
    }


def _unit_payload(entry: UnitRecommendation) -> dict[str, object]:
    unit = entry.unit
    identity: dict[str, object] = {
        "node_id": unit.node_id,
        "stage": unit.stage,
        "dataset_id": unit.dataset_id,
        "embedding_provider_name": unit.embedding_provider_name,
        "embedding_model_name": unit.embedding_model_name,
        "current_vector_weight": entry.current_vector_weight,
        "weights_changed_in_window": entry.weights_changed_in_window,
    }
    match entry.recommendation:
        case InsufficientEvidence(liked_runs=liked, disliked_runs=disliked, required_per_rating=required):
            return {
                **identity,
                "verdict": "insufficient_evidence",
                "recommended_vector_weight": None,
                "liked_runs": liked,
                "disliked_runs": disliked,
                "required_per_rating": required,
                "analysis": None,
            }
        case KeepCurrentWeight(analysis=analysis):
            return {**identity, **_analysed_payload("keep_current", None, analysis)}
        case RecommendWeightChange(recommended_vector_weight=weight, analysis=analysis):
            return {**identity, **_analysed_payload("recommend_change", weight, analysis)}


def _analysed_payload(
    verdict: Literal["keep_current", "recommend_change"], recommended: float | None, analysis: WeightAnalysis
) -> dict[str, object]:
    return {
        "verdict": verdict,
        "recommended_vector_weight": recommended,
        "liked_runs": analysis.liked_runs,
        "disliked_runs": analysis.disliked_runs,
        "required_per_rating": None,
        "analysis": {
            "best_vector_weight": analysis.best_vector_weight,
            "improvement": analysis.improvement,
            "interval_low": analysis.interval[0],
            "interval_high": analysis.interval[1],
            "stability": analysis.stability,
            "affected_share": analysis.affected_share,
            "curve": [{"vector_weight": weight, "improvement": value} for weight, value in analysis.curve],
        },
    }
