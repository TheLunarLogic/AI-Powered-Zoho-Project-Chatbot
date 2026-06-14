import logging

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_config

logger = logging.getLogger(__name__)


def get_llm() -> BaseChatModel:
    """Return the configured LLM.

    Reads from Config (backed by pydantic-settings) so that .env values
    always win over stale OS-level environment variables.

    Supported providers: bedrock (default), gemini
    """
    config = get_config()
    provider = config.llm_provider.lower()
    logger.info("LLM provider: %s", provider)

    if provider == "bedrock":
        from langchain_aws import ChatBedrockConverse

        logger.info("Loading Bedrock model: %s (region=%s)", config.bedrock_model_id, config.aws_region)
        logger.warning(
        "ACTIVE MODEL => provider=%s model=%s",
        config.llm_provider,
        config.bedrock_model_id,
        )
        kwargs: dict = {
            "model": config.bedrock_model_id,
            "region_name": config.aws_region,
        }
        if config.aws_access_key_id:
            kwargs["aws_access_key_id"] = config.aws_access_key_id
        if config.aws_secret_access_key:
            kwargs["aws_secret_access_key"] = config.aws_secret_access_key
        if config.aws_session_token:
            kwargs["aws_session_token"] = config.aws_session_token
        return ChatBedrockConverse(**kwargs)

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        logger.info("Loading Gemini model: %s", config.gemini_model_id)
        return ChatGoogleGenerativeAI(
            model=config.gemini_model_id,
            google_api_key=config.google_api_key,
        )

    else:
        raise ValueError(f"Unknown LLM_PROVIDER: '{provider}'. Use 'bedrock' or 'gemini'.")
