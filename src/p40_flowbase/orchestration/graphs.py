"""
MIT License

Copyright (c) 2025 Anton Tarasenko

LangGraph-based orchestration for parallel recursive task execution.

Each "lane" progresses through sequential steps independently, while all lanes
run in parallel. LangGraph's Send API fans out one subgraph per lane, and
each lane subgraph loops through its steps sequentially.
"""

import operator
import uuid
from collections.abc import Awaitable, Callable
from typing import (
    Annotated,
    Any,
    TypedDict,
)

from langgraph.constants import (
    END,
    START,
)
from langgraph.graph import StateGraph
from langgraph.types import Send

from p40_flowbase.logging import logger


class StepResult(TypedDict):
    lane_id: str
    step_index: int
    results: list[Any]


class LaneState(TypedDict, total=False):
    """State for a single lane subgraph."""

    lane_id: str
    step_index: int
    num_steps: int
    max_retries: int
    previous_step_results: list[Any]
    all_step_results: list[StepResult]


class OverallState(TypedDict, total=False):
    """State for the main fan-out/collect graph.

    :ivar lanes: List of lane identifiers.
    :ivar num_steps: Number of steps per lane.
    :ivar max_retries: Maximum retry attempts per step.
    :ivar lane_results: Flat list of per-lane result dicts, collected
        from all lanes. Uses ``operator.add`` reducer so concurrent
        ``Send`` outputs are concatenated.
    :ivar organized_results: Final organized results (set by the
        ``collect_results`` node).
    """

    lanes: list[str]
    num_steps: int
    max_retries: int
    lane_results: Annotated[list[StepResult], operator.add]
    organized_results: dict[str, list[list[Any]]]


PopulateStep = Callable[[str, int, list[Any]], Awaitable[uuid.UUID | None]]
ExecutePending = Callable[[str], Awaitable[list[Any]]]
RetryFailed = Callable[[str], Awaitable[list[Any]]]
GetWaveResults = Callable[[uuid.UUID], Awaitable[list[Any]]]


def build_recursive_task_graph(
    populate_step: PopulateStep,
    execute_pending: ExecutePending,
    retry_failed: RetryFailed,
    get_wave_results: GetWaveResults,
    checkpointer: Any | None = None,
) -> Any:
    """Build a LangGraph graph for parallel-lane, sequential-step execution.

    :param populate_step: Async callback
        ``(lane_id, step_index, prev_results) -> Optional[UUID]``.
        Creates tasks/requests for one lane-step. Returns group UUID
        or ``None`` to skip.
    :param execute_pending: Async callback ``(group_id_str) -> list``.
        Executes pending items in the given group.
    :param retry_failed: Async callback ``(group_id_str) -> list``.
        Retries failed items in the given group.
    :param get_wave_results: Async callback ``(group_id) -> list``.
        Returns the final (non-superseded) results for the given group.
    :param checkpointer: Optional LangGraph checkpointer for resumability.
    :returns: Compiled LangGraph graph ready to invoke.
    """

    # Lane subgraph

    async def process_step(state: dict[str, Any]) -> dict[str, Any]:
        """Execute populate + execute + retry for one lane-step.

        Returns the full state dict (not partial) because StateGraph(dict)
        replaces state on node output rather than merging.
        """
        lane_id: str = state["lane_id"]
        step_index: int = state["step_index"]
        previous_step_results: list[Any] = state.get("previous_step_results", [])
        max_retries: int = state.get("max_retries", 1)

        logger.info(
            f"Lane '{lane_id}': processing step {step_index}"
        )

        group_id = await populate_step(
            lane_id, step_index, previous_step_results
        )

        if group_id is None:
            logger.info(
                f"Lane '{lane_id}': step {step_index} skipped (populate returned None)"
            )
            return {
                **state,
                "step_index": step_index + 1,
                "previous_step_results": [],
                "all_step_results": state.get("all_step_results", []) + [
                    {"lane_id": lane_id, "step_index": step_index, "results": []},
                ],
            }

        group_id_str = str(group_id)

        await execute_pending(group_id_str)

        for retry_attempt in range(max_retries):
            results = await get_wave_results(group_id)
            has_failures = _check_for_failures(results)
            if not has_failures:
                break
            logger.info(
                f"Lane '{lane_id}': step {step_index}, "
                f"retry {retry_attempt + 1}/{max_retries}"
            )
            await retry_failed(group_id_str)

        results = await get_wave_results(group_id)

        logger.info(
            f"Lane '{lane_id}': step {step_index} completed "
            f"with {len(results)} results"
        )

        return {
            **state,
            "step_index": step_index + 1,
            "previous_step_results": results,
            "all_step_results": state.get("all_step_results", []) + [
                {"lane_id": lane_id, "step_index": step_index, "results": results},
            ],
        }

    def should_continue(state: dict[str, Any]) -> str:
        """Decide whether to continue looping or end the lane."""
        if state["step_index"] < state["num_steps"]:
            return "process_step"
        result: str = END
        return result

    # Plain ``dict`` schema (not a TypedDict) is intentional: nodes replace
    # the whole state instead of per-channel merging. See ``process_step``.
    lane_graph: Any = StateGraph(dict)  # pyright: ignore[reportArgumentType]
    lane_graph.add_node("process_step", process_step)
    lane_graph.add_conditional_edges(START, should_continue)
    lane_graph.add_conditional_edges("process_step", should_continue)
    compiled_lane = lane_graph.compile()

    # Main graph

    def fan_out_lanes(state: dict[str, Any]) -> list[Send]:
        """Create a Send per lane for parallel execution."""
        return [
            Send(
                "lane_processor",
                {
                    "lane_id": lane_id,
                    "step_index": 0,
                    "num_steps": state["num_steps"],
                    "max_retries": state.get("max_retries", 1),
                    "previous_step_results": [],
                    "all_step_results": [],
                },
            )
            for lane_id in state["lanes"]
        ]

    def collect_results(state: dict[str, Any]) -> dict[str, Any]:
        """Reorganize flat lane_results into per-lane dict."""
        organized: dict[str, list[list[Any]]] = {}
        for entry in state.get("lane_results", []):
            lane_id = entry["lane_id"]
            step_index = entry["step_index"]
            results = entry["results"]
            if lane_id not in organized:
                organized[lane_id] = []
            while len(organized[lane_id]) <= step_index:
                organized[lane_id].append([])
            organized[lane_id][step_index] = results
        return {"organized_results": organized}

    async def lane_processor(state: dict[str, Any]) -> dict[str, Any]:
        """Run lane subgraph and return results for aggregation."""
        result = await compiled_lane.ainvoke(state)
        return {"lane_results": result.get("all_step_results", [])}

    main_graph: Any = StateGraph(OverallState)
    main_graph.add_node("lane_processor", lane_processor)
    main_graph.add_node("collect_results", collect_results)
    main_graph.add_conditional_edges(START, fan_out_lanes)
    main_graph.add_edge("lane_processor", "collect_results")
    main_graph.add_edge("collect_results", END)

    return main_graph.compile(checkpointer=checkpointer)


def _check_for_failures(results: list[Any]) -> bool:
    """Check if any results indicate failure.

    Inspects common failure indicators across HTTP, LLM, and Agent result types.
    """
    for result in results:
        if hasattr(result, "response_status") and result.response_status != 200:
            return True
        if (
            hasattr(result, "response_text")
            and result.response_text is None
            and hasattr(result, "requested_at_utc")
            and result.requested_at_utc is not None
        ):
            return True
        if hasattr(result, "is_error") and result.is_error:
            return True
    return False
