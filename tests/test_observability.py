import pytest

from infergate.observability import RequestObservation


def test_fallback_counts_two_attempts_but_finishes_one_request():
    observation = RequestObservation(started_at=10.0)
    observation.start_attempt()
    observation.start_attempt()

    assert observation.finish("completed", 12.0) is True
    assert observation.attempt == 2
    assert observation.outcome == "completed"
    assert observation.total_time == 2.0
    assert observation.is_finish is True
    assert observation.first_byte_sec is None


def test_cleanup_error_cannot_overwrite_cancellation_or_finish_twice():
    observation = RequestObservation(10.0)
    observation.start_attempt()
    assert observation.finish("cancelled", 12.0) is True

    assert observation.finish("internal_error", 13.0) is False
    observation.start_attempt()
    observation.record_first_byte(14.0)

    assert observation.outcome == "cancelled"
    assert observation.total_time == 2.0
    assert observation.attempt == 1
    assert observation.first_byte_sec is None


@pytest.mark.parametrize("first_byte_at", [10.0, 10.5])
def test_first_byte_is_recorded_once_including_zero_duration(first_byte_at):
    observation = RequestObservation(10.0)
    observation.start_attempt()
    observation.record_first_byte(first_byte_at)
    observation.record_first_byte(11.0)
    assert observation.first_byte_sec == first_byte_at - 10.0

    assert observation.finish("stream_error", 12.0) is True
    observation.record_first_byte(13.0)
    assert observation.first_byte_sec == first_byte_at - 10.0
    assert observation.outcome == "stream_error"


def test_rejected_request_has_no_attempt_or_first_byte():
    observation = RequestObservation(10.0)
    assert observation.finish("rejected", 10.0) is True
    assert observation.attempt == 0
    assert observation.first_byte_sec is None
    assert observation.total_time == 0.0


def test_requests_keep_independent_observation_state():
    cancelled = RequestObservation(10.0)
    ongoing = RequestObservation(20.0)
    cancelled.start_attempt()
    cancelled.finish("cancelled", 12.0)

    assert ongoing.attempt == 0
    assert ongoing.outcome is None
    assert ongoing.total_time is None
    assert ongoing.first_byte_sec is None
    assert ongoing.is_finish is False
    ongoing.start_attempt()
    ongoing.record_first_byte(20.5)
    assert ongoing.finish("completed", 21.0) is True
    assert ongoing.attempt == 1
    assert ongoing.first_byte_sec == 0.5
    assert ongoing.total_time == 1.0
    assert cancelled.outcome == "cancelled"
    assert cancelled.total_time == 2.0
