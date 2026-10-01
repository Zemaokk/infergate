import pytest

from infergate.observability import RequestObservation


def test_candidate_result_can_change_without_finishing_request():
    observation = RequestObservation(10.0)
    observation.make_result("rejected", "no_backend_available")
    observation.make_result("completed")
    assert observation.pending_outcome == "completed"
    assert observation.pending_reason is None
    assert observation.is_finished is False
    assert observation.outcome is None
    assert observation.total_time is None


def test_candidate_updates_cannot_change_finished_record():
    observation = RequestObservation(10.0)
    observation.make_result("completed")
    observation.record_failure("cancelled")
    observation.finish(12.0)
    observation.make_result("internal_error", "cleanup_failure")
    assert observation.pending_outcome == "completed"
    assert observation.pending_reason is None
    assert observation.outcome == "cancelled"
    assert observation.total_time == 2.0


def test_fallback_counts_two_attempts_but_finishes_one_request():
    observation = RequestObservation(started_at=10.0)
    observation.start_attempt()
    observation.start_attempt()
    observation.make_result("completed")
    observation.response_complete = True

    assert observation.finish(12.0) is True
    assert observation.attempt == 2
    assert observation.outcome == "completed"
    assert observation.total_time == 2.0
    assert observation.is_finished is True
    assert observation.first_byte_sec is None


def test_cleanup_error_cannot_overwrite_cancellation_or_finish_twice():
    observation = RequestObservation(10.0)
    observation.start_attempt()
    observation.record_failure("cancelled")
    assert observation.finish(12.0) is True

    observation.record_failure("internal_error")
    assert observation.finish(13.0) is False
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

    observation.record_failure("stream_error")
    assert observation.finish(12.0) is True
    observation.record_first_byte(13.0)
    assert observation.first_byte_sec == first_byte_at - 10.0
    assert observation.outcome == "stream_error"


def test_rejected_request_has_no_attempt_or_first_byte():
    observation = RequestObservation(10.0)
    observation.make_result("rejected")
    observation.response_complete = True
    assert observation.finish(10.0) is True
    assert observation.is_finished is True
    assert observation.finish(11.0) is False
    assert observation.attempt == 0
    assert observation.first_byte_sec is None
    assert observation.total_time == 0.0


def test_requests_keep_independent_observation_state():
    cancelled = RequestObservation(10.0)
    ongoing = RequestObservation(20.0)
    cancelled.start_attempt()
    cancelled.record_failure("cancelled")
    cancelled.finish(12.0)

    assert ongoing.attempt == 0
    assert ongoing.outcome is None
    assert ongoing.total_time is None
    assert ongoing.first_byte_sec is None
    assert ongoing.is_finished is False
    ongoing.start_attempt()
    ongoing.record_first_byte(20.5)
    ongoing.make_result("completed")
    ongoing.response_complete = True
    assert ongoing.finish(21.0) is True
    assert ongoing.attempt == 1
    assert ongoing.first_byte_sec == 0.5
    assert ongoing.total_time == 1.0
    assert cancelled.outcome == "cancelled"
    assert cancelled.total_time == 2.0


@pytest.mark.parametrize(
    "pending, reason, failure, body_complete, expected, final_reason",
    [
        ("completed", None, None, True, "completed", None),
        ("rejected", "rate_limit_exceeded", None, True, "rejected", "rate_limit_exceeded"),
        ("completed", None, "stream_error", True, "stream_error", None),
        ("rejected", "rate_limit_exceeded", "cancelled", False, "cancelled", None),
        ("completed", None, None, False, "internal_error", None),
        (None, None, None, True, "internal_error", None),
    ],
)
def test_finish_resolves_result_from_observed_state(
    pending, reason, failure, body_complete, expected, final_reason
):
    observation = RequestObservation(10.0)
    if pending is not None:
        observation.make_result(pending, reason)
    if failure is not None:
        observation.record_failure(failure)
    observation.response_complete = body_complete
    assert observation.finish(12.0) is True
    assert observation.outcome == expected
    assert observation.reason == final_reason
    assert observation.total_time == 2.0


def test_finished_property_has_no_independent_boolean_storage():
    observation = RequestObservation(10.0)
    assert observation.is_finished is False
    assert "is_finished" not in vars(observation)
    assert "is_finish" not in vars(observation)
    with pytest.raises(AttributeError):
        observation.is_finished = True
