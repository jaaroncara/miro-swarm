"""Helpers for using CLI-backed LLMs inside OASIS/CAMEL simulations."""

import asyncio
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from camel.models import ModelFactory
from camel.models.openai_model import OpenAIModel
from camel.types import ModelPlatformType
from openai.types.chat.chat_completion import ChatCompletion

from ..config import Config
from .llm_client import LLMClient
from .logger import get_logger

logger = get_logger('mirofish.oasis_llm')

CLI_PROVIDERS = {'claude-cli', 'codex-cli'}
DEFAULT_API_SEMAPHORE = 30
DEFAULT_CLI_SEMAPHORE = 3


@dataclass
class ResolvedLLMConfig:
    """Resolved LLM settings for simulation-time use."""

    provider: str
    api_key: str
    base_url: str
    model: str
    label: str
    is_cli: bool = False


def _detect_provider(model: str, base_url: str) -> str:
    model_lower = (model or '').lower()
    base_lower = (base_url or '').lower()

    if any(keyword in model_lower for keyword in ('claude', 'anthropic')):
        return 'anthropic'
    if 'anthropic' in base_lower:
        return 'anthropic'
    return 'openai'


def resolve_oasis_llm_config(config: Dict[str, Any], use_boost: bool = False) -> ResolvedLLMConfig:
    """Resolve the LLM configuration used by OASIS simulation scripts."""

    standard_provider = (
        os.environ.get('LLM_PROVIDER')
        or config.get('llm_provider')
        or Config.LLM_PROVIDER
        or ''
    ).lower()
    standard_api_key = (
        os.environ.get('LLM_API_KEY')
        or Config.LLM_API_KEY
        or os.environ.get('OPENAI_API_KEY')
        or os.environ.get('ANTHROPIC_API_KEY')
        or ''
    )
    standard_base_url = os.environ.get('LLM_BASE_URL') or Config.LLM_BASE_URL or ''
    standard_model = (
        os.environ.get('LLM_MODEL_NAME')
        or config.get('llm_model')
        or Config.LLM_MODEL_NAME
        or 'gpt-4o-mini'
    )

    boost_provider = (
        os.environ.get('LLM_BOOST_PROVIDER')
        or config.get('llm_boost_provider')
        or standard_provider
        or ''
    ).lower()
    boost_api_key = os.environ.get('LLM_BOOST_API_KEY', '')
    boost_base_url = os.environ.get('LLM_BOOST_BASE_URL', '')
    boost_model = os.environ.get('LLM_BOOST_MODEL_NAME', '') or standard_model
    has_boost_config = bool(boost_api_key or boost_base_url or os.environ.get('LLM_BOOST_MODEL_NAME'))

    if use_boost and has_boost_config:
        provider = boost_provider or _detect_provider(boost_model, boost_base_url)
        return ResolvedLLMConfig(
            provider=provider,
            api_key=boost_api_key,
            base_url=boost_base_url,
            model=boost_model,
            label='[Boost LLM]',
            is_cli=provider in CLI_PROVIDERS,
        )

    provider = standard_provider or _detect_provider(standard_model, standard_base_url)
    return ResolvedLLMConfig(
        provider=provider,
        api_key=standard_api_key,
        base_url=standard_base_url,
        model=standard_model,
        label='[Standard LLM]',
        is_cli=provider in CLI_PROVIDERS,
    )


class CLIModel(OpenAIModel):
    """CAMEL model backend that proxies requests to Claude/Codex CLI."""

    def __init__(
        self,
        model_type: str,
        provider: str,
        model_config_dict: Dict[str, Any] | None = None,
        api_key: str | None = None,
        url: str | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
    ) -> None:
        self.provider = (provider or '').lower()
        self._llm = LLMClient(
            api_key=api_key,
            base_url=url,
            model=model_type,
            provider=self.provider,
        )
        super().__init__(
            model_type=model_type,
            model_config_dict=model_config_dict,
            api_key=api_key or 'cli-bridge',
            url=url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _estimate_tokens(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return max(1, math.ceil(len(value) / 4)) if value else 0
        if isinstance(value, list):
            return sum(self._estimate_tokens(item) for item in value)
        if isinstance(value, dict):
            return self._estimate_tokens(json.dumps(value, ensure_ascii=False))
        return self._estimate_tokens(str(value))

    def _build_completion(self, messages: List[Dict[str, Any]], content: str) -> ChatCompletion:
        prompt_tokens = sum(self._estimate_tokens(message.get('content')) for message in messages)
        completion_tokens = self._estimate_tokens(content)

        return ChatCompletion.model_validate(
            {
                'id': f'chatcmpl-cli-{uuid.uuid4().hex[:24]}',
                'object': 'chat.completion',
                'created': int(time.time()),
                'model': self._llm.model or str(self.model_type),
                'choices': [
                    {
                        'index': 0,
                        'message': {
                            'role': 'assistant',
                            'content': content,
                        },
                        'finish_reason': 'stop',
                    }
                ],
                'usage': {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': prompt_tokens + completion_tokens,
                },
            }
        )

    def _request_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        if tools:
            logger.warning('CLIModel ignores tool schemas; tool calling is not supported in OASIS CLI mode')

        temperature = float((self.model_config_dict or {}).get('temperature', 1.0) or 1.0)
        max_tokens = int((self.model_config_dict or {}).get('max_tokens', 4096) or 4096)
        content = self._llm.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._build_completion(messages, content)

    async def _arequest_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        return await asyncio.to_thread(self._request_chat_completion, messages, tools)

    def _request_parse(
        self,
        messages: List[Dict[str, Any]],
        response_format,
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        if tools:
            logger.warning('CLIModel ignores tool schemas during structured output requests')

        temperature = float((self.model_config_dict or {}).get('temperature', 1.0) or 1.0)
        max_tokens = int((self.model_config_dict or {}).get('max_tokens', 4096) or 4096)
        payload = self._llm.chat_json(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._build_completion(messages, json.dumps(payload, ensure_ascii=False))

    async def _arequest_parse(
        self,
        messages: List[Dict[str, Any]],
        response_format,
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        return await asyncio.to_thread(self._request_parse, messages, response_format, tools)


def create_oasis_model(config: Dict[str, Any], use_boost: bool = False):
    """Create the CAMEL model used by OASIS simulations."""

    resolved = resolve_oasis_llm_config(config, use_boost=use_boost)

    if resolved.is_cli:
        print(
            f"{resolved.label} provider={resolved.provider}, model={resolved.model}, mode=cli-bridge"
        )
        return CLIModel(
            model_type=resolved.model,
            provider=resolved.provider,
            model_config_dict={},
            api_key=resolved.api_key or 'cli-bridge',
            url=resolved.base_url or None,
        )

    if not resolved.api_key:
        raise ValueError(
            'Missing API Key configuration. Please set LLM_API_KEY in the project root .env file '
            'or use LLM_PROVIDER=claude-cli/codex-cli.'
        )

    print(
        f"{resolved.label} provider={resolved.provider}, model={resolved.model}, "
        f"base_url={resolved.base_url[:40] if resolved.base_url else 'default'}..."
    )

    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=resolved.model,
        model_config_dict={"temperature": 1.0},
        api_key=resolved.api_key,
        url=resolved.base_url or None,
    )


def get_oasis_semaphore(config: Dict[str, Any], use_boost: bool = False) -> int:
    """Get a provider-appropriate OASIS concurrency limit."""

    resolved = resolve_oasis_llm_config(config, use_boost=use_boost)
    if resolved.is_cli:
        return int(os.environ.get('OASIS_CLI_SEMAPHORE', str(DEFAULT_CLI_SEMAPHORE)))
    return int(os.environ.get('OASIS_API_SEMAPHORE', str(DEFAULT_API_SEMAPHORE)))
