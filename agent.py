"""
agent.py

Main orchestration script for the Multi-Agent System using Google ADK.
- Loads environment variables and sub-agents.
- Defines a master planner agent to generate execution plans.
- Implements a dynamic orchestrator to run sub-agents in sequence.
- Sets up the runner and session for the application.
"""

# --- Import Statements ---
import sys
import os
from dotenv import load_dotenv
import json
from typing import AsyncGenerator, List
from typing_extensions import override
from google.adk.agents import BaseAgent, SequentialAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
import json
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

# --- Constants ---
APP_NAME = "google_adk_app"
USER_ID = "12345"
SESSION_ID = "123344"
PLANNER_MODEL_NAME = "gemini-2.0-flash"

# --- Environment Setup ---
print("Attempting to load .env file from coordinator_file.py...")
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print(f".env file found at {dotenv_path} and loaded.")
    # ... (API key checks) ...
else:
    print(f"⚠️ .env file not found at {dotenv_path}.")

# Add the current directory to sys.path to allow local imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- Sub-Agent Imports ---
from sub_agents import launches_agent, weather_agent, summarizer_agent, news_agent
 
# --- Master Planner Agent ---
MASTER_PLANNER_INSTRUCTION = """
You are a master AI task planner. Your goal is to take the user's current query and break it down into an ordered sequence of tasks that can be performed by specialized sub-agents.

Available Sub-Agents and their functions:
- 'launches_agent': Provides specific details about rocket launches.
- 'weather_agent': Provides weather forecasts for a specific location and date.
- 'news_agent': Fetches relevant news articles based on keywords, sources, domains, dates, etc. Use this if the query asks for news, articles, updates on a topic, or current events.
- 'summarizer_agent': Consolidates and presents all gathered information. (Must always be passed at the end of Output Plan at all cost)

Based on the user's current query, determine the necessary sequence of sub-agents to call.
Your output MUST be a list of strings, where each string is the exact name of the sub-agent to be called in order.

Examples:
- If the user's current query is "What's the next SpaceX launch and the weather for it?",
  Output Plan: ["launches_agent", "weather_agent", "summarizer_agent"]
- If the user's current query is "Give some news about space launches?"
  Output Plan: ["news_agent", "summarizer_agent"]
- If the user's current query is "Some news on the latest SpaceX launch.",
  Output Plan: ["launches_agent", "news_agent", "summarizer_agent"]
- If the user's current query is "What's the next SpaceX launch, what's the weather for it, any news going around it?",
  Output Plan: ["launches_agent", "weather_agent", "news_agent", "summarizer_agent"]
- If the user's current query is "Weather in Paris tomorrow?",
  Output Plan: ["weather_agent", "summarizer_agent"]
- If the user's current query is anything outside the scope of the available sub-agents,
  Output Plan: ["summarizer_agent"]

Consider ONLY the most recent user query to make your plan.

Output Plan (JSON list of agent names):
"""
master_planner_agent = LlmAgent(
    model=PLANNER_MODEL_NAME,
    name="MasterPlannerAgent",
    instruction=MASTER_PLANNER_INSTRUCTION,
    description="Analyzes user query and creates an execution plan string.",
    output_key="agent_execution_plan_str" # Output is the JSON string of the plan
)
print(f"✅ MasterPlannerAgent '{master_planner_agent.name}' created.")

# --- Dynamic Orchestrator Agent ---
class DynamicOrchestratorAgent(BaseAgent):
    """
    Reads a JSON list of agent-names from ctx.session.state['agent_execution_plan_str'],
    then runs each named sub-agent in sequence, carrying forward the entire session state
    (including the original user query).
    """

    # Declare each possible sub-agent as a field so Pydantic can wire them up:
    launches_agent: LlmAgent
    weather_agent:  LlmAgent
    summarizer_agent:  LlmAgent
    news_agent: LlmAgent
    # …and any others (if adding more sub-agents in the future, add them here)

    model_config = {"arbitrary_types_allowed": True}

    def __init__(
        self,
        name: str,
        launches_agent: LlmAgent,
        weather_agent: LlmAgent,
        summarizer_agent: LlmAgent,
        news_agent: LlmAgent
        # …pass any future agents here too
    ):
        # Build the list of sub_agents for the ADK framework:
        sub_agents_list = [launches_agent, weather_agent, news_agent, summarizer_agent]
        super().__init__(
            name=name,
            launches_agent=launches_agent,
            weather_agent=weather_agent,
            news_agent=news_agent,
            summarizer_agent=summarizer_agent,
            sub_agents=sub_agents_list,
        )
        
    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
       
        # 1) Parse the plan string into a Python list
        plan_str = ctx.session.state.get("agent_execution_plan_str", "[]")
        try:
            plan: List[str] = json.loads(plan_str)
        except json.JSONDecodeError:
            # If plan is malformed, bail out
            return

        # 2) For each agent name in the plan, look up the attribute and invoke it
        for agent_name in plan:
            agent = getattr(self, agent_name, None)
            if agent is None:
                # optionally log or yield an error event here
                continue

            # Yield all events from that agent
            async for event in agent.run_async(ctx):
                yield event


orchestrator_agent = DynamicOrchestratorAgent(
    name="DynamicOrchestratorAgent",
    launches_agent = launches_agent,
    weather_agent =  weather_agent,
    news_agent = news_agent,
    summarizer_agent = summarizer_agent,
)


# --- Runner and Session Setup ---
session_service = InMemorySessionService()

session = session_service.create_session(
    app_name=APP_NAME,
    user_id=USER_ID,
    session_id=SESSION_ID,
)
      
root_agent = SequentialAgent(
    name="RootPlannerOrchestrator",
    description="Orchestrates the master planner and sub-agents to fulfill user queries.",
    sub_agents=[master_planner_agent, orchestrator_agent],
)

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service
)