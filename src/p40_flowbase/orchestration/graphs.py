"""
MIT License

Copyright (c) 2025 Anton Tarasenko

LangGraph-based orchestration for parallel recursive task execution.

Each "lane" progresses through sequential steps independently, while all lanes
run in parallel. LangGraph's Send API fans out one subgraph per lane, and
each lane subgraph loops through its steps sequentially.
"""

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
)

from langgraph.constants import (
    END,
    START,
)
from langgraph.graph import StateGraph
from langgraph.types import Send

from p40_flowbase.logging import logger


class LaneState(dict):
    """State for a single lane subgraph.

    Attributes:
        lane_id: Identifier for this lane.
        step_index: Current step (0-based).
        num_steps: Total number of steps to process.
        max_retries: Maximum retry attempts per step.
        previous_step_results: Results from the previous step.
        all_step_results: Accumulated results from all completed steps.
    """

    @property
    def lane_id(self) -> str:
        return self["lane_id"]

    @property
    def step_index(self) -> int:
        return self["step_index"]

    @property
    def num_steps(self) -> int:
        return self["num_steps"]

    @property
    def max_retries(self) -> int:
        return self["max_retries"]

    @property
    def previous_step_results(self) -> list:
        return self.get("previous_step_results", [])

    @property
    def all_step_results(self) -> list:
        return self.get("all_step_results", [])


class OverallState(dict):
    """State for the main fan-out/collect graph.

    Attributes:
        lanes: List of lane identifiers.
        num_steps: Number of steps per lane.
        max_retries: Maximum retry attempts per step.
        lane_results: Flat list of per-lane result dicts, collected from all lanes.
    """

    @property
    def lanes(self) -> List[str]:
        return self["lanes"]

    @property
    def num_steps(self) -> int:
        return self["num_steps"]

    @property
    def max_retries(self) -> int:
        return self["max_retries"]

    @property
    def lane_results(self) -> list:
        return self.get("lane_results", [])


def build_recursive_task_graph(
    populate_step: Callable,
    execute_pending: Callable,
    retry_failed: Callable,
    get_wave_results: Callable,
    checkpointer: Optional[Any] = None,
):
    """Build a LangGraph graph for parallel-lane, sequential-step execution.

    Args:
        populate_step: Async callback ``(lane_id, step_index, prev_results) -> Optional[UUID]``.
            Creates tasks/requests for one lane-step. Returns group UUID or None to skip.
        execute_pending: Async callback ``(group_id_str) -> list``.
            Executes pending items in the given group.
        retry_failed: Async callback ``(group_id_str) -> list``.
            Retries failed items in the given group.
        get_wave_results: Async callback ``(group_id) -> list``.
            Returns the final (non-superseded) results for the given group.
        checkpointer: Optional LangGraph checkpointer for resumability.

    Returns:
        Compiled LangGraph graph ready to invoke.
    """

    # --- Lane subgraph ---

    async def process_step(state: dict) -> dict:
        """Execute populate + execute + retry for one lane-step.

        Returns the full state dict (not partial) because StateGraph(dict)
        replaces state on node output rather than merging.
        """
        lane_id = state["lane_id"]
        step_index = state["step_index"]
        num_steps = state["num_steps"]
        previous_step_results = state.get("previous_step_results", [])
        max_retries = state.get("max_retries", 1)

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

    def should_continue(state: dict) -> str:
        """Decide whether to continue looping or end the lane."""
        if state["step_index"] < state["num_steps"]:
            return "process_step"
        return END

    lane_graph = StateGraph(dict)
    lane_graph.add_node("process_step", process_step)
    lane_graph.add_conditional_edges(START, should_continue)
    lane_graph.add_conditional_edges("process_step", should_continue)
    compiled_lane = lane_graph.compile()

    # --- Main graph ---

    def fan_out_lanes(state: dict) -> list:
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

    def collect_results(state: dict) -> dict:
        """Reorganize flat lane_results into per-lane dict."""
        organized: Dict[str, List[list]] = {}
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

    # Wrapper node that runs the lane subgraph and extracts results
    # for the parent's lane_results reducer
    async def lane_processor(state: dict) -> dict:
        """Run lane subgraph and return results for aggregation."""
        result = await compiled_lane.ainvoke(state)
        return {"lane_results": result.get("all_step_results", [])}

    main_graph = StateGraph(dict)
    main_graph.add_node("lane_processor", lane_processor)
    main_graph.add_node("collect_results", collect_results)
    main_graph.add_conditional_edges(START, fan_out_lanes)
    main_graph.add_edge("lane_processor", "collect_results")
    main_graph.add_edge("collect_results", END)

    return main_graph.compile(checkpointer=checkpointer)


def _check_for_failures(results: list) -> bool:
    """Check if any results indicate failure.

    Inspects common failure indicators across HTTP, LLM, and Agent result types.
    """
    for result in results:
        if hasattr(result, "response_status") and result.response_status != 200:
            return True
        if hasattr(result, "response_text") and result.response_text is None:
            if hasattr(result, "requested_at_utc") and result.requested_at_utc is not None:
                return True
        if hasattr(result, "is_error") and result.is_error:
            return True
    return False
