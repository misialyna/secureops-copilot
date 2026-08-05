from langfuse.langchain import CallbackHandler

from app.config import Settings
from app.observability import get_langfuse_config, init_langfuse


def test_init_langfuse_is_a_noop_without_credentials() -> None:
    settings = Settings(langfuse_public_key="", langfuse_secret_key="")
    assert init_langfuse(settings) is False


def test_get_langfuse_config_is_empty_when_disabled() -> None:
    assert get_langfuse_config("thread-1", langfuse_enabled=False) == {}


def test_get_langfuse_config_carries_the_session_id_when_enabled() -> None:
    config = get_langfuse_config("thread-1", langfuse_enabled=True)

    assert config["metadata"] == {"langfuse_session_id": "thread-1"}
    assert len(config["callbacks"]) == 1
    assert isinstance(config["callbacks"][0], CallbackHandler)
