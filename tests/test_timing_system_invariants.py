"""Model checks use real operation signatures, not invented source types.

These tests do not substitute for semantic verification of source obligations.
The example's certificate workflow must discharge those separately.
"""

from copy import deepcopy

import pytest

from dagcert.induction import parse_induction_spec, prove_inductive_invariant
from examples.timing_systems.invariants import (
    invariant_rows,
    policy_relations,
    source_contract,
    source_obligations,
    task_definitions,
)


@pytest.mark.parametrize("index", range(5))
def test_five_real_policy_invariants_cover_the_compiler_extracted_outcome_unions(index: int) -> None:
    row = invariant_rows()[index]
    passed, diagnostic = prove_inductive_invariant(parse_induction_spec(row), source_contract())
    assert passed, diagnostic


def test_variable_av_reserve_admission_without_capacity_check_has_a_counterexample() -> None:
    row = deepcopy(invariant_rows()[0])
    row["transitions"][0]["relation"] = (
        "after.next_sequence == before.next_sequence + 1 "
        "and after.capacity_ms == before.capacity_ms and after.reserve_ms > before.reserve_ms"
    )
    passed, diagnostic = prove_inductive_invariant(parse_induction_spec(row), source_contract())
    assert not passed
    assert "AVJoined" in diagnostic


def test_variable_sized_chunks_cannot_be_falsely_claimed_to_have_one_byte_each() -> None:
    row = deepcopy(invariant_rows()[2])
    row["invariant"] = "0 <= state.durable_chunks and state.durable_chunks == state.durable_bytes"
    passed, diagnostic = prove_inductive_invariant(parse_induction_spec(row), source_contract())
    assert not passed
    assert "ChunkCommitted" in diagnostic


def test_search_cannot_claim_input_changes_instantaneously_update_visible_content() -> None:
    row = deepcopy(invariant_rows()[3])
    row["invariant"] = "0 <= state.current_generation and state.visible_generation == state.current_generation"
    passed, diagnostic = prove_inductive_invariant(parse_induction_spec(row), source_contract())
    assert not passed
    assert "SearchChanged" in diagnostic


def test_duplicate_window_reading_cannot_increment_unique_reading_count() -> None:
    row = deepcopy(invariant_rows()[4])
    duplicate = next(item for item in row["transitions"] if item["outcome"] == "WindowIgnored")
    duplicate["relation"] = "after.count == before.count + 1 and after.last_sequence == before.last_sequence"
    passed, diagnostic = prove_inductive_invariant(parse_induction_spec(row), source_contract())
    assert not passed
    assert "WindowIgnored" in diagnostic


def test_each_real_outcome_has_a_source_obligation_and_policies_are_additional() -> None:
    contract = source_contract()
    relations = source_obligations(contract)
    for task in contract.tasks:
        assert {relation.outcome_type for relation in relations if relation.task_id == task.id} == set(
            task.outcome_by_type,
        )
    assert len({relation.id for relation in relations}) == len(relations)
    assert len(relations) == sum(len(task.outcomes) for task in contract.tasks) + len(policy_relations())


def test_contract_task_outcomes_are_extracted_from_the_real_files() -> None:
    contract = source_contract()
    for row in task_definitions():
        task = contract.task_by_id[row["id"]]
        assert task.source_signature is not None
        assert {outcome["type"] for outcome in row["outcomes"]} == set(task.source_signature.outcome_types)


def test_no_outcome_may_be_dropped_to_make_a_stronger_invariant_pass() -> None:
    row = deepcopy(invariant_rows()[3])
    row["transitions"] = [item for item in row["transitions"] if item["outcome"] != "SearchStale"]
    passed, diagnostic = prove_inductive_invariant(parse_induction_spec(row), source_contract())
    assert not passed
    assert "SearchStale" in diagnostic
