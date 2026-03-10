from fagent.providers.openai_codex_provider import _extract_usage


def test_extract_usage_maps_responses_api_fields() -> None:
    usage = _extract_usage({"usage": {"input_tokens": 123, "output_tokens": 45, "total_tokens": 168}})

    assert usage == {
        "prompt_tokens": 123,
        "completion_tokens": 45,
        "total_tokens": 168,
    }

