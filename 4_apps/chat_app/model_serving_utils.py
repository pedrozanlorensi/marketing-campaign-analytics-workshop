import logging
import requests
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


def _invoke_endpoint(endpoint_name: str, payload: dict) -> dict:
    """POST directly to the serving endpoint's invocations URL and return JSON.

    We bypass the mlflow deploy client / OpenAI client here: agent endpoints
    return a single JSON body at /invocations, but those wrappers assume a
    different response shape and fail with a JSONDecodeError. A plain request
    parses cleanly and works across all Databricks serving-endpoint versions.
    """
    w = WorkspaceClient()
    host = w.config.host
    if host and not host.startswith("http"):
        host = f"https://{host}"
    token = w.config.authenticate()["Authorization"].split(" ", 1)[1]
    url = f"{host}/serving-endpoints/{endpoint_name}/invocations"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()


def get_endpoint_task_type(endpoint_name: str) -> str:
    """Get the task type of a serving endpoint."""
    w = WorkspaceClient()
    ep = w.serving_endpoints.get(endpoint_name)
    return ep.task


def is_endpoint_supported(endpoint_name: str) -> bool:
    """Check if the endpoint has a supported task type."""
    task_type = get_endpoint_task_type(endpoint_name)
    supported_task_types = ["agent/v1/chat", "agent/v2/chat", "llm/v1/chat"]
    return task_type in supported_task_types


def query_endpoint(endpoint_name: str, messages: list[dict]) -> dict:
    """
    Query a Databricks serving endpoint with messages.
    
    Supports multiple response formats:
    - Standard ChatCompletions (choices)
    - Databricks agents (messages)
    - Custom multi-agent output format
    
    Returns a dict with role and content.
    """
    # Count assistant messages in the request (these may be echoed in response)
    assistant_messages_sent = sum(1 for msg in messages if msg.get('role') == 'assistant')
    
    # Log the request
    logger.info("=" * 80)
    logger.info("📤 REQUEST TO ENDPOINT: %s", endpoint_name)
    logger.info("Number of messages: %d", len(messages))
    logger.info("Assistant messages already sent: %d", assistant_messages_sent)
    logger.info("Messages being sent:")
    for i, msg in enumerate(messages):
        content_preview = msg.get('content', '')[:100]
        logger.info("  [%d] %s: %s%s", i, msg.get('role'), content_preview, 
                   '...' if len(msg.get('content', '')) > 100 else '')
    
    # Try standard format first, fallback to the Responses-API 'input' format.
    # Different endpoints signal the need for 'input' with different messages,
    # so detect it broadly rather than matching one exact string.
    def _needs_input_field(err: str) -> bool:
        err_l = err.lower()
        return (
            "model is missing inputs ['input']" in err_l
            or "'messages' field is not supported" in err_l
            or "use 'input'" in err_l
            or "use the 'input' field" in err_l
        )

    try:
        logger.info("Using input format: 'messages'")
        response = _invoke_endpoint(endpoint_name, {'messages': messages})
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else str(e)
        if _needs_input_field(body):
            logger.info("Retrying with input format: 'input'")
            response = _invoke_endpoint(endpoint_name, {'input': messages})
        else:
            raise
    
    # Log the raw response
    logger.info("-" * 80)
    logger.info("📥 RAW RESPONSE FROM ENDPOINT:")
    logger.info("Response type: %s", type(response).__name__)
    logger.info("Response keys: %s", list(response.keys()) if isinstance(response, dict) else 'N/A')
    logger.info("Response: %s", response)

    # Log response structure details
    if "output" in response:
        logger.info("Output array length: %d", len(response.get("output", [])))
        logger.info("Output items:")
        for i, item in enumerate(response.get("output", [])):
            logger.info("  [%d] type=%s, role=%s", i, 
                       item.get("type"), item.get("role", "N/A"))
    elif "choices" in response:
        logger.info("Choices format detected")
    elif "messages" in response:
        logger.info("Messages format detected, count: %d", len(response.get("messages", [])))
    
    # Parse response based on format
    parsed = _parse_response(response, assistant_messages_sent)
    
    # Log the parsed response
    logger.info("-" * 80)
    logger.info("✅ PARSED RESPONSE:")
    logger.info("Role: %s", parsed.get('role'))
    logger.info("Content length: %d characters", len(parsed.get('content', '')))
    logger.info("Content preview: %s...", parsed.get('content', '')[:200])
    logger.info("=" * 80)
    
    return parsed


def _parse_response(response: dict, assistant_messages_sent: int = 0) -> dict:
    """Parse different response formats and return a standardized message.
    
    Args:
        response: The response from the endpoint
        assistant_messages_sent: Number of assistant messages in the request (to skip echoed messages)
    """
    
    # Format 1: Databricks agent format with messages array
    if "messages" in response:
        return response["messages"][-1]
    
    # Format 2: Standard ChatCompletions with choices
    if "choices" in response:
        message = response["choices"][0]["message"]
        content = message.get("content")
        
        # Handle structured content (list of parts)
        if isinstance(content, list):
            text = "".join(
                part.get("text", "")
                for part in content
                if part.get("type") == "text"
            )
            return {"role": message.get("role"), "content": text}
        
        # Handle simple string content
        return message
    
    # Format 3: Custom multi-agent output format
    if "output" in response:
        logger.info("Parsing custom output format...")

        # The supervisor emits several assistant messages per turn: a preamble
        # ("I'll query..."), tool-result echoes (e.g. the raw Genie table, which
        # carry a `call_id`), routing metadata (`<name>...`), and finally the
        # synthesized natural-language answer. We only want that final answer,
        # so we keep the LAST assistant message that is not metadata and not a
        # tool result. This drops preambles and intermediate tables.
        final = None
        for i, item in enumerate(response["output"]):
            if item.get("type") != "message" or item.get("role") != "assistant":
                continue
            # Skip tool-result echoes (intermediate data such as Genie tables).
            if item.get("call_id"):
                logger.info("  [%d] skipped tool-result message (call_id present)", i)
                continue
            text = "".join(
                part.get("text", "")
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            )
            if not text or _is_metadata_message(text):
                continue
            final = text  # keep overwriting -> ends on the final answer

        messages = [{"role": "assistant", "content": final}] if final else []
        
        logger.info("Total assistant messages extracted: %d (after filtering)", len(messages))
        
        if messages:
            # Combine all messages with separators
            combined = "\n\n---\n\n".join(msg["content"] for msg in messages)
            logger.info("Combined message length: %d characters", len(combined))
            return {"role": "assistant", "content": combined}
    
    raise Exception(
        "Unsupported response format. This app supports:\n"
        "1. Standard ChatCompletions (choices)\n"
        "2. Databricks agents (messages)\n"
        "3. Custom multi-agent format (output)"
    )


def _is_metadata_message(text: str) -> bool:
    """Check if a message is metadata that should be filtered out."""
    text_lower = text.lower()
    return (
        text.strip().startswith("<name>") or
        "transferring" in text_lower or
        "successfully transferred" in text_lower
    )
