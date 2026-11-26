"""Unit tests for Majority Voting and Fast-Confirm consensus rules."""

from __future__ import annotations

import pytest

from src.backend.domain.models import VoteObservation
from src.backend.domain.voting import get_vote_result, is_vote_confirmed


def test_get_vote_result_and_standard_confirmation() -> None:
    assert get_vote_result([]) is None
    assert is_vote_confirmed(None) is False

    # 2 samples without confidence do not reach VOTE_MIN_SAMPLES (3)
    obs_short = [
        (1.0, "59V179379", "59V1-79379"),
        (1.2, "59V179379", "59V1-79379"),
    ]
    res_short = get_vote_result(obs_short)
    assert res_short is not None
    assert is_vote_confirmed(res_short) is False
    assert is_vote_confirmed(res_short, obs_short) is False

    # 4 samples with 3 matching (75% >= 70%) -> confirmed
    obs_valid = [
        (1.0, "59V179379", "59V1-79379"),
        (1.2, "59V179379", "59V1-79379"),
        (1.4, "59V179378", "59V1-79378"),
        (1.6, "59V179379", "59V1-79379"),
    ]
    res_valid = get_vote_result(obs_valid)
    assert res_valid is not None
    assert res_valid.plate_key == "59V179379"
    assert res_valid.plate_display == "59V1-79379"
    assert res_valid.vote_count == 3
    assert res_valid.sample_count == 4
    assert res_valid.vote_share == pytest.approx(0.75)
    assert is_vote_confirmed(res_valid) is True


def test_fast_confirm_two_high_confidence_samples() -> None:
    # 2 consecutive high-confidence samples (>= 0.75) -> Fast-Confirm on 2nd sample
    obs_fast = [
        (1.0, "59V179379", "59V1-79379", 0.86),
        (1.15, "59V179379", "59V1-79379", 0.89),
    ]
    res_fast = get_vote_result(obs_fast)
    assert is_vote_confirmed(res_fast, obs_fast) is True

    # Low char confidence (< 0.75) -> wait for 3rd sample
    obs_low_conf = [
        VoteObservation(1.0, "59V179379", "59V1-79379", 0.62),
        VoteObservation(1.15, "59V179379", "59V1-79379", 0.68),
    ]
    res_low = get_vote_result(obs_low_conf)
    assert is_vote_confirmed(res_low, obs_low_conf) is False

    # Conflicting plates -> never fast-confirm
    obs_conflict = [
        VoteObservation(1.0, "59V179379", "59V1-79379", 0.92),
        VoteObservation(1.15, "59V179378", "59V1-79378", 0.92),
    ]
    res_conflict = get_vote_result(obs_conflict)
    assert is_vote_confirmed(res_conflict, obs_conflict) is False
