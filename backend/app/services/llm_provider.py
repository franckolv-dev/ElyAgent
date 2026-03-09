from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from app.config import get_settings

settings = get_settings()


def get_llm() -> BaseChatModel:
    provider = settings.active_llm_provider
    model = settings.active_llm_model

    if provider == "anthropic":
        return ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
            temperature=0.7,
        )
    elif provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=0.7,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
