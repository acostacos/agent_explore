import json
from collections import OrderedDict
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from langchain_core.callbacks import BaseCallbackHandler
from bedrock_agentcore.runtime.context import BedrockAgentCoreContext
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from mcp_client.client import get_streamable_http_mcp_client
from digest import CHAT_SYSTEM_PROMPT, DIGEST_SYSTEM_PROMPT, run_weekly_digest

LangchainInstrumentor().instrument()

app = BedrockAgentCoreApp()
log = app.logger

_llm = None


def get_or_create_model():
    global _llm
    if _llm is None:
        _llm = load_model()
    return _llm


DEFAULT_SYSTEM_PROMPT = CHAT_SYSTEM_PROMPT

# Module-level checkpointer preserves conversation history across invocations (chat mode only).
# InMemorySaver keeps every thread_id (= session_id) checkpoint in memory
# forever, so we bound it to 128 active threads with LRU eviction (the
# least-recently-used thread is deleted and its history reset) to keep a
# long-running process from growing without limit. For durable history, swap in
# a persistent checkpointer (e.g. SqliteSaver/AsyncSqliteSaver with a file path).
_CHECKPOINT_LIMIT = 128
_checkpointer = InMemorySaver()
_thread_ids = OrderedDict()


def touch_thread(thread_id):
    if thread_id in _thread_ids:
        _thread_ids.move_to_end(thread_id)
        return
    while len(_thread_ids) >= _CHECKPOINT_LIMIT:
        evicted, _ = _thread_ids.popitem(last=False)
        _checkpointer.delete_thread(evicted)
    _thread_ids[thread_id] = True


class ConfigBundleCallback(BaseCallbackHandler):
    """Injects config bundle values into LangGraph agent at runtime.

    BedrockAgentCoreContext.get_config_bundle() fetches the component configuration
    for the current runtime ARN from the config bundle service. The SDK caches the
    result and refreshes on bundle version changes.
    """

    def on_chain_start(self, serialized: dict, inputs: dict, **kwargs: Any) -> None:
        config = BedrockAgentCoreContext.get_config_bundle()
        prompt = config.get("systemPrompt", DEFAULT_SYSTEM_PROMPT)

        messages = inputs.get("messages", [])
        if messages and isinstance(messages[0], SystemMessage):
            messages[0] = SystemMessage(content=prompt)
        else:
            messages.insert(0, SystemMessage(content=prompt))
        inputs["messages"] = messages


async def load_tools() -> list:
    """Load the research tools (Brave Search, arXiv) exposed through the AgentCore Gateway."""
    mcp_client = get_streamable_http_mcp_client()
    if not mcp_client:
        return []
    return await mcp_client.get_tools()


async def build_digest_graph():
    """A fresh, checkpointer-less agent with the digest system prompt (not overridden by the config bundle)."""
    return create_react_agent(get_or_create_model(), tools=await load_tools(), prompt=DIGEST_SYSTEM_PROMPT)


async def run_chat(payload, context):
    graph = create_react_agent(
        get_or_create_model(),
        tools=await load_tools(),
        prompt=DEFAULT_SYSTEM_PROMPT,
        checkpointer=_checkpointer,
    )
    callback = ConfigBundleCallback()

    # Process the user prompt
    prompt = payload.get("prompt", "What can you help me with?")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    session_id = getattr(context, "session_id", "default-session")
    touch_thread(session_id)
    log.info(f"Agent input: {prompt}")

    # Run the agent with config bundle callback (checkpointer auto-loads/saves history per session)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=prompt)]},
        config={"callbacks": [callback], "configurable": {"thread_id": session_id}},
    )

    # Return result
    output = result["messages"][-1].content
    log.info(f"Agent output: {output}")
    return {"result": output}


def normalize_payload(payload: dict) -> dict:
    """`agentcore invoke '<json>'` wraps its argument as {"prompt": "<json>"}; unwrap digest requests sent that way."""
    prompt = payload.get("prompt")
    if "mode" not in payload and isinstance(prompt, str) and prompt.lstrip().startswith("{"):
        try:
            inner = json.loads(prompt)
        except ValueError:
            return payload
        if isinstance(inner, dict) and inner.get("mode") == "weekly_digest":
            return inner
    return payload


@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent.....")
    payload = normalize_payload(payload)

    if payload.get("mode") == "weekly_digest":
        dry_run = payload.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        log.info(f"Running weekly digest (dry_run={dry_run})")
        return await run_weekly_digest(build_digest_graph, dry_run=dry_run)

    return await run_chat(payload, context)


if __name__ == "__main__":
    app.run()
