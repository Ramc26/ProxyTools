import os

from crewai import Agent, Crew, LLM, Task
from crewai.tools import tool

from studio_log import log_agent_step

from .tools import build_crewai_backstory, mcp_call, tools_catalog


async def run_crew_once(session, user_message, model, tool_log, steps, assistant_name):
    catalog = await tools_catalog(session["integrations"])
    step_counter = [0]

    @tool
    def mcp_call_tool(tool_name, arguments_json="{}"):
        import asyncio

        return asyncio.run(
            mcp_call(
                tool_name,
                arguments_json,
                tool_log,
                steps,
                step_counter,
                session,
            )
        )

    llm = LLM(model=model, api_key=os.getenv("OPENAI_API_KEY"))
    backstory = build_crewai_backstory(
        assistant_name,
        session["integrations"],
        catalog,
        session.get("gworkspace_email"),
    )

    log_agent_step(1, "llm_start", "crew kickoff", {"model": model})
    assistant = Agent(
        role="Personal Assistant",
        goal="Help the user using MCP integrations",
        backstory=backstory,
        llm=llm,
        tools=[mcp_call_tool],
        verbose=False,
    )
    task = Task(
        description="Reply to the user.\n\nUser: " + user_message,
        expected_output="Clear helpful answer.",
        agent=assistant,
    )
    result = Crew(agents=[assistant], tasks=[task], verbose=False).kickoff()
    return str(result), steps

