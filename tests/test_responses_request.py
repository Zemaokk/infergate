import pytest
from pydantic import ValidationError

from infergate.app import ChatCompletionRequest, ResponsesRequest


BASE = {"model": "responses-model", "input": "hello", "store": False}


def test_minimal_request_preserves_omitted_fields():
    request = ResponsesRequest.model_validate(BASE)
    assert request.stream is False
    assert request.background is False
    assert request.model_dump(exclude_unset=True) == BASE


def test_explicit_fields_and_multiline_text_are_preserved():
    payload = {
        **BASE,
        "input": "\n  hello\nworld  \n",
        "instructions": "",
        "max_output_tokens": 16,
        "stream": False,
        "background": False,
    }
    assert ResponsesRequest.model_validate(payload).model_dump(exclude_unset=True) == payload


@pytest.mark.parametrize("field", ["instructions", "max_output_tokens"])
def test_optional_null_is_preserved(field):
    payload = {**BASE, field: None}
    assert ResponsesRequest.model_validate(payload).model_dump(exclude_unset=True) == payload


@pytest.mark.parametrize("field", ["model", "input", "store"])
def test_required_fields_cannot_be_omitted(field):
    with pytest.raises(ValidationError) as exc:
        ResponsesRequest.model_validate({key: value for key, value in BASE.items() if key != field})
    assert exc.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["model", "input"])
@pytest.mark.parametrize("value", [None, "", " \t\n", 3, False, []])
def test_required_text_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError) as exc:
        ResponsesRequest.model_validate({**BASE, field: value})
    assert exc.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["store", "stream", "background"])
@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_false_only_flags_reject_coercion_and_unsupported_values(field, value):
    with pytest.raises(ValidationError) as exc:
        ResponsesRequest.model_validate({**BASE, field: value})
    assert exc.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("value", [True, False, 15, 16.0, "16"])
def test_token_limit_requires_integer_at_least_sixteen(value):
    with pytest.raises(ValidationError) as exc:
        ResponsesRequest.model_validate({**BASE, "max_output_tokens": value})
    assert exc.value.errors()[0]["loc"] == ("max_output_tokens",)


@pytest.mark.parametrize("value", [0, False, []])
def test_instructions_requires_string_or_null(value):
    with pytest.raises(ValidationError):
        ResponsesRequest.model_validate({**BASE, "instructions": value})


@pytest.mark.parametrize("field,value", [("tools", []), ("previous_response_id", "resp_1"), ("temperature", None)])
def test_unknown_fields_are_rejected(field, value):
    with pytest.raises(ValidationError) as exc:
        ResponsesRequest.model_validate({**BASE, field: value})
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


def test_schema_keeps_required_fields_and_false_only_flags():
    schema = ResponsesRequest.model_json_schema()
    assert set(schema["required"]) == {"model", "input", "store"}
    assert schema["additionalProperties"] is False
    for field in ("store", "stream", "background"):
        assert schema["properties"][field]["type"] == "boolean"
        assert schema["properties"][field]["const"] is False


def test_chat_validation_and_extra_field_passthrough_are_unchanged():
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": None,
    }
    assert ChatCompletionRequest.model_validate(payload).model_dump(exclude_unset=True) == payload
    for value in (None, 0, "false"):
        with pytest.raises(ValidationError):
            ChatCompletionRequest.model_validate({**payload, "stream": value})
