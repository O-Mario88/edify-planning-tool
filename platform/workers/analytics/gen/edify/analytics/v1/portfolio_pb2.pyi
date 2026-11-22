from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PortfolioSchool(_message.Message):
    __slots__ = ("school_type", "enrollment")
    SCHOOL_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    school_type: str
    enrollment: int
    def __init__(self, school_type: _Optional[str] = ..., enrollment: _Optional[int] = ...) -> None: ...

class SummarizePortfolioRequest(_message.Message):
    __slots__ = ("schools",)
    SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    schools: _containers.RepeatedCompositeFieldContainer[PortfolioSchool]
    def __init__(self, schools: _Optional[_Iterable[_Union[PortfolioSchool, _Mapping]]] = ...) -> None: ...

class SummarizePortfolioResponse(_message.Message):
    __slots__ = ("school_count", "schools_by_type", "schools_with_enrollment", "total_enrollment", "median_enrollment")
    class SchoolsByTypeEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    SCHOOL_COUNT_FIELD_NUMBER: _ClassVar[int]
    SCHOOLS_BY_TYPE_FIELD_NUMBER: _ClassVar[int]
    SCHOOLS_WITH_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    MEDIAN_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    school_count: int
    schools_by_type: _containers.ScalarMap[str, int]
    schools_with_enrollment: int
    total_enrollment: int
    median_enrollment: float
    def __init__(self, school_count: _Optional[int] = ..., schools_by_type: _Optional[_Mapping[str, int]] = ..., schools_with_enrollment: _Optional[int] = ..., total_enrollment: _Optional[int] = ..., median_enrollment: _Optional[float] = ...) -> None: ...

class SsaSchoolRecord(_message.Message):
    __slots__ = ("school_id", "current_score", "previous_score", "intervention_scores")
    class InterventionScoresEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    SCHOOL_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_SCORE_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_SCORE_FIELD_NUMBER: _ClassVar[int]
    INTERVENTION_SCORES_FIELD_NUMBER: _ClassVar[int]
    school_id: str
    current_score: float
    previous_score: float
    intervention_scores: _containers.ScalarMap[str, float]
    def __init__(self, school_id: _Optional[str] = ..., current_score: _Optional[float] = ..., previous_score: _Optional[float] = ..., intervention_scores: _Optional[_Mapping[str, float]] = ...) -> None: ...

class InterventionSummary(_message.Message):
    __slots__ = ("intervention", "assessed_count", "average_score", "min_score", "max_score", "urgent_count", "watch_count", "strong_count")
    INTERVENTION_FIELD_NUMBER: _ClassVar[int]
    ASSESSED_COUNT_FIELD_NUMBER: _ClassVar[int]
    AVERAGE_SCORE_FIELD_NUMBER: _ClassVar[int]
    MIN_SCORE_FIELD_NUMBER: _ClassVar[int]
    MAX_SCORE_FIELD_NUMBER: _ClassVar[int]
    URGENT_COUNT_FIELD_NUMBER: _ClassVar[int]
    WATCH_COUNT_FIELD_NUMBER: _ClassVar[int]
    STRONG_COUNT_FIELD_NUMBER: _ClassVar[int]
    intervention: str
    assessed_count: int
    average_score: float
    min_score: float
    max_score: float
    urgent_count: int
    watch_count: int
    strong_count: int
    def __init__(self, intervention: _Optional[str] = ..., assessed_count: _Optional[int] = ..., average_score: _Optional[float] = ..., min_score: _Optional[float] = ..., max_score: _Optional[float] = ..., urgent_count: _Optional[int] = ..., watch_count: _Optional[int] = ..., strong_count: _Optional[int] = ...) -> None: ...

class AnalyzeSsaRequest(_message.Message):
    __slots__ = ("records",)
    RECORDS_FIELD_NUMBER: _ClassVar[int]
    records: _containers.RepeatedCompositeFieldContainer[SsaSchoolRecord]
    def __init__(self, records: _Optional[_Iterable[_Union[SsaSchoolRecord, _Mapping]]] = ...) -> None: ...

class AnalyzeSsaResponse(_message.Message):
    __slots__ = ("total_schools", "assessed_schools", "compared_schools", "improved_schools", "declined_schools", "average_score", "average_delta", "on_track_count", "watch_count", "critical_count", "interventions")
    TOTAL_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    ASSESSED_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    COMPARED_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    IMPROVED_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    DECLINED_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    AVERAGE_SCORE_FIELD_NUMBER: _ClassVar[int]
    AVERAGE_DELTA_FIELD_NUMBER: _ClassVar[int]
    ON_TRACK_COUNT_FIELD_NUMBER: _ClassVar[int]
    WATCH_COUNT_FIELD_NUMBER: _ClassVar[int]
    CRITICAL_COUNT_FIELD_NUMBER: _ClassVar[int]
    INTERVENTIONS_FIELD_NUMBER: _ClassVar[int]
    total_schools: int
    assessed_schools: int
    compared_schools: int
    improved_schools: int
    declined_schools: int
    average_score: float
    average_delta: float
    on_track_count: int
    watch_count: int
    critical_count: int
    interventions: _containers.RepeatedCompositeFieldContainer[InterventionSummary]
    def __init__(self, total_schools: _Optional[int] = ..., assessed_schools: _Optional[int] = ..., compared_schools: _Optional[int] = ..., improved_schools: _Optional[int] = ..., declined_schools: _Optional[int] = ..., average_score: _Optional[float] = ..., average_delta: _Optional[float] = ..., on_track_count: _Optional[int] = ..., watch_count: _Optional[int] = ..., critical_count: _Optional[int] = ..., interventions: _Optional[_Iterable[_Union[InterventionSummary, _Mapping]]] = ...) -> None: ...

class CoverageSchoolRecord(_message.Message):
    __slots__ = ("area_name", "has_ssa", "visited", "trained")
    AREA_NAME_FIELD_NUMBER: _ClassVar[int]
    HAS_SSA_FIELD_NUMBER: _ClassVar[int]
    VISITED_FIELD_NUMBER: _ClassVar[int]
    TRAINED_FIELD_NUMBER: _ClassVar[int]
    area_name: str
    has_ssa: bool
    visited: bool
    trained: bool
    def __init__(self, area_name: _Optional[str] = ..., has_ssa: _Optional[bool] = ..., visited: _Optional[bool] = ..., trained: _Optional[bool] = ...) -> None: ...

class AreaCoverageGap(_message.Message):
    __slots__ = ("area_name", "total_schools", "ssa_covered", "visited_schools", "trained_schools", "ssa_coverage_pct", "visit_coverage_pct", "training_coverage_pct", "unassessed_gap", "unvisited_gap", "composite_gap_score")
    AREA_NAME_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    SSA_COVERED_FIELD_NUMBER: _ClassVar[int]
    VISITED_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    TRAINED_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    SSA_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    VISIT_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    TRAINING_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    UNASSESSED_GAP_FIELD_NUMBER: _ClassVar[int]
    UNVISITED_GAP_FIELD_NUMBER: _ClassVar[int]
    COMPOSITE_GAP_SCORE_FIELD_NUMBER: _ClassVar[int]
    area_name: str
    total_schools: int
    ssa_covered: int
    visited_schools: int
    trained_schools: int
    ssa_coverage_pct: float
    visit_coverage_pct: float
    training_coverage_pct: float
    unassessed_gap: int
    unvisited_gap: int
    composite_gap_score: float
    def __init__(self, area_name: _Optional[str] = ..., total_schools: _Optional[int] = ..., ssa_covered: _Optional[int] = ..., visited_schools: _Optional[int] = ..., trained_schools: _Optional[int] = ..., ssa_coverage_pct: _Optional[float] = ..., visit_coverage_pct: _Optional[float] = ..., training_coverage_pct: _Optional[float] = ..., unassessed_gap: _Optional[int] = ..., unvisited_gap: _Optional[int] = ..., composite_gap_score: _Optional[float] = ...) -> None: ...

class AnalyzeCoverageGapsRequest(_message.Message):
    __slots__ = ("records",)
    RECORDS_FIELD_NUMBER: _ClassVar[int]
    records: _containers.RepeatedCompositeFieldContainer[CoverageSchoolRecord]
    def __init__(self, records: _Optional[_Iterable[_Union[CoverageSchoolRecord, _Mapping]]] = ...) -> None: ...

class AnalyzeCoverageGapsResponse(_message.Message):
    __slots__ = ("total_schools", "overall_ssa_coverage_pct", "overall_visit_coverage_pct", "overall_training_coverage_pct", "areas")
    TOTAL_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    OVERALL_SSA_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    OVERALL_VISIT_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    OVERALL_TRAINING_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    AREAS_FIELD_NUMBER: _ClassVar[int]
    total_schools: int
    overall_ssa_coverage_pct: float
    overall_visit_coverage_pct: float
    overall_training_coverage_pct: float
    areas: _containers.RepeatedCompositeFieldContainer[AreaCoverageGap]
    def __init__(self, total_schools: _Optional[int] = ..., overall_ssa_coverage_pct: _Optional[float] = ..., overall_visit_coverage_pct: _Optional[float] = ..., overall_training_coverage_pct: _Optional[float] = ..., areas: _Optional[_Iterable[_Union[AreaCoverageGap, _Mapping]]] = ...) -> None: ...

class FieldDayRoute(_message.Message):
    __slots__ = ("staff_id", "stops_completed", "total_distance_km", "travel_minutes", "school_minutes")
    STAFF_ID_FIELD_NUMBER: _ClassVar[int]
    STOPS_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    TOTAL_DISTANCE_KM_FIELD_NUMBER: _ClassVar[int]
    TRAVEL_MINUTES_FIELD_NUMBER: _ClassVar[int]
    SCHOOL_MINUTES_FIELD_NUMBER: _ClassVar[int]
    staff_id: str
    stops_completed: int
    total_distance_km: float
    travel_minutes: int
    school_minutes: int
    def __init__(self, staff_id: _Optional[str] = ..., stops_completed: _Optional[int] = ..., total_distance_km: _Optional[float] = ..., travel_minutes: _Optional[int] = ..., school_minutes: _Optional[int] = ...) -> None: ...

class AnalyzeRouteEfficiencyRequest(_message.Message):
    __slots__ = ("field_days",)
    FIELD_DAYS_FIELD_NUMBER: _ClassVar[int]
    field_days: _containers.RepeatedCompositeFieldContainer[FieldDayRoute]
    def __init__(self, field_days: _Optional[_Iterable[_Union[FieldDayRoute, _Mapping]]] = ...) -> None: ...

class AnalyzeRouteEfficiencyResponse(_message.Message):
    __slots__ = ("field_day_count", "total_stops", "total_distance_km", "average_stops_per_day", "average_km_per_stop", "school_time_share_pct", "efficiency_score")
    FIELD_DAY_COUNT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STOPS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_DISTANCE_KM_FIELD_NUMBER: _ClassVar[int]
    AVERAGE_STOPS_PER_DAY_FIELD_NUMBER: _ClassVar[int]
    AVERAGE_KM_PER_STOP_FIELD_NUMBER: _ClassVar[int]
    SCHOOL_TIME_SHARE_PCT_FIELD_NUMBER: _ClassVar[int]
    EFFICIENCY_SCORE_FIELD_NUMBER: _ClassVar[int]
    field_day_count: int
    total_stops: int
    total_distance_km: float
    average_stops_per_day: float
    average_km_per_stop: float
    school_time_share_pct: float
    efficiency_score: float
    def __init__(self, field_day_count: _Optional[int] = ..., total_stops: _Optional[int] = ..., total_distance_km: _Optional[float] = ..., average_stops_per_day: _Optional[float] = ..., average_km_per_stop: _Optional[float] = ..., school_time_share_pct: _Optional[float] = ..., efficiency_score: _Optional[float] = ...) -> None: ...

class SchoolRiskInput(_message.Message):
    __slots__ = ("school_id", "latest_ssa", "ssa_delta", "days_since_last_visit", "has_cluster", "package_complete")
    SCHOOL_ID_FIELD_NUMBER: _ClassVar[int]
    LATEST_SSA_FIELD_NUMBER: _ClassVar[int]
    SSA_DELTA_FIELD_NUMBER: _ClassVar[int]
    DAYS_SINCE_LAST_VISIT_FIELD_NUMBER: _ClassVar[int]
    HAS_CLUSTER_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_COMPLETE_FIELD_NUMBER: _ClassVar[int]
    school_id: str
    latest_ssa: float
    ssa_delta: float
    days_since_last_visit: int
    has_cluster: bool
    package_complete: bool
    def __init__(self, school_id: _Optional[str] = ..., latest_ssa: _Optional[float] = ..., ssa_delta: _Optional[float] = ..., days_since_last_visit: _Optional[int] = ..., has_cluster: _Optional[bool] = ..., package_complete: _Optional[bool] = ...) -> None: ...

class SchoolRiskPrediction(_message.Message):
    __slots__ = ("school_id", "risk_score", "risk_tier", "drivers", "recommended_action")
    SCHOOL_ID_FIELD_NUMBER: _ClassVar[int]
    RISK_SCORE_FIELD_NUMBER: _ClassVar[int]
    RISK_TIER_FIELD_NUMBER: _ClassVar[int]
    DRIVERS_FIELD_NUMBER: _ClassVar[int]
    RECOMMENDED_ACTION_FIELD_NUMBER: _ClassVar[int]
    school_id: str
    risk_score: float
    risk_tier: str
    drivers: _containers.RepeatedScalarFieldContainer[str]
    recommended_action: str
    def __init__(self, school_id: _Optional[str] = ..., risk_score: _Optional[float] = ..., risk_tier: _Optional[str] = ..., drivers: _Optional[_Iterable[str]] = ..., recommended_action: _Optional[str] = ...) -> None: ...

class ComputePredictiveInsightsRequest(_message.Message):
    __slots__ = ("schools",)
    SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    schools: _containers.RepeatedCompositeFieldContainer[SchoolRiskInput]
    def __init__(self, schools: _Optional[_Iterable[_Union[SchoolRiskInput, _Mapping]]] = ...) -> None: ...

class ComputePredictiveInsightsResponse(_message.Message):
    __slots__ = ("high_risk_count", "medium_risk_count", "low_risk_count", "predictions")
    HIGH_RISK_COUNT_FIELD_NUMBER: _ClassVar[int]
    MEDIUM_RISK_COUNT_FIELD_NUMBER: _ClassVar[int]
    LOW_RISK_COUNT_FIELD_NUMBER: _ClassVar[int]
    PREDICTIONS_FIELD_NUMBER: _ClassVar[int]
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    predictions: _containers.RepeatedCompositeFieldContainer[SchoolRiskPrediction]
    def __init__(self, high_risk_count: _Optional[int] = ..., medium_risk_count: _Optional[int] = ..., low_risk_count: _Optional[int] = ..., predictions: _Optional[_Iterable[_Union[SchoolRiskPrediction, _Mapping]]] = ...) -> None: ...

class CountryMetricInput(_message.Message):
    __slots__ = ("country_code", "school_count", "assessed_schools", "visited_schools", "average_ssa", "total_enrollment")
    COUNTRY_CODE_FIELD_NUMBER: _ClassVar[int]
    SCHOOL_COUNT_FIELD_NUMBER: _ClassVar[int]
    ASSESSED_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    VISITED_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    AVERAGE_SSA_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    country_code: str
    school_count: int
    assessed_schools: int
    visited_schools: int
    average_ssa: float
    total_enrollment: int
    def __init__(self, country_code: _Optional[str] = ..., school_count: _Optional[int] = ..., assessed_schools: _Optional[int] = ..., visited_schools: _Optional[int] = ..., average_ssa: _Optional[float] = ..., total_enrollment: _Optional[int] = ...) -> None: ...

class CountryGlobalRow(_message.Message):
    __slots__ = ("country_code", "school_count", "ssa_coverage_pct", "visit_coverage_pct", "average_ssa", "total_enrollment", "suppressed")
    COUNTRY_CODE_FIELD_NUMBER: _ClassVar[int]
    SCHOOL_COUNT_FIELD_NUMBER: _ClassVar[int]
    SSA_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    VISIT_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    AVERAGE_SSA_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    SUPPRESSED_FIELD_NUMBER: _ClassVar[int]
    country_code: str
    school_count: int
    ssa_coverage_pct: float
    visit_coverage_pct: float
    average_ssa: float
    total_enrollment: int
    suppressed: bool
    def __init__(self, country_code: _Optional[str] = ..., school_count: _Optional[int] = ..., ssa_coverage_pct: _Optional[float] = ..., visit_coverage_pct: _Optional[float] = ..., average_ssa: _Optional[float] = ..., total_enrollment: _Optional[int] = ..., suppressed: _Optional[bool] = ...) -> None: ...

class GenerateGlobalReportRequest(_message.Message):
    __slots__ = ("countries", "min_cohort_size")
    COUNTRIES_FIELD_NUMBER: _ClassVar[int]
    MIN_COHORT_SIZE_FIELD_NUMBER: _ClassVar[int]
    countries: _containers.RepeatedCompositeFieldContainer[CountryMetricInput]
    min_cohort_size: int
    def __init__(self, countries: _Optional[_Iterable[_Union[CountryMetricInput, _Mapping]]] = ..., min_cohort_size: _Optional[int] = ...) -> None: ...

class GenerateGlobalReportResponse(_message.Message):
    __slots__ = ("country_count", "total_schools", "total_enrollment", "weighted_average_ssa", "overall_ssa_coverage_pct", "overall_visit_coverage_pct", "countries")
    COUNTRY_COUNT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    WEIGHTED_AVERAGE_SSA_FIELD_NUMBER: _ClassVar[int]
    OVERALL_SSA_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    OVERALL_VISIT_COVERAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    COUNTRIES_FIELD_NUMBER: _ClassVar[int]
    country_count: int
    total_schools: int
    total_enrollment: int
    weighted_average_ssa: float
    overall_ssa_coverage_pct: float
    overall_visit_coverage_pct: float
    countries: _containers.RepeatedCompositeFieldContainer[CountryGlobalRow]
    def __init__(self, country_count: _Optional[int] = ..., total_schools: _Optional[int] = ..., total_enrollment: _Optional[int] = ..., weighted_average_ssa: _Optional[float] = ..., overall_ssa_coverage_pct: _Optional[float] = ..., overall_visit_coverage_pct: _Optional[float] = ..., countries: _Optional[_Iterable[_Union[CountryGlobalRow, _Mapping]]] = ...) -> None: ...
