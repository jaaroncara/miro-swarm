"""Helpers for using CLI-backed LLMs inside OASIS/CAMEL simulations.

Includes transparent MCP tool-calling support: when MCP_SERVER_ENABLED=true,
every agent chat completion is augmented with MCP tool schemas.  If the LLM
responds with tool_calls, we execute them against the MCP server in a loop
before returning the final natural-language answer to OASIS.
"""

import asyncio
import copy
import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from camel.models import ModelFactory
from camel.models.openai_model import OpenAIModel
from camel.types import ModelPlatformType
from openai.types.chat.chat_completion import ChatCompletion

from ..config import Config
from ..core.task_action_parser import TASK_ACTION_GRAMMAR
from .llm_client import LLMClient
from .logger import get_logger

logger = get_logger("mirofish.oasis_llm")

CLI_PROVIDERS = {"claude-cli", "codex-cli"}
DEFAULT_API_SEMAPHORE = 30
DEFAULT_CLI_SEMAPHORE = 3
TASK_MCP_TOOL_ORDER = (
    "offer_task",
    "accept_task",
    "decline_task",
    "get_task",
    "list_my_tasks",
    "start_task",
    "update_task_status",
    "block_task",
    "complete_task",
    "save_task_artifact",
)
TASK_MCP_TOOL_NAMES = set(TASK_MCP_TOOL_ORDER)

TASK_COORDINATION_SYSTEM_ADDENDUM = f"""
# TASK COORDINATION
- Use task MCP tools as the primary coordination path whenever they are available.
- When you ask a colleague for work, make it a concrete deliverable that can be completed inside the simulation with the available MCP tools. Prefer briefs, analyses, summaries, comparisons, memos, recommendations, evidence packs, and report sections over meeting coordination.
- Do not offer meeting-only work such as "set up a meeting", "schedule a sync", or "talk to Marketing" unless you rewrite it into a concrete deliverable request first.
- When you ask a colleague for a concrete deliverable, call `offer_task` so they can explicitly `accept_task` or `decline_task` before work begins.
- Before replying about task work, check `list_my_tasks` and `get_task` so you do not miss pending offers or active assignments.
- After accepting a task, keep it current with `start_task`, `update_task_status`, `block_task`, `complete_task`, and `save_task_artifact` when you produce a deliverable.
- If the deliverable would naturally live in a file, such as a markdown brief, memo, meeting notes, CSV table, JSON payload, code/config snippet, or PDF, call `save_task_artifact` first with a descriptive filename and matching `media_type`.
- For text artifacts, prefer `encoding="utf-8"` and filenames such as `brief.md`, `notes.txt`, `results.json`, or `table.csv`. For binary artifacts such as PDFs, send base64 content with `encoding="base64"`.
- When you publish the final report or deliverable for a task, pass that same report text, or a faithful summary of it, into `complete_task.output` so the task record preserves what you published. If you saved a file artifact first, complete the task with a concise summary that mentions the saved filename and the key outcome.
- After you accept, decline, start, update, block, or complete a task, leave a visible public update in the simulation chat so other agents can follow the lifecycle and see the result.
- Typical file-output sequence: call `save_task_artifact` with the file content, then call `complete_task` with a short summary such as "Saved rollout-brief.md with the final recommendation set."
- The active simulation ID and your actor identity are injected automatically for task MCP tools. Do not provide them yourself.
- XML `<task_action>` blocks are legacy compatibility only. Use them only if task MCP tools are unavailable in the current run.

{TASK_ACTION_GRAMMAR}
""".strip()


# ═══════════════════════════════════════════════════════════════
# Business-oriented system prompt overrides for OASIS agents
#
# The upstream OASIS framework frames agents as "Twitter users" and
# "Reddit users", which causes LLMs to produce short social-media-style
# output.  For business simulation we replace those with Slack channel
# and internal email framing so agents write substantive, professional
# messages at realistic lengths.
#
# These are applied as monkey-patches on UserInfo so every simulation
# script that imports oasis_llm gets the override automatically,
# without modifying vendored code in .venv.
# ═══════════════════════════════════════════════════════════════


def _business_slack_system_message(self) -> str:
    """Slack channel system prompt (replaces Twitter framing)."""
    name_string = ""
    description_string = ""
    description = ""
    if self.name is not None:
        name_string = f"Your name is {self.name}."
    if self.profile is None:
        description = name_string
    elif "other_info" not in self.profile:
        description = name_string
    elif "user_profile" in self.profile.get("other_info", {}):
        if self.profile["other_info"]["user_profile"] is not None:
            user_profile = self.profile["other_info"]["user_profile"]
            description_string = f"Your profile: {user_profile}."
            description = f"{name_string}\n{description_string}"
        else:
            description = name_string
    else:
        description = name_string

    return f"""
# SELF-DESCRIPTION
Your actions and communication style should be consistent with your
professional identity and personality.
{description}

# OBJECTIVE
You are a corporate professional communicating through internal Slack channels.
You will be presented with messages from colleagues. After reviewing them,
choose actions from the available functions.

# COMMUNICATION GUIDELINES
- Write realistic Slack messages (brief, conversational, usually 1-3 sentences or 10-50 words).
- Use appropriate formatting (threaded replies, emojis, code blocks, bullet points).
- React to urgency: Be terse during incidents, collaborative during brainstorming.
- Not every message needs to be a profound business statement; quick acknowledgments ("Looking into this", "Approved", "+1") are highly realistic.
- Advocate for your department. If a proposal threatens your team's bandwidth or KPIs, push back professionally.
- IMPORTANT: Before composing any message that references metrics, trends, or
  business data, you MUST first call the relevant data tool (e.g.
  lookup_business_data, basic_news_search) to retrieve real numbers.

# RESPONSE METHOD & TOOL EXECUTION
You operate in a multi-turn environment. You MUST separate data gathering from your final action:

TURN 1 (DATA GATHERING): If the discussion involves metrics, trends, or facts, you MUST call your data tools (e.g., `lookup_business_data`, `basic_news_search`) FIRST. 
**CRITICAL:** Do NOT call platform tools like `create_post` or `send_email` during this turn. Wait for the tool observation to be returned to you.

TURN 2 (ACTION): Once you receive the data observation, you may then call your platform tools (`create_post`, etc.) to compose your message. You MUST explicitly quote the exact numbers and metrics from the tool observation in your final message.

If your role relies on data (e.g. Sales, Finance, Analyst), any message you post without citing hard numbers retrieved from your MCP tools is considered a failure.

{TASK_COORDINATION_SYSTEM_ADDENDUM}
"""


def _business_email_system_message(self) -> str:
    """Internal email system prompt (replaces Reddit framing)."""
    name_string = ""
    description_string = ""
    description = ""
    if self.name is not None:
        name_string = f"Your name is {self.name}."
    if self.profile is None:
        description = name_string
    elif "other_info" not in self.profile:
        description = name_string
    elif "user_profile" in self.profile.get("other_info", {}):
        if self.profile["other_info"]["user_profile"] is not None:
            user_profile = self.profile["other_info"]["user_profile"]
            description_string = f"Your profile: {user_profile}."
            description = f"{name_string}\n{description_string}"
        else:
            description = name_string
    else:
        description = name_string

    # Append demographic/professional details if available
    if self.profile and "other_info" in self.profile:
        other = self.profile["other_info"]
        demo_parts = []
        if other.get("gender"):
            demo_parts.append(f"{other['gender']}")
        if other.get("age"):
            demo_parts.append(f"age {other['age']}")
        if other.get("mbti"):
            demo_parts.append(f"MBTI personality type {other['mbti']}")
        if other.get("country"):
            demo_parts.append(f"based in {other['country']}")
        if demo_parts:
            description += f"\nYou are a professional — {', '.join(demo_parts)}."

    return f"""
# SELF-DESCRIPTION
Your communication style and professional opinions should be consistent
with your identity and expertise.
{description}

# OBJECTIVE
You are a corporate professional communicating through internal email.
You will be presented with email threads and messages from colleagues.
After reviewing them, choose actions from the available functions.

# COMMUNICATION GUIDELINES
- Write professional but pragmatic emails. Use a "Bottom Line Up Front" (BLUF) approach for executives.
- Clearly delegate Action Items (e.g., "@Jane - please review by EOD").
- Factor in organizational politics: ensure you are aligning with your department's goals and looping in relevant stakeholders.
- When disagreeing, maintain a corporate tone but hold firm on your team's constraints, budgets, or technical limitations.
- Tailor depth and formality to the audience (executive summaries vs. detailed breakdowns).
- IMPORTANT: Before composing any email that references metrics, trends, or
  business data, you MUST first call the relevant data tool (e.g.
  lookup_business_data, basic_news_search) to retrieve real numbers.

# RESPONSE METHOD & TOOL EXECUTION
You operate in a multi-turn environment. You MUST separate data gathering from your final action:

TURN 1 (DATA GATHERING): If the discussion involves metrics, trends, or facts, you MUST call your data tools (e.g., `lookup_business_data`, `basic_news_search`) FIRST. 
**CRITICAL:** Do NOT call platform tools like `send_email` or `create_post` during this turn. Wait for the tool observation to be returned to you.

TURN 2 (ACTION): Once you receive the data observation, you may then call your platform tools (`compose_email`, etc.) to compose your message. You MUST explicitly quote the exact numbers and metrics from the tool observation in your final message.

If your role relies on data (e.g. Sales, Finance, Analyst), any message you post without citing hard numbers retrieved from your MCP tools is considered a failure.

{TASK_COORDINATION_SYSTEM_ADDENDUM}
"""


# Apply overrides at import time so all simulation scripts get business framing
try:
    from oasis.social_platform.config import UserInfo

    UserInfo.to_twitter_system_message = _business_slack_system_message
    UserInfo.to_reddit_system_message = _business_email_system_message
    logger.info(
        "Applied business-oriented system prompts (Slack/Email) to OASIS UserInfo"
    )
except ImportError:
    pass  # OASIS not installed; overrides not needed


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
    model_lower = (model or "").lower()
    base_lower = (base_url or "").lower()

    if any(keyword in model_lower for keyword in ("claude", "anthropic")):
        return "anthropic"
    if "anthropic" in base_lower:
        return "anthropic"
    return "openai"


def resolve_oasis_llm_config(
    config: Dict[str, Any], use_boost: bool = False
) -> ResolvedLLMConfig:
    """Resolve the LLM configuration used by OASIS simulation scripts."""

    standard_provider = (
        os.environ.get("LLM_PROVIDER")
        or config.get("llm_provider")
        or Config.LLM_PROVIDER
        or ""
    ).lower()
    standard_api_key = (
        os.environ.get("LLM_API_KEY")
        or Config.LLM_API_KEY
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    )
    standard_base_url = os.environ.get("LLM_BASE_URL") or Config.LLM_BASE_URL or ""
    standard_model = (
        os.environ.get("LLM_MODEL_NAME")
        or config.get("llm_model")
        or Config.LLM_MODEL_NAME
        or "gpt-4o-mini"
    )

    boost_provider = (
        os.environ.get("LLM_BOOST_PROVIDER")
        or config.get("llm_boost_provider")
        or standard_provider
        or ""
    ).lower()
    boost_api_key = os.environ.get("LLM_BOOST_API_KEY", "")
    boost_base_url = os.environ.get("LLM_BOOST_BASE_URL", "")
    boost_model = os.environ.get("LLM_BOOST_MODEL_NAME", "") or standard_model
    has_boost_config = bool(
        boost_api_key or boost_base_url or os.environ.get("LLM_BOOST_MODEL_NAME")
    )

    if use_boost and has_boost_config:
        provider = boost_provider or _detect_provider(boost_model, boost_base_url)
        return ResolvedLLMConfig(
            provider=provider,
            api_key=boost_api_key,
            base_url=boost_base_url,
            model=boost_model,
            label="[Boost LLM]",
            is_cli=provider in CLI_PROVIDERS,
        )

    provider = standard_provider or _detect_provider(standard_model, standard_base_url)
    return ResolvedLLMConfig(
        provider=provider,
        api_key=standard_api_key,
        base_url=standard_base_url,
        model=standard_model,
        label="[Standard LLM]",
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
        simulation_id: str | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
    ) -> None:
        self.provider = (provider or "").lower()
        self._simulation_id = simulation_id
        self._llm = LLMClient(
            api_key=api_key,
            base_url=url,
            model=model_type,
            provider=self.provider,
        )
        super().__init__(
            model_type=model_type,
            model_config_dict=model_config_dict,
            api_key=api_key or "cli-bridge",
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

    def _build_completion(
        self, messages: List[Dict[str, Any]], content: str
    ) -> ChatCompletion:
        prompt_tokens = sum(
            self._estimate_tokens(message.get("content")) for message in messages
        )
        completion_tokens = self._estimate_tokens(content)

        return ChatCompletion.model_validate(
            {
                "id": f"chatcmpl-cli-{uuid.uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": self._llm.model or str(self.model_type),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }
        )

    def _request_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        if tools:
            logger.warning(
                "CLIModel ignores native OASIS tool schemas; using MCP tools instead if configured"
            )

        temperature = float(
            (self.model_config_dict or {}).get("temperature", 1.0) or 1.0
        )
        max_tokens = int((self.model_config_dict or {}).get("max_tokens", 4096) or 4096)

        # --- MCP tool-calling loop (sync, for CLI providers) ---
        final_content = _mcp_tool_loop_sync(
            llm=self._llm,
            messages=list(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            simulation_id=self._simulation_id,
        )

        return self._build_completion(messages, final_content)

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
            logger.warning(
                "CLIModel ignores tool schemas during structured output requests"
            )

        temperature = float(
            (self.model_config_dict or {}).get("temperature", 1.0) or 1.0
        )
        max_tokens = int((self.model_config_dict or {}).get("max_tokens", 4096) or 4096)
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
        return await asyncio.to_thread(
            self._request_parse, messages, response_format, tools
        )


# ═══════════════════════════════════════════════════════════════
# MCPOpenAIModel — native OpenAI function-calling with MCP tools
# ═══════════════════════════════════════════════════════════════


class MCPOpenAIModel(OpenAIModel):
    """Thin wrapper around CAMEL's OpenAIModel that injects MCP tools as
    native OpenAI function-calling schemas and handles the
    tool_calls → execute → re-prompt loop transparently.

    When MCP is disabled or has no tools, behaviour is identical to the
    base ``OpenAIModel``.
    """

    def __init__(self, *args, simulation_id: str | None = None, **kwargs) -> None:
        self._simulation_id = simulation_id
        super().__init__(*args, **kwargs)

    def _get_mcp_tools_and_names(self, messages: List[Dict[str, Any]]):
        """Return (openai_tool_schemas, set_of_mcp_tool_names) or ([], set())."""
        mgr = _get_mcp_manager_if_enabled()
        if mgr is None:
            return [], set()
        actor_name = _extract_actor_name(messages)
        schemas = [
            _prepare_mcp_tool_schema(schema, self._simulation_id, actor_name)
            for schema in mgr.get_openai_tools_schema()
        ]
        names = {s["function"]["name"] for s in schemas}
        return schemas, names

    def _execute_mcp_tool_calls(
        self, tool_calls, mcp_tool_names, actor_name: str | None
    ):
        """Execute MCP tool calls and return a list of tool-result messages.

        Non-MCP tool calls (i.e. OASIS-native tools) are skipped so they
        can be handled by the framework itself.
        """
        mgr = _get_mcp_manager_if_enabled()
        if mgr is None:
            return []

        tool_messages = []
        for tc in tool_calls:
            fn_name = tc.function.name
            if fn_name not in mcp_tool_names:
                continue  # not an MCP tool — leave for OASIS

            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}
                logger.warning(
                    f"Failed to parse arguments for MCP tool '{fn_name}': "
                    f"{tc.function.arguments[:200]}"
                )

            logger.info(f"MCP tool call: {fn_name}")

            try:
                result = mgr.call_tool_sync(
                    fn_name,
                    _prepare_mcp_tool_arguments(
                        fn_name,
                        fn_args,
                        self._simulation_id,
                        actor_name,
                    ),
                )
            except Exception as exc:
                result = f"Tool error: {exc}"
                logger.warning(f"MCP tool '{fn_name}' failed: {exc}")

            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )

        return tool_messages

    # ------------------------------------------------------------------

    def _request_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        actor_name = _extract_actor_name(messages)
        mcp_schemas, mcp_names = self._get_mcp_tools_and_names(messages)

        if not mcp_schemas:
            # Fast path — no MCP overhead
            return super()._request_chat_completion(messages, tools)

        # Per-agent tool routing: select only the best-fit tools
        mgr = _get_mcp_manager_if_enabled()
        if mgr is not None:
            available_tools = mgr.get_tools()
            selected_names = _ensure_task_tool_access(
                _tool_router.select_tools(messages, available_tools),
                available_tools,
            )
            if selected_names is not None:
                name_set = set(selected_names)
                mcp_schemas = [
                    s for s in mcp_schemas if s["function"]["name"] in name_set
                ]
                mcp_names = {s["function"]["name"] for s in mcp_schemas}
                if not mcp_schemas:
                    return super()._request_chat_completion(messages, tools)

        # Merge MCP tool schemas with any OASIS-native tools
        merged_tools = list(tools or []) + mcp_schemas

        max_rounds = Config.MCP_MAX_TOOL_ROUNDS
        messages = list(messages)  # shallow copy for the loop

        for round_idx in range(max_rounds + 1):  # +1 for the final non-tool turn
            response = super()._request_chat_completion(messages, merged_tools)

            choice = response.choices[0]
            assistant_msg = choice.message

            # If the model didn't call any tools we're done
            if not assistant_msg.tool_calls:
                return response

            mcp_calls = []
            native_calls = []
            for tool_call in assistant_msg.tool_calls:
                if tool_call.function.name in mcp_names:
                    mcp_calls.append(tool_call)
                else:
                    native_calls.append(tool_call)

            if not mcp_calls:
                # All tool calls are OASIS-native — return as-is
                return response

            logger.info(
                f"MCP tool round {round_idx + 1}/{max_rounds}: "
                f"{[tc.function.name for tc in mcp_calls]}"
            )

            # Execute MCP tool calls
            tool_result_messages = self._execute_mcp_tool_calls(
                mcp_calls,
                mcp_names,
                actor_name,
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.content or "",
                    "tool_calls": _serialize_openai_tool_calls(mcp_calls),
                }
            )
            messages.extend(tool_result_messages)

            if native_calls:
                logger.warning(
                    "Model mixed MCP and native tool calls; deferring native follow-up "
                    f"until after task tool results: {[tc.function.name for tc in native_calls]}"
                )
                follow_up_messages = list(messages)
                follow_up_messages.append(
                    {
                        "role": "user",
                        "content": _build_native_follow_up_prompt(native_calls),
                    }
                )
                return super()._request_chat_completion(follow_up_messages, tools)

        # Exhausted rounds — make one final call without tools so the model
        # produces a natural-language answer
        logger.warning("MCP tool loop exhausted max rounds; making final call")
        return super()._request_chat_completion(messages, tools)

    async def _arequest_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        return await asyncio.to_thread(self._request_chat_completion, messages, tools)


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
            api_key=resolved.api_key or "cli-bridge",
            url=resolved.base_url or None,
            simulation_id=config.get("simulation_id"),
        )

    if not resolved.api_key:
        raise ValueError(
            "Missing API Key configuration. Please set LLM_API_KEY in the project root .env file "
            "or use LLM_PROVIDER=claude-cli/codex-cli."
        )

    # Use MCPOpenAIModel when MCP tools are available so simulation agents
    # can invoke tools via native OpenAI function-calling.
    mgr = _get_mcp_manager_if_enabled()
    if mgr is not None:
        print(
            f"{resolved.label} provider={resolved.provider}, model={resolved.model}, "
            f"base_url={resolved.base_url[:40] if resolved.base_url else 'default'}..., "
            f"mcp_tools={len(mgr.get_tools())}"
        )
        return MCPOpenAIModel(
            model_type=resolved.model,
            model_config_dict={"temperature": 1.0},
            api_key=resolved.api_key,
            url=resolved.base_url or None,
            simulation_id=config.get("simulation_id"),
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
        return int(os.environ.get("OASIS_CLI_SEMAPHORE", str(DEFAULT_CLI_SEMAPHORE)))
    return int(os.environ.get("OASIS_API_SEMAPHORE", str(DEFAULT_API_SEMAPHORE)))


# ═══════════════════════════════════════════════════════════════
# MCP Tool-Calling Loop
# ═══════════════════════════════════════════════════════════════

# A system-level instruction appended to the agent's messages when MCP tools
# are available.  This teaches the LLM how to invoke tools using a lightweight
# XML format that we can regex-parse from CLI providers that don't support
# native OpenAI function-calling JSON.
MCP_TOOL_SYSTEM_ADDENDUM = """
# EXTERNAL TOOL USAGE

You have access to the external tools listed below. Use business/data tools to ground your responses in real numbers, and use task tools when you need to inspect or update private task state for coordination.

## Tool Calling Format

To execute a data tool, output a single `<tool_call>` block containing a JSON payload. You will receive an `<observation>` back with the result.

<tool_call>
{{"name": "<tool_name>", "arguments": {{<json_args>}}}}
</tool_call>

You may invoke up to {max_rounds} tools consecutively.

## Execution Rules

1. STRICT TURN SEPARATION: If you need data, your output must contain ONLY the `<tool_call>` block. Do NOT include your final message (CREATE_POST, CREATE_COMMENT, etc.) in the same response as the tool call.
2. NO ASSUMPTIONS: Ground your final message in the data returned in the `<observation>`. Do not guess metrics or facts.

## Available Tools
{tool_descriptions}

## Correct Execution Examples

### Example: Data Gather (Turn 1)
User: "How is EMEA revenue tracking this quarter?"
You:
<tool_call>
{{"name": "lookup_business_data", "arguments": {{"dataset": "sales", "region": "EMEA", "quarter": "Q1"}}}}
</tool_call>

### Example: Action (Turn 2 - After receiving <observation>)
System: <observation>EMEA Q1 Revenue: $4.2M (+12% YoY)</observation>
You:
`CREATE_POST`: "EMEA revenue hit $4.2M for Q1, up 12% YoY. We need to capitalize on this momentum."
""".strip()

import re

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)
_ACTOR_NAME_RE = re.compile(r"Your name is\s+([^\.\n]+)", re.IGNORECASE)
_DEFERRED_PUBLIC_UPDATE_PROMPT = (
    "The task tool results above are now available. Your previous reply mixed "
    "task-tool work with a public platform action. Now issue only the required "
    "public update or reply for this turn, and do not call additional task MCP "
    "tools unless you still need them."
)


def _extract_tool_call_xml_parts(
    text: str,
) -> tuple[Optional[Dict[str, Any]], str, str]:
    """Extract the first tool call plus any surrounding non-tool content."""
    match = _TOOL_CALL_RE.search(text)
    if not match:
        return None, "", ""

    tool_block = match.group(0)
    remainder = f"{text[: match.start()]}{text[match.end() :]}".strip()

    try:
        return json.loads(match.group(1)), tool_block, remainder
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse MCP tool call JSON: {match.group(1)[:200]}")
        return None, "", ""


def _parse_tool_call_xml(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first <tool_call>{...}</tool_call> from *text*."""
    parsed, _, _ = _extract_tool_call_xml_parts(text)
    return parsed


def _get_mcp_manager_if_enabled():
    """Return the MCPManager singleton if MCP is configured and connected, else None."""
    if not Config.MCP_SERVER_ENABLED:
        return None
    from .mcp_manager import get_mcp_manager_sync

    mgr = get_mcp_manager_sync()
    if mgr is not None and mgr.is_connected and mgr.has_tools():
        return mgr
    return None


def _extract_actor_name(messages: List[Dict[str, Any]]) -> str | None:
    """Extract the current agent name from the original system prompt."""
    for message in messages:
        if message.get("role") != "system":
            continue
        content = str(message.get("content", ""))
        match = _ACTOR_NAME_RE.search(content)
        if match:
            return match.group(1).strip()
    return None


def _prepare_mcp_tool_arguments(
    tool_name: str,
    arguments: Dict[str, Any] | None,
    simulation_id: str | None,
    actor_name: str | None = None,
) -> Dict[str, Any]:
    """Auto-inject active task scope for task tools."""
    prepared = dict(arguments or {})
    if simulation_id and tool_name in TASK_MCP_TOOL_NAMES:
        prepared.setdefault("simulation_id", simulation_id)
    if actor_name and tool_name in TASK_MCP_TOOL_NAMES:
        prepared.setdefault("actor", actor_name)
    return prepared


def _prepare_mcp_tool_schema(
    schema: Dict[str, Any],
    simulation_id: str | None,
    actor_name: str | None = None,
) -> Dict[str, Any]:
    """Hide auto-scoped task-tool fields from the tool schema."""
    if (not simulation_id and not actor_name) or schema.get("function", {}).get(
        "name"
    ) not in TASK_MCP_TOOL_NAMES:
        return schema

    patched = copy.deepcopy(schema)
    function_block = patched.setdefault("function", {})
    parameters = function_block.setdefault("parameters", {})
    properties = parameters.get("properties")
    if isinstance(properties, dict):
        if simulation_id:
            properties.pop("simulation_id", None)
        if actor_name:
            properties.pop("actor", None)

    required = parameters.get("required")
    if isinstance(required, list):
        parameters["required"] = [
            item for item in required if item not in {"simulation_id", "actor"}
        ]

    description = (function_block.get("description") or "").rstrip()
    auto_notes = []
    if simulation_id:
        auto_notes.append(
            "The active simulation_id is injected automatically; do not provide it."
        )
    if actor_name:
        auto_notes.append(
            "The active actor is injected automatically; do not provide it."
        )
    auto_note = f" {' '.join(auto_notes)}" if auto_notes else ""
    if auto_note.strip() and auto_note.strip() not in description:
        function_block["description"] = f"{description}{auto_note}".strip()

    return patched


def _serialize_openai_tool_calls(tool_calls) -> List[Dict[str, Any]]:
    """Convert OpenAI tool-call objects into chat-history payloads."""
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        }
        for tc in tool_calls
    ]


def _build_native_follow_up_prompt(native_tool_calls) -> str:
    """Ask the model to re-issue deferred native platform actions."""
    deferred_names: list[str] = []
    seen_names: set[str] = set()
    for tool_call in native_tool_calls:
        tool_name = getattr(getattr(tool_call, "function", None), "name", "")
        if tool_name and tool_name not in seen_names:
            deferred_names.append(tool_name)
            seen_names.add(tool_name)

    if not deferred_names:
        return _DEFERRED_PUBLIC_UPDATE_PROMPT

    deferred_list = ", ".join(deferred_names)
    return (
        f"{_DEFERRED_PUBLIC_UPDATE_PROMPT} Re-issue the deferred platform action "
        f"using: {deferred_list}."
    )


def _format_mcp_tool_descriptions(
    tools: List[Any],
    simulation_id: str | None,
    actor_name: str | None = None,
) -> str:
    """Render tool descriptions, hiding auto-scoped task-tool arguments."""
    parts: list[str] = []
    for tool in tools:
        input_schema = tool.inputSchema if hasattr(tool, "inputSchema") else {}
        props = dict((input_schema or {}).get("properties", {}))
        if simulation_id and tool.name in TASK_MCP_TOOL_NAMES:
            props.pop("simulation_id", None)
        if actor_name and tool.name in TASK_MCP_TOOL_NAMES:
            props.pop("actor", None)

        if props:
            param_strs = []
            for pname, pschema in props.items():
                ptype = pschema.get("type", "any")
                pdesc = pschema.get("description", "")
                param_strs.append(
                    f"{pname} ({ptype}): {pdesc}" if pdesc else f"{pname} ({ptype})"
                )
            params_line = f"  Parameters: {', '.join(param_strs)}"
        else:
            params_line = "  Parameters: (none)"

        description = tool.description or "(no description)"
        if tool.name in TASK_MCP_TOOL_NAMES:
            auto_notes = []
            if simulation_id:
                auto_notes.append("The active simulation_id is injected automatically.")
            if actor_name:
                auto_notes.append("The active actor is injected automatically.")
            if auto_notes:
                description = f"{description.rstrip()} {' '.join(auto_notes)}"

        parts.append(f"- mcp__{tool.name}: {description}")
        parts.append(params_line)
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Per-Agent MCP Tool Routing
# ═══════════════════════════════════════════════════════════════

MCP_MAX_TOOLS_PER_AGENT = int(os.environ.get("MCP_MAX_TOOLS_PER_AGENT", "3"))


class ToolRouter:
    """Selects the best-fit MCP tools for each agent via a one-shot LLM call.

    Results are cached by agent identity (hashed system message) so each
    unique agent profile pays the routing cost only once per simulation run.
    When routing is disabled (MCP_MAX_TOOLS_PER_AGENT <= 0) all tools are
    returned.  On any failure the agent receives NO tools (strict filtering).
    """

    def __init__(self) -> None:
        self._cache: Dict[str, List[str]] = {}
        self._llm: Optional[LLMClient] = None

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    @staticmethod
    def _extract_agent_key(messages: List[Dict[str, Any]]) -> Optional[str]:
        """Hash the first system message to get a stable per-agent cache key."""
        for msg in messages:
            if msg.get("role") == "system":
                content = str(msg.get("content", ""))
                if content:
                    return hashlib.sha256(content.encode()).hexdigest()[:16]
        return None

    def select_tools(
        self,
        messages: List[Dict[str, Any]],
        all_tools: list,
    ) -> List[str]:
        """Return a list of tool names best suited for the agent in *messages*.

        *all_tools* should be the raw MCP Tool objects from MCPManager.get_tools().
        Returns at most ``MCP_MAX_TOOLS_PER_AGENT`` names.  On failure returns
        an empty list (strict = agent gets no tools).
        """
        max_tools = MCP_MAX_TOOLS_PER_AGENT
        if max_tools <= 0:
            # Routing disabled — return all tool names
            return [t.name for t in all_tools]

        if not all_tools:
            return []

        agent_key = self._extract_agent_key(messages)
        if agent_key is None:
            return []  # no system message → no tools

        if agent_key in self._cache:
            return self._cache[agent_key]

        # Build a compact agent description from the system message
        agent_desc = ""
        for msg in messages:
            if msg.get("role") == "system":
                agent_desc = str(msg.get("content", ""))[:500]
                break

        # Build numbered tool catalog
        catalog_lines = []
        valid_names = set()
        for i, tool in enumerate(all_tools, 1):
            name = tool.name
            desc = (tool.description or "")[:120]
            catalog_lines.append(f"{i}. {name} — {desc}")
            valid_names.add(name)
        catalog = "\n".join(catalog_lines)

        prompt = (
            f"Given this agent description:\n---\n{agent_desc}\n---\n\n"
            f"And these available tools:\n{catalog}\n\n"
            f"Select up to {max_tools} tools that would be most useful for "
            f"this agent's role and expertise. Return ONLY a JSON array of "
            f'tool name strings, e.g. ["tool_a", "tool_b"].\n'
            f"If no tools are relevant, return an empty array []."
        )

        try:
            llm = self._get_llm()
            raw = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=256,
            )
            # Extract JSON array from the response
            import re as _re

            match = _re.search(r"\[.*?\]", raw or "", _re.DOTALL)
            if not match:
                fallback = [t.name for t in all_tools][:max_tools]
                logger.warning(
                    f"ToolRouter: no JSON array in LLM response; "
                    f"falling back to all tools for agent {agent_key[:8]}… "
                    f"({agent_desc[:100]})"
                )
                self._cache[agent_key] = fallback
                return fallback

            selected = json.loads(match.group(0))
            if not isinstance(selected, list):
                selected = []

            # Validate and cap
            result = [n for n in selected if isinstance(n, str) and n in valid_names][
                :max_tools
            ]
            self._cache[agent_key] = result
            logger.info(
                f"ToolRouter: agent {agent_key[:8]}… → "
                f"{result if result else '(no tools)'}"
            )
            return result

        except Exception as exc:
            fallback = [t.name for t in all_tools][:max_tools]
            logger.warning(
                f"ToolRouter: LLM call failed ({exc}); "
                f"falling back to all tools for agent {agent_key[:8]}… "
                f"({agent_desc[:100]})"
            )
            self._cache[agent_key] = fallback
            return fallback


_tool_router = ToolRouter()


def _ensure_task_tool_access(
    selected_names: List[str] | None,
    available_tools: list,
) -> List[str] | None:
    """Preserve task coordination tools even when role-based routing is active."""
    if selected_names is None:
        return None

    available_names: list[str] = []
    seen_available: set[str] = set()
    for tool in available_tools:
        name = getattr(tool, "name", None)
        if not name or name in seen_available:
            continue
        available_names.append(name)
        seen_available.add(name)

    merged: list[str] = []
    seen_selected: set[str] = set()
    required_task_tools = [
        name for name in TASK_MCP_TOOL_ORDER if name in seen_available
    ]

    for name in list(selected_names) + required_task_tools:
        if name not in seen_available or name in seen_selected:
            continue
        merged.append(name)
        seen_selected.add(name)

    return merged


def _mcp_tool_loop_sync(
    llm: LLMClient,
    messages: List[Dict[str, Any]],
    temperature: float = 1.0,
    max_tokens: int = 4096,
    simulation_id: str | None = None,
) -> str:
    """
    Run a single LLM turn with an optional MCP tool-calling inner loop.

    If MCP is not enabled or has no tools, this degrades to a plain
    ``llm.chat()`` call with zero overhead.

    The loop:
    1. Inject available MCP tool descriptions into the system message.
    2. Call the LLM.
    3. If the response contains a ``<tool_call>`` block, execute the tool
       via MCPManager, append the observation, and loop (up to max rounds).
    4. Return the final text once the LLM stops calling tools.
    """
    mgr = _get_mcp_manager_if_enabled()

    if mgr is None:
        # Fast path — no MCP overhead
        return llm.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # Per-agent tool routing: select only the best-fit tools
    all_mcp_tools = mgr.get_tools()
    selected_names = _ensure_task_tool_access(
        _tool_router.select_tools(messages, all_mcp_tools),
        all_mcp_tools,
    )
    if selected_names is not None and not selected_names:
        # Strict filtering: no relevant tools → skip MCP entirely
        return llm.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # Filter tools to only the selected subset
    if selected_names is not None:
        name_set = set(selected_names)
        filtered_tools = [t for t in all_mcp_tools if t.name in name_set]
    else:
        filtered_tools = all_mcp_tools

    max_rounds = Config.MCP_MAX_TOOL_ROUNDS
    actor_name = _extract_actor_name(messages)
    tool_desc = _format_mcp_tool_descriptions(filtered_tools, simulation_id, actor_name)

    # Inject tool instructions into the conversation
    mcp_system_msg = MCP_TOOL_SYSTEM_ADDENDUM.format(
        max_rounds=max_rounds,
        tool_descriptions=tool_desc,
    )
    messages = list(messages)  # shallow copy
    messages.insert(0, {"role": "system", "content": mcp_system_msg})

    for round_idx in range(max_rounds + 1):  # +1 for the final non-tool turn
        content = llm.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if content is None:
            return "(empty response from LLM)"

        call, tool_block, deferred_public_update = _extract_tool_call_xml_parts(content)
        if call is None:
            # No tool call — this is the final answer
            return content

        tool_name = call.get("name", "")
        tool_args = call.get("arguments", {})
        logger.info(f"MCP tool call (round {round_idx+1}/{max_rounds}): {tool_name}")

        try:
            observation = mgr.call_tool_sync(
                tool_name,
                _prepare_mcp_tool_arguments(
                    tool_name, tool_args, simulation_id, actor_name
                ),
            )
        except Exception as exc:
            observation = f"Tool error: {exc}"
            logger.warning(f"MCP tool '{tool_name}' failed: {exc}")

        # Append assistant message + observation
        messages.append({"role": "assistant", "content": tool_block or content})
        observation_content = f"<observation>\n{observation}\n</observation>"
        if deferred_public_update:
            logger.warning(
                "CLI response mixed an MCP tool call with a public action; "
                "deferring the public update until after the observation"
            )
            observation_content = (
                f"{observation_content}\n\n{_DEFERRED_PUBLIC_UPDATE_PROMPT}\n"
                f"<draft_public_update>\n{deferred_public_update}\n</draft_public_update>"
            )
        messages.append(
            {
                "role": "user",
                "content": observation_content,
            }
        )

    # Exhausted rounds — return whatever the last response was
    logger.warning("MCP tool loop exhausted max rounds; returning last LLM response")
    return content
