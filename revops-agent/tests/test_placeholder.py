"""Smoke tests — verify core imports and environment config are functional."""


def test_imports():
    import agno
    import litellm
    import pydantic
    from app.utils.llm import get_model_id, get_api_base, is_local_model
    assert get_model_id() is not None
