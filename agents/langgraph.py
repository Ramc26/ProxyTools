from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from studio_log import (
    log,
    log_agent_llm,
    log_agent_step,
)

from .tools import (
    build_langgraph_system_prompt,
    make_langchain_mcp_tool,
    make_llm,
    message_text,
    preview_text,
    tools_catalog,
)

MEMORY = MemorySaver()


def _steps_from_messages(new_messages, model, step_no, steps):
    for msg in new_messages:
        if isinstance(msg, AIMessage):
            if getattr(msg, "tool_calls", None):
                for call in msg.tool_calls:
                    step_no[0] = step_no[0] + 1
                    n = step_no[0]
                    name = call.get("name", "unknown")
                    steps.append(
                        {
                            "step": n,
                            "type": "thinking",
                            "detail": "Calling " + name,
                            "model": model,
                        }
                    )
                    log_agent_step(n, "thinking", "plan → " + name, {"model": model})
            elif msg.content:
                text = message_text(msg.content)
                if text.strip():
                    step_no[0] = step_no[0] + 1
                    n = step_no[0]
                    steps.append(
                        {
                            "step": n,
                            "type": "reply",
                            "model": model,
                            "preview": preview_text(text, 120),
                        }
                    )
                    log_agent_step(n, "reply", preview_text(text, 80), {"model": model})
        elif isinstance(msg, ToolMessage):
            step_no[0] = step_no[0] + 1
            n = step_no[0]
            steps.append(
                {
                    "step": n,
                    "type": "tool_message",
                    "tool": msg.name or "mcp_call",
                    "preview": preview_text(message_text(msg.content)),
                }
            )


async def run_langgraph_once(session, user_message, model, tool_log, steps, assistant_name):
    step_no = [0]
    catalog = await tools_catalog(session["integrations"])
    mcp_tool = await make_langchain_mcp_tool(tool_log, steps, step_no, session)
    graph = create_react_agent(make_llm(model), [mcp_tool], checkpointer=MEMORY)
    config = {"configurable": {"thread_id": session["id"]}}

    messages = [HumanMessage(content=user_message)]
    if not session.get("started"):
        prompt = build_langgraph_system_prompt(
            assistant_name,
            session["integrations"],
            catalog,
            session.get("gworkspace_email"),
        )
        messages.insert(0, SystemMessage(content=prompt))
        session["started"] = True

    step_no[0] = step_no[0] + 1
    n = step_no[0]
    steps.append({"step": n, "type": "llm_start", "model": model})
    log_agent_step(n, "llm_start", "processing user message", {"model": model})
    log_agent_llm(model, "invoke")

    reply = ""
    async for update in graph.astream({"messages": messages}, config, stream_mode="updates"):
        for node, data in update.items():
            new_msgs = data.get("messages") or []
            log.info("  · graph node: %s (%d message(s))", node, len(new_msgs))
            _steps_from_messages(new_msgs, model, step_no, steps)
            for msg in new_msgs:
                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                    reply = message_text(msg.content)

    if not reply:
        state = await graph.aget_state(config)
        messages_state = state.values.get("messages", [])
        for msg in reversed(messages_state):
            if isinstance(msg, AIMessage) and msg.content:
                reply = message_text(msg.content)
                break

    return reply, steps

