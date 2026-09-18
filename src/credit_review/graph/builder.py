"""LangGraph MVP for a sequential Parent–Child evidence review loop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Literal

try:  # LangGraph is optional for the provider-free MVP/test environment.
    from langgraph.graph import END, START, StateGraph
except ModuleNotFoundError:  # pragma: no cover - exercised through integration tests
    END = "__end__"
    START = "__start__"

    class StateGraph:  # type: ignore[no-redef]
        """Small compatibility runner implementing the subset used by this graph."""

        def __init__(self, state_type: Any) -> None:
            self.nodes: dict[str, Any] = {}
            self.edges: dict[str, str] = {}
            self.conditional: dict[str, Any] = {}

        def add_node(self, name: str, fn: Any) -> None:
            self.nodes[name] = fn

        def add_edge(self, source: str, target: str) -> None:
            self.edges[source] = target

        def add_conditional_edges(self, source: str, router: Any) -> None:
            self.conditional[source] = router

        def compile(self) -> "_CompiledFallbackGraph":
            return _CompiledFallbackGraph(self.nodes, self.edges, self.conditional)


    class _CompiledFallbackGraph:
        def __init__(self, nodes: dict[str, Any], edges: dict[str, str], conditional: dict[str, Any]) -> None:
            self.nodes, self.edges, self.conditional = nodes, edges, conditional

        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            current = self.edges[START]
            working = dict(state)
            while current != END:
                update = self.nodes[current](working) or {}
                working.update(update)
                if current in self.conditional:
                    current = self.conditional[current](working)
                else:
                    current = self.edges[current]
            return working

from credit_review.domain.models import Evidence
from credit_review.config.models import RetrievalConfig
from credit_review.agents.planning_agent import FinancialPlanningAgent, validate_retrieval_plan
from credit_review.graph.state import ReviewState
from credit_review.services.mvp_services import (
    DeterministicParentChildExtractor,
    MvpEvidenceGrader,
    MvpFactVerifier,
    SimpleCompanyResolver,
    SimpleQueryPlanner,
)
from credit_review.policies.risk import RiskPolicy
from credit_review.rules.engine import RuleEngine, default_rules
from credit_review.verification.numeric import DeterministicNumericValidator
from credit_review.retrieval.service import RetrievalRouter


@dataclass
class MvpServices:
    extractor: Any
    company_resolver: Any
    query_planner: Any
    retriever: Any
    grader: Any
    verifier: Any
    max_retry: int = 1
    numeric_validator: Any | None = None
    rule_engine: Any | None = None
    risk_policy: Any | None = None
    critic_verifier: Any | None = None


def _coerce_evidence(items: list[Evidence | dict[str, Any]] | None) -> list[Evidence]:
    normalized: list[Evidence] = []
    for item in items or []:
        if isinstance(item, Evidence):
            normalized.append(item)
            continue
        if not isinstance(item, dict):
            raise TypeError("evidence items must be Evidence or dict")
        try:
            if not isinstance(item["evidence_id"], str) or not isinstance(item["content"], str) or not isinstance(item["source"], str):
                raise TypeError("evidence_id, content and source must be strings")
            if item.get("page") is not None and not isinstance(item.get("page"), int):
                raise TypeError("page must be an integer or None")
            if item.get("evidence_type", "text") not in {"text", "table"}:
                raise ValueError("evidence_type must be text or table")
            normalized.append(
                Evidence(
                    evidence_id=item["evidence_id"],
                    content=item["content"],
                    source=item["source"],
                    page=item.get("page"),
                    evidence_type=item.get("evidence_type", "text"),
                    score=float(item.get("score", 0.0)),
                    table_name=item.get("table_name"),
                    row=item.get("row"),
                    column=item.get("column"),
                    document_id=item.get("document_id"),
                    document_version=item.get("document_version"),
                    company_id=item.get("company_id"),
                    period=item.get("period"),
                    content_hash=item.get("content_hash"),
                    table_id=item.get("table_id"),
                    section=item.get("section"),
                    metric_ids=list(item.get("metric_ids") or []),
                    structured=bool(item.get("structured", False)),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid evidence item: {item!r}") from exc
    return normalized


def default_services(
    evidence: list[Evidence | dict[str, Any]] | None = None,
    companies: dict[str, dict[str, str]] | None = None,
    source_scope: dict[str, Any] | None = None,
    *,
    retrieval_backend: str | None = None,
    retrieval_config: RetrievalConfig | None = None,
    index_dir: Path | str | None = None,
) -> MvpServices:
    config = retrieval_config or RetrievalConfig.from_env()
    backend = retrieval_backend or config.backend
    normalized_evidence = _coerce_evidence(evidence)
    if backend == "sentence_transformers":
        from credit_review.infrastructure.retrieval_stack import create_production_router

        retriever = create_production_router(
            normalized_evidence,
            config=config,
            index_dir=index_dir,
            default_scope=source_scope,
        )
    elif backend == "deterministic":
        retriever = RetrievalRouter(normalized_evidence, default_scope=source_scope)
    else:
        raise ValueError(f"unsupported retrieval backend: {backend}")
    return MvpServices(
        extractor=DeterministicParentChildExtractor(),
        company_resolver=SimpleCompanyResolver(companies),
        query_planner=FinancialPlanningAgent(),
        retriever=retriever,
        grader=MvpEvidenceGrader(),
        verifier=MvpFactVerifier(),
        numeric_validator=DeterministicNumericValidator(),
        rule_engine=RuleEngine(default_rules()),
        risk_policy=RiskPolicy(),
        critic_verifier=MvpFactVerifier(),
    )


def deepseek_services(
    evidence: list[Evidence | dict[str, Any]] | None = None,
    companies: dict[str, dict[str, str]] | None = None,
    source_scope: dict[str, Any] | None = None,
    gateway: Any | None = None,
    *,
    retrieval_backend: str | None = None,
    retrieval_config: RetrievalConfig | None = None,
    index_dir: Path | str | None = None,
) -> MvpServices:
    """Build services using DeepSeek only for structured agent decisions.

    Retrieval uses the configured deterministic or Sentence-Transformers stack;
    numeric validation, rules and risk gating stay local. ``gateway`` is
    injectable for tests; when omitted it reads the environment.
    """
    from credit_review.agents.deepseek_agents import DeepSeekFactVerifier, DeepSeekParentChildExtractor, DeepSeekQueryPlanner
    from credit_review.infrastructure.deepseek_gateway import DeepSeekGateway

    gateway = gateway or DeepSeekGateway()
    services = default_services(
        evidence=evidence,
        companies=companies,
        source_scope=source_scope,
        retrieval_backend=retrieval_backend,
        retrieval_config=retrieval_config,
        index_dir=index_dir,
    )
    services.extractor = DeepSeekParentChildExtractor(gateway, services.extractor)
    services.query_planner = DeepSeekQueryPlanner(gateway, services.query_planner)
    services.verifier = DeepSeekFactVerifier(gateway, services.verifier)
    services.critic_verifier = DeepSeekFactVerifier(gateway, services.critic_verifier)
    return services


def _flatten_fact_groups(fact_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    work_items: list[dict[str, Any]] = []
    for group in fact_groups:
        parent = group["parent"]
        for child in group["children"]:
            work_items.append({"parent": parent, "child": child})
    return work_items


def _trace_summary(node: str, state: dict[str, Any]) -> dict[str, Any]:
    """Return a concise, auditable summary of a completed graph node."""
    if node == "extract_parent_child":
        return {
            "parent_count": len(state.get("fact_groups", [])),
            "children": [
                {"fact_id": item["child"].get("fact_id"), "fact": item["child"].get("fact")}
                for item in state.get("flat_children", [])
            ],
        }
    if node == "resolve_company":
        return {"company_info": state.get("company_info")}
    if node == "prepare_child":
        return {
            "parent_id": (state.get("current_parent") or {}).get("parent_id"),
            "claim": (state.get("current_fact") or {}).get("fact"),
        }
    if node in {"plan_query", "rewrite_query"}:
        plan = state.get("retrieval_plan") or {}
        requests = state.get("current_queries", [])
        return {
            "plan_id": plan.get("plan_id"),
            "analysis_concept": plan.get("analysis_concept"),
            "entity_profile": plan.get("entity_profile"),
            "stop_conditions": plan.get("stop_conditions", []),
            "requests": [
                {
                    key: request[key]
                    for key in (
                        "query_id", "need_id", "query_text", "retrieval_profile", "metric_ids",
                        "formula_id", "periods", "evidence_types", "dense_top_k", "lexical_top_k",
                        "candidate_top_k", "rerank_top_n",
                    )
                    if key in request
                }
                for request in requests
            ],
        }
    if node == "retrieve":
        count = len(state.get("current_queries", []))
        traces = state.get("retrieval_trace", [])[-count:] if count else []
        return {"queries": traces, "unique_evidence_count": len(state.get("current_evidence", []))}
    if node == "grade_evidence":
        return {
            "evidence_status": state.get("evidence_status"),
            "observation": state.get("evidence_observation"),
            "assessments": [
                {
                    key: item[key]
                    for key in ("evidence_id", "relation", "usable", "reason")
                    if key in item
                }
                for item in state.get("current_assessments", [])
            ],
        }
    if node == "verify":
        result = state.get("verification_result") or {}
        return {key: result.get(key) for key in ("status", "reason", "confidence", "evidence_ids") if key in result}
    if node == "numeric_check":
        return {"checks": state.get("numeric_checks", [])}
    if node == "rule_check":
        return {"rule_hits": state.get("rule_hits", [])}
    if node in {"risk_gate", "compare"}:
        return {"risk_decision": state.get("risk_decision")}
    if node == "critic":
        return {"critic_verdict": state.get("critic_verdict")}
    if node == "human_review":
        return {"human_task": state.get("human_task")}
    if node == "finalize_child":
        result = (state.get("completed_results") or [{}])[-1]
        return {
            "fact_id": result.get("fact_id"),
            "status": result.get("status"),
            "confidence": result.get("confidence"),
            "evidence_ids": [item.get("evidence_id") for item in result.get("evidence", [])],
        }
    if node == "aggregate":
        return {"summary_counts": (state.get("review_result") or {}).get("summary_counts", {})}
    return {}


def build_review_graph(services: MvpServices, *, trace: Callable[[dict[str, Any]], None] | None = None):
    """Build the MVP graph with all external capabilities injected."""

    def extract_parent_child(state: ReviewState) -> dict[str, Any]:
        groups = services.extractor.extract(state["original_input"])
        return {
            "fact_groups": groups,
            "flat_children": _flatten_fact_groups(groups),
            "completed_results": [],
            "child_index": 0,
            "workflow_status": "EXTRACTED",
        }

    def resolve_company(state: ReviewState) -> dict[str, Any]:
        return {
            "company_info": services.company_resolver.resolve(state["original_input"]),
            "workflow_status": "COMPANY_RESOLVED",
        }

    def prepare_child(state: ReviewState) -> dict[str, Any]:
        item = state["flat_children"][state["child_index"]]
        return {
            "current_parent": item["parent"],
            "current_fact": item["child"],
            "retrieval_plan": None,
            "evidence_requirements": [],
            "current_queries": [],
            "current_evidence": [],
            "retrieval_trace": [],
            "evidence_status": None,
            "evidence_observation": None,
            "missing_needs": [],
            "retry_count": 0,
            "current_assessments": [],
            "verification_result": None,
            "initial_verdict": None,
            "critic_verdict": None,
            "numeric_checks": [],
            "rule_hits": [],
            "risk_decision": None,
            "human_task": None,
            "workflow_status": "CHILD_STARTED",
        }

    def traced_node(name: str, function: Callable[[ReviewState], dict[str, Any]]):
        def run(state: ReviewState) -> dict[str, Any]:
            base = {
                "type": "node_start",
                "node": name,
                "child_id": (state.get("current_fact") or {}).get("fact_id"),
                "attempt": state.get("retry_count", 0),
            }
            if trace is not None:
                trace(base)
            started = perf_counter()
            update = function(state) or {}
            merged = dict(state)
            merged.update(update)
            if trace is not None:
                trace({
                    **base,
                    "type": "node_finish",
                    "attempt": merged.get("retry_count", base["attempt"]),
                    "workflow_status": merged.get("workflow_status"),
                    "elapsed_ms": (perf_counter() - started) * 1000,
                    "summary": _trace_summary(name, merged),
                })
            return update
        return run

    def traced_router(name: str, function: Callable[[ReviewState], str]):
        def route(state: ReviewState) -> str:
            destination = function(state)
            reason = None
            if name == "grade_evidence":
                if destination == "rewrite_query":
                    reason = "evidence is insufficient or required needs are missing; retry budget remains"
                elif state.get("evidence_status") == "INSUFFICIENT" or state.get("missing_needs"):
                    reason = "retry budget exhausted; continue to verification with current evidence"
                else:
                    reason = "continue to verification"
            elif name == "risk_gate":
                decision = state.get("risk_decision") or {}
                reason = f"risk policy selected {decision.get('next_step')} ({decision.get('reason_codes', [])})"
            elif name == "compare":
                reason = "critic verdict conflicts with initial verdict" if destination == "human_review" else "critic agrees with initial verdict"
            elif name == "finalize_child":
                reason = "process next Child" if destination == "prepare_child" else "all Child items completed"
            if trace is not None:
                trace({
                    "type": "route",
                    "source": name,
                    "destination": destination,
                    "child_id": (state.get("current_fact") or {}).get("fact_id"),
                    "attempt": state.get("retry_count", 0),
                    "reason": reason,
                })
            return destination
        return route

    def plan_query(state: ReviewState) -> dict[str, Any]:
        planner = services.query_planner
        if hasattr(planner, "build_plan"):
            plan = planner.build_plan(
                state["current_fact"], state["current_parent"],
                state.get("company_info"), attempt=state["retry_count"],
            )
            queries = plan["requests"]
        else:
            queries = planner.plan(
                state["current_fact"], state["current_parent"],
                state.get("company_info"), state["retry_count"],
            )
            queries = [
                {
                    **query,
                    "need_id": query.get("need_id", f"N-{state['current_fact']['fact_id']}-{index}"),
                    "retrieval_profile": query.get(
                        "retrieval_profile",
                        "financial_table" if query.get("retrieval_type") == "table" else "atomic_text",
                    ),
                }
                for index, query in enumerate(queries, 1)
            ]
            plan = {
                "plan_id": f"RP-{state['current_fact']['fact_id']}-{state['retry_count']}",
                "claim_id": state["current_fact"]["fact_id"],
                "requests": queries,
                "attempt": state["retry_count"],
            }
        validate_retrieval_plan(plan)
        return {
            "retrieval_plan": plan,
            "evidence_requirements": list(plan.get("requests", [])),
            "current_queries": queries,
            "missing_needs": [],
            "workflow_status": "QUERY_PLANNED",
        }

    def retrieve(state: ReviewState) -> dict[str, Any]:
        # Evidence is cumulative across bounded rewrite rounds.  A targeted
        # second query supplements the first round; it must not erase a valid
        # hit merely because that hit was not requested again.
        evidence: list[dict[str, Any]] = list(state.get("current_evidence", []))
        seen: set[str] = {str(item.get("evidence_id")) for item in evidence}
        trace: list[dict[str, Any]] = list(state.get("retrieval_trace", []))
        for query in state["current_queries"]:
            query_hits: list[dict[str, Any]] = []
            for item in services.retriever.retrieve(query):
                query_hits.append(item)
                if item["evidence_id"] not in seen:
                    seen.add(item["evidence_id"])
                    item = dict(item)
                    item["query_ids"] = [query.get("query_id")]
                    evidence.append(item)
                else:
                    existing = next(candidate for candidate in evidence if candidate.get("evidence_id") == item["evidence_id"])
                    query_ids = list(existing.get("query_ids", []))
                    if query.get("query_id") not in query_ids:
                        query_ids.append(query.get("query_id"))
                    existing["query_ids"] = query_ids
            trace.append({
                "query_id": query.get("query_id"),
                "need_id": query.get("need_id"),
                "retrieval_profile": query.get("retrieval_profile"),
                "hit_count": len(query_hits),
                "evidence_ids": [item.get("evidence_id") for item in query_hits],
                "routes": sorted({
                    str(route_hit.get("route"))
                    for item in query_hits
                    for route_hit in (item.get("route_hits") or [{"route": item.get("route")}])
                    if route_hit.get("route")
                }),
                "candidates": [
                    {
                        "evidence_id": item.get("evidence_id"),
                        "route_hits": item.get("route_hits") or ([{"route": item.get("route"), "raw_score": item.get("retrieval_score")}] if item.get("route") else []),
                        "rrf_score": item.get("rrf_score"),
                        "rerank_score": item.get("rerank_score", item.get("score")),
                        "reranker_model": item.get("reranker_model"),
                        "source": item.get("source"),
                        "page": item.get("page"),
                    }
                    for item in query_hits
                ],
            })
        return {"current_evidence": evidence, "retrieval_trace": trace, "workflow_status": "RETRIEVED"}

    def grade_evidence(state: ReviewState) -> dict[str, Any]:
        assessments, status = services.grader.grade(state["current_fact"], state["current_evidence"])
        evidence_ids = {str(item.get("evidence_id")) for item in state.get("current_evidence", [])}
        hit_query_ids = {
            str(query_id)
            for item in state.get("current_evidence", [])
            for query_id in (item.get("query_ids") or [item.get("query_id")])
            if query_id
        }
        observation_requests = list((state.get("retrieval_plan") or {}).get("requests", [])) or list(state.get("evidence_requirements", []))
        current_requests = list(state.get("evidence_requirements", []))
        covered_needs = [
            str(request.get("need_id"))
            for request in observation_requests
            if request.get("need_id") and str(request.get("query_id")) in hit_query_ids
        ]
        all_missing_needs = [
            str(request.get("need_id"))
            for request in observation_requests
            if request.get("need_id") and str(request.get("query_id")) not in hit_query_ids
        ]
        missing_needs = [
            str(request.get("need_id"))
            for request in current_requests
            if request.get("need_id") and str(request.get("query_id")) not in hit_query_ids
        ]
        observation = {
            "covered_needs": covered_needs,
            "missing_needs": all_missing_needs,
            "new_usable_evidence_count": sum(1 for item in assessments if item.get("usable")),
            "evidence_ids": sorted(evidence_ids),
            "conflicts": [item["evidence_id"] for item in assessments if item.get("relation") == "CONTRADICTS"],
        }
        return {
            "current_assessments": assessments,
            "evidence_status": status,
            "evidence_observation": observation,
            "missing_needs": missing_needs,
            "workflow_status": "EVIDENCE_EVALUATED",
        }

    def route_after_grade(state: ReviewState) -> Literal["rewrite_query", "verify"]:
        if (
            (state.get("evidence_status") == "INSUFFICIENT" or state.get("missing_needs"))
            and state.get("retry_count", 0) < services.max_retry
        ):
            return "rewrite_query"
        return "verify"

    def missing_need_ids(state: ReviewState) -> list[str]:
        """Approximate uncovered needs from query-to-hit provenance.

        The grader remains the source of truth for evidence relations.  This
        helper only tells the planner which requests produced no hit so a
        rewrite cannot accidentally use the old hard-coded Child ID.
        """

        queries = state.get("current_queries", [])
        hit_query_ids = {str(item.get("query_id")) for item in state.get("current_evidence", []) if item.get("query_id")}
        missing = [str(query.get("need_id")) for query in queries if query.get("need_id") and str(query.get("query_id")) not in hit_query_ids]
        return missing or [str(query.get("need_id")) for query in queries if query.get("need_id")]

    def rewrite_query(state: ReviewState) -> dict[str, Any]:
        retry_count = state.get("retry_count", 0) + 1
        planner = services.query_planner
        if hasattr(planner, "build_plan"):
            plan = planner.build_plan(
                state["current_fact"], state["current_parent"],
                state.get("company_info"), attempt=retry_count,
                missing_needs=state.get("missing_needs") or missing_need_ids(state),
            )
            queries = plan["requests"]
        else:
            queries = planner.rewrite(
                state["current_fact"], state["current_parent"], state["current_queries"],
            )
            queries = [
                {
                    **query,
                    "need_id": query.get("need_id", f"N-{state['current_fact']['fact_id']}-{index}"),
                    "retrieval_profile": query.get(
                        "retrieval_profile",
                        "financial_table" if query.get("retrieval_type") == "table" else "atomic_text",
                    ),
                }
                for index, query in enumerate(queries, 1)
            ]
            plan = {
                "plan_id": f"RP-{state['current_fact']['fact_id']}-{retry_count}",
                "claim_id": state["current_fact"]["fact_id"],
                "requests": queries,
                "attempt": retry_count,
            }
        # Keep the complete audit plan while executing only newly requested
        # needs.  This lets the final result explain both the first plan and
        # the targeted rewrite without re-running already covered queries.
        previous_requirements = list(state.get("evidence_requirements", []))
        current_need_ids = {str(item.get("need_id")) for item in previous_requirements}
        plan["requests"] = previous_requirements + [
            item for item in plan.get("requests", []) if str(item.get("need_id")) not in current_need_ids
        ]
        validate_retrieval_plan(plan)
        return {
            "retry_count": retry_count,
            "retrieval_plan": plan,
            "evidence_requirements": list(queries),
            "current_queries": queries,
            "missing_needs": [],
            "workflow_status": "QUERY_REWRITTEN",
        }

    def verify(state: ReviewState) -> dict[str, Any]:
        result = services.verifier.verify(
            state["current_fact"],
            state["current_parent"],
            state["current_evidence"],
            state["current_assessments"],
            state["evidence_status"] or "INSUFFICIENT",
        )
        return {"verification_result": result, "initial_verdict": result, "workflow_status": "VERIFIED"}

    def numeric_check(state: ReviewState) -> dict[str, Any]:
        if services.numeric_validator is None:
            return {"numeric_checks": [], "workflow_status": "NUMERIC_CHECKED"}
        return {"numeric_checks": services.numeric_validator.validate(state["current_fact"], state["current_evidence"]), "workflow_status": "NUMERIC_CHECKED"}

    def rule_check(state: ReviewState) -> dict[str, Any]:
        if services.rule_engine is None:
            return {"rule_hits": [], "workflow_status": "RULES_CHECKED"}
        context = {
            "child": state["current_fact"], "parent": state["current_parent"],
            "assessments": state.get("current_assessments", []),
            "numeric_checks": state.get("numeric_checks", []),
            "risk_level": state["current_fact"].get("importance", "low"),
        }
        return {"rule_hits": services.rule_engine.evaluate(context), "workflow_status": "RULES_CHECKED"}

    def risk_gate(state: ReviewState) -> dict[str, Any]:
        initial = state.get("initial_verdict") or state.get("verification_result") or {}
        if services.risk_policy is None:
            decision = {"next_step": "finalize", "risk_level": "low", "reason_codes": []}
        else:
            decision = services.risk_policy.decide(
                child=state["current_fact"], initial_verdict=initial,
                rule_hits=state.get("rule_hits", []),
                has_counter_evidence=any(a.get("relation") == "CONTRADICTS" for a in state.get("current_assessments", [])),
            )
        return {"risk_decision": decision, "workflow_status": "RISK_GATED"}

    def route_after_risk(state: ReviewState) -> Literal["critic", "human_review", "finalize_child"]:
        decision = state.get("risk_decision") or {}
        if decision.get("next_step") == "human":
            return "human_review"
        if decision.get("next_step") == "critic" and services.critic_verifier is not None:
            return "critic"
        return "finalize_child"

    def critic(state: ReviewState) -> dict[str, Any]:
        # Only Child, Parent and external evidence are passed to the critic.
        result = services.critic_verifier.verify(
            state["current_fact"], state["current_parent"], state["current_evidence"],
            state.get("current_assessments", []), state.get("evidence_status") or "INSUFFICIENT",
        )
        return {"critic_verdict": result, "workflow_status": "CRITIC_VERIFIED"}

    def compare(state: ReviewState) -> dict[str, Any]:
        initial = state.get("initial_verdict") or {}
        critic_result = state.get("critic_verdict") or {}
        if initial.get("status") != critic_result.get("status"):
            return {"risk_decision": {"next_step": "human", "risk_level": "high", "reason_codes": ["critic_conflict"]}, "workflow_status": "CRITIC_CONFLICT"}
        return {"verification_result": initial, "workflow_status": "CRITIC_AGREED"}

    def route_after_compare(state: ReviewState) -> Literal["human_review", "finalize_child"]:
        return "human_review" if (state.get("risk_decision") or {}).get("next_step") == "human" else "finalize_child"

    def human_review(state: ReviewState) -> dict[str, Any]:
        child = state["current_fact"]
        task = {"task_id": f"HT-{child['fact_id']}", "task_version": 1, "fact_id": child["fact_id"], "status": "PENDING", "reason_codes": (state.get("risk_decision") or {}).get("reason_codes", [])}
        return {"human_task": task, "workflow_status": "HUMAN_REVIEW_REQUIRED"}

    def finalize_child(state: ReviewState) -> dict[str, Any]:
        return _finalize_child_state(state)

    def _finalize_child_state(state: ReviewState, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        result = dict(state["verification_result"] or {})
        child = state["current_fact"]
        parent = state["current_parent"]
        if decision is not None:
            result.update({
                "status": decision["decision"],
                "reason": decision.get("comment", "人工复核已提交。"),
                "confidence": "high",
                "human_decision": dict(decision),
            })
        result.update({
            "fact_id": child["fact_id"],
            "fact": child["fact"],
            "parent_id": parent["parent_id"],
            "parent_text": parent["parent_text"],
            "queries": list(state["current_queries"]),
            "retrieval_plan": state.get("retrieval_plan"),
            "evidence_requirements": list(state.get("evidence_requirements", [])),
            "evidence": list(state["current_evidence"]),
            "retrieval_trace": list(state.get("retrieval_trace", [])),
            "assessments": list(state["current_assessments"]),
            "evidence_observation": state.get("evidence_observation"),
            "missing_needs": list(state.get("missing_needs", [])),
            "retry_count": state.get("retry_count", 0),
            "numeric_checks": list(state.get("numeric_checks", [])),
            "rule_hits": list(state.get("rule_hits", [])),
            "critic_verdict": state.get("critic_verdict"),
            "risk_decision": state.get("risk_decision"),
        })
        completed = list(state.get("completed_results", []))
        completed.append(result)
        return {
            "completed_results": completed,
            "child_index": state["child_index"] + 1,
            "current_parent": {},
            "current_fact": {},
            "retrieval_plan": None,
            "evidence_requirements": [],
            "current_queries": [],
            "current_evidence": [],
            "retrieval_trace": [],
            "evidence_status": None,
            "evidence_observation": None,
            "missing_needs": [],
            "retry_count": 0,
            "current_assessments": [],
            "verification_result": None,
            "initial_verdict": None,
            "critic_verdict": None,
            "numeric_checks": [],
            "rule_hits": [],
            "risk_decision": None,
            "human_task": None,
            "workflow_status": "CHILD_COMPLETED",
        }

    def route_after_child(state: ReviewState) -> Literal["prepare_child", "aggregate"]:
        if state["child_index"] < len(state["flat_children"]):
            return "prepare_child"
        return "aggregate"

    def aggregate(state: ReviewState) -> dict[str, Any]:
        results = list(state.get("completed_results", []))
        counts: dict[str, int] = {}
        for item in results:
            status = item["status"]
            counts[status] = counts.get(status, 0) + 1
        return {
            "workflow_status": "COMPLETED",
            "review_result": {
                "status": "COMPLETED",
                "company_info": state.get("company_info"),
                "fact_groups": state["fact_groups"],
                "completed_results": results,
                "summary_counts": counts,
            },
        }

    graph = StateGraph(ReviewState)
    graph.add_node("extract_parent_child", traced_node("extract_parent_child", extract_parent_child))
    graph.add_node("resolve_company", traced_node("resolve_company", resolve_company))
    graph.add_node("prepare_child", traced_node("prepare_child", prepare_child))
    graph.add_node("plan_query", traced_node("plan_query", plan_query))
    graph.add_node("retrieve", traced_node("retrieve", retrieve))
    graph.add_node("grade_evidence", traced_node("grade_evidence", grade_evidence))
    graph.add_node("rewrite_query", traced_node("rewrite_query", rewrite_query))
    graph.add_node("verify", traced_node("verify", verify))
    graph.add_node("numeric_check", traced_node("numeric_check", numeric_check))
    graph.add_node("rule_check", traced_node("rule_check", rule_check))
    graph.add_node("risk_gate", traced_node("risk_gate", risk_gate))
    graph.add_node("critic", traced_node("critic", critic))
    graph.add_node("compare", traced_node("compare", compare))
    graph.add_node("human_review", traced_node("human_review", human_review))
    graph.add_node("finalize_child", traced_node("finalize_child", finalize_child))
    graph.add_node("aggregate", traced_node("aggregate", aggregate))

    graph.add_edge(START, "extract_parent_child")
    graph.add_edge("extract_parent_child", "resolve_company")
    graph.add_edge("resolve_company", "prepare_child")
    graph.add_edge("prepare_child", "plan_query")
    graph.add_edge("plan_query", "retrieve")
    graph.add_edge("retrieve", "grade_evidence")
    graph.add_conditional_edges("grade_evidence", traced_router("grade_evidence", route_after_grade))
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("verify", "numeric_check")
    graph.add_edge("numeric_check", "rule_check")
    graph.add_edge("rule_check", "risk_gate")
    graph.add_conditional_edges("risk_gate", traced_router("risk_gate", route_after_risk))
    graph.add_edge("critic", "compare")
    graph.add_conditional_edges("compare", traced_router("compare", route_after_compare))
    graph.add_edge("human_review", END)
    graph.add_conditional_edges("finalize_child", traced_router("finalize_child", route_after_child))
    graph.add_edge("aggregate", END)
    return graph.compile()


def resume_review(state: ReviewState, decision: dict[str, Any]) -> dict[str, Any]:
    """Apply an optimistic-lock human decision to a paused one-Child state.

    The function is intentionally independent from a checkpointer so it can be
    used by an API adapter or an in-memory test repository.
    """
    task = state.get("human_task") or {}
    if task.get("status") != "PENDING":
        raise ValueError("review has no pending human task")
    if decision.get("task_version") != task.get("task_version"):
        raise ValueError("stale human task version")
    if decision.get("decision") not in {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"}:
        raise ValueError("invalid human decision")
    result = dict(state.get("verification_result") or {})
    result.update({"status": decision["decision"], "reason": decision.get("comment", "人工复核已提交。"), "confidence": "high", "human_decision": dict(decision)})
    child, parent = state["current_fact"], state["current_parent"]
    result.update({"fact_id": child["fact_id"], "fact": child["fact"], "parent_id": parent["parent_id"], "parent_text": parent["parent_text"], "queries": list(state.get("current_queries", [])), "retrieval_plan": state.get("retrieval_plan"), "evidence_requirements": list(state.get("evidence_requirements", [])), "evidence": list(state.get("current_evidence", [])), "retrieval_trace": list(state.get("retrieval_trace", [])), "assessments": list(state.get("current_assessments", [])), "evidence_observation": state.get("evidence_observation"), "missing_needs": list(state.get("missing_needs", [])), "retry_count": state.get("retry_count", 0), "numeric_checks": list(state.get("numeric_checks", [])), "rule_hits": list(state.get("rule_hits", [])), "critic_verdict": state.get("critic_verdict"), "risk_decision": state.get("risk_decision")})
    completed = list(state.get("completed_results", [])) + [result]
    next_state = dict(state)
    next_state.update({"completed_results": completed, "child_index": state["child_index"] + 1, "human_task": {**task, "status": "RESOLVED", "decision": dict(decision)}, "current_parent": {}, "current_fact": {}, "retrieval_plan": None, "evidence_requirements": [], "current_queries": [], "current_evidence": [], "retrieval_trace": [], "evidence_status": None, "evidence_observation": None, "missing_needs": [], "retry_count": 0, "current_assessments": [], "verification_result": None, "initial_verdict": None, "critic_verdict": None, "numeric_checks": [], "rule_hits": [], "risk_decision": None, "workflow_status": "CHILD_COMPLETED"})
    if next_state["child_index"] < len(next_state.get("flat_children", [])):
        return next_state
    counts: dict[str, int] = {}
    for item in completed:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    next_state.update({"workflow_status": "COMPLETED", "review_result": {"status": "COMPLETED", "company_info": next_state.get("company_info"), "fact_groups": next_state["fact_groups"], "completed_results": completed, "summary_counts": counts}})
    return next_state


def run_review(
    original_input: str,
    evidence: list[Evidence | dict[str, Any]] | None = None,
    companies: dict[str, dict[str, str]] | None = None,
    source_scope: dict[str, Any] | None = None,
    *,
    retrieval_backend: str | None = None,
    retrieval_config: RetrievalConfig | None = None,
    index_dir: Path | str | None = None,
    trace: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the synchronous MVP and return its final graph state."""
    if not isinstance(original_input, str) or not original_input.strip():
        raise ValueError("original_input must be a non-empty string")
    app = build_review_graph(
        default_services(
            evidence=evidence,
            companies=companies,
            source_scope=source_scope,
            retrieval_backend=retrieval_backend,
            retrieval_config=retrieval_config,
            index_dir=index_dir,
        ),
        trace=trace,
    )
    return app.invoke({"original_input": original_input})


def run_review_with_deepseek(
    original_input: str,
    evidence: list[Evidence | dict[str, Any]] | None = None,
    companies: dict[str, dict[str, str]] | None = None,
    source_scope: dict[str, Any] | None = None,
    gateway: Any | None = None,
    *,
    retrieval_backend: str | None = None,
    retrieval_config: RetrievalConfig | None = None,
    index_dir: Path | str | None = None,
    trace: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not isinstance(original_input, str) or not original_input.strip():
        raise ValueError("original_input must be a non-empty string")
    return build_review_graph(
        deepseek_services(
            evidence=evidence,
            companies=companies,
            source_scope=source_scope,
            gateway=gateway,
            retrieval_backend=retrieval_backend,
            retrieval_config=retrieval_config,
            index_dir=index_dir,
        ),
        trace=trace,
    ).invoke({"original_input": original_input})
