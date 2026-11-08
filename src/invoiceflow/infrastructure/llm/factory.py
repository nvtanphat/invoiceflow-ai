from invoiceflow.config import Settings
from invoiceflow.infrastructure.llm.gemini_adapter import GeminiAdapter
from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter
from invoiceflow.infrastructure.llm.provider import LLMProviderPort


def get_llm_adapter(settings: Settings) -> LLMProviderPort:
    if settings.LLM_PROVIDER == "openai":
        return OpenAIAdapter(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            model_id=settings.OPENAI_MODEL_ID,
        )
    return GeminiAdapter(
        api_key=settings.GEMINI_API_KEY,
        model_id=settings.GEMINI_MODEL_ID,
    )
