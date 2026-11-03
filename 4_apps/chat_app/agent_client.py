"""Call the Agent Bricks agent deployed by `agentbricks deploy` (stage 3).

The agent runs as its own Databricks App (`agent-bricks-<name>`) and exposes the Agent Bricks
invocation API at `<agent-app-url>/api/invocations`. This module:

- resolves the agent app's URL from its name,
- authenticates with this app's own service principal (OAuth M2M, injected by Databricks Apps),
- sends one user turn per request with a stable `session_id`, so the agent's managed session
  store keeps the conversation history (no need to resend earlier messages),
- returns the agent's final answer text.
"""

import logging
import uuid
from functools import lru_cache

import requests
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _workspace_client() -> WorkspaceClient:
    return WorkspaceClient()


@lru_cache(maxsize=8)
def get_agent_url(agent_app_name: str) -> str:
    """Base URL of the deployed agent app, for example https://agent-bricks-x-123.azure.databricksapps.com."""
    app = _workspace_client().apps.get(name=agent_app_name)
    if not app.url:
        raise RuntimeError(f"Agent app '{agent_app_name}' has no URL yet. Is it deployed and running?")
    return app.url.rstrip("/")


def _auth_headers() -> dict:
    # authenticate() returns {"Authorization": "Bearer <oauth token>"} and refreshes as needed.
    return _workspace_client().config.authenticate()


def query_agent(agent_app_name: str, session_id: str, user_message: str) -> str:
    """Send one user turn to the agent and return its final answer."""
    payload = {
        "id": str(uuid.uuid4()),  # a fresh invocation id per turn
        "session_id": session_id,  # stable per chat, so the agent remembers earlier turns
        "input": {"messages": [{"role": "user", "content": user_message}]},
    }
    url = f"{get_agent_url(agent_app_name)}/api/invocations"
    logger.info("POST %s session=%s", url, session_id)
    resp = requests.post(
        url,
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=300,
    )
    resp.raise_for_status()
    return _final_answer(resp.json())


def _messages(body: dict) -> list:
    """The adapter returns {"output": [...messages], "status": ...}, under the server's `output`."""
    output = body.get("output", body)
    if isinstance(output, dict):
        output = output.get("output", [])
    return output if isinstance(output, list) else []


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return ""


def _final_answer(body: dict) -> str:
    """Return the last AI message with text and no pending tool calls (skips tool results)."""
    for message in reversed(_messages(body)):
        if not isinstance(message, dict) or message.get("type") not in ("ai", "AIMessageChunk"):
            continue
        if message.get("tool_calls"):
            continue
        text = _text(message.get("content")).strip()
        if text:
            return text
    logger.warning("No final answer found in agent response: %s", body)
    return "The agent did not return an answer. Please try again."
