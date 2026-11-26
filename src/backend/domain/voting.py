"""Majority voting and Fast-Confirm rules for license plate consensus."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from src.backend.domain.models import VoteObservation, VoteResult

VoteTuple = tuple[float, str, str] | tuple[float, str, str, float]
ObservationItem = VoteObservation | VoteTuple


def _unpack_observation(item: ObservationItem) -> tuple[str, str, float | None]:
    if isinstance(item, VoteObservation):
        return item.plate_key, item.plate_display, item.char_confidence
    conf = float(item[3]) if len(item) >= 4 else None
    return item[1], item[2], conf


def get_vote_result(observations: Sequence[ObservationItem]) -> VoteResult | None:
    """Aggregate plate observations into the leading VoteResult, or None if empty."""
    if not observations:
        return None
    unpacked = [_unpack_observation(item) for item in observations]
    votes = Counter(key for key, _, _ in unpacked)
    key, vote_count = votes.most_common(1)[0]
    display = Counter(disp for k, disp, _ in unpacked if k == key).most_common(1)[0][0]
    total = len(unpacked)
    return VoteResult(
        plate_key=key,
        plate_display=display,
        vote_count=vote_count,
        vote_share=vote_count / total,
        sample_count=total,
    )


def is_vote_confirmed(
    vote_result: VoteResult | None,
    observations: Sequence[ObservationItem] | None = None,
    *,
    min_samples: int = 3,
    min_share: float = 0.70,
    fast_min_samples: int = 2,
    fast_min_char_conf: float = 0.75,
) -> bool:
    """Return True when standard majority or high-confidence Fast-Confirm is met."""
    if vote_result is None:
        return False
    if vote_result.sample_count >= min_samples and vote_result.vote_share >= min_share:
        return True
    if (
        observations is not None
        and len(observations) >= fast_min_samples
        and vote_result.vote_share >= min_share
    ):
        tail = list(observations)[-fast_min_samples:]
        for item in tail:
            key, _, conf = _unpack_observation(item)
            if key != vote_result.plate_key or conf is None or conf < fast_min_char_conf:
                return False
        return True
    return False
