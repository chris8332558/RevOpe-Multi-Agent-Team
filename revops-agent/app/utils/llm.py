"""
LiteLLM configuration — single source of truth for all agents.

Supports:
  - Google Gemini  (set LLM_MODEL=gemini/gemini-2.0-flash)
  - Local vLLM     (set LLM_MODEL=openai/<your-model>,
                        VLLM_API_BASE=http://localhost:8000)

All agents call get_model_id() to retrieve the active model string.
LiteLLM routes the request to the correct provider automatically.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def get_model_id() -> str:
    """Return the active LiteLLM model string from environment."""
    return os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash")


def get_api_base() -> str | None:
    """
    Return the API base URL if using a local vLLM endpoint.
    Returns None for cloud providers (Gemini, OpenAI, Anthropic).
    """
    return os.getenv("VLLM_API_BASE", None)


def is_local_model() -> bool:
    """True when routing to a local vLLM-compatible endpoint."""
    return get_api_base() is not None
