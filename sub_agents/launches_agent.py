#%%

# Import necessary libraries
from typing import Any, Dict, List
from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext
import warnings
# Ignore all warnings
warnings.filterwarnings("ignore")
import logging
logging.basicConfig(level=logging.ERROR)
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import random
import time

print("Libraries imported.")

# Create a new agent for handling launch information queries

MODEL_GEMINI_2_0_FLASH = "gemini-2.0-flash"

# Step 1: Get free proxies from a public site
def get_free_proxies():
    print("🔍 Fetching free proxies...")
    url = "https://free-proxy-list.net/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    proxies = []

    table = soup.find("table", class_="table table-striped table-bordered")
    if table is None:
        print("❌ Could not find proxy table. Site might have changed again.")
        return proxies

    for row in table.tbody.find_all("tr"):
        cols = row.find_all("td")
        ip = cols[0].text.strip()
        port = cols[1].text.strip()
        https = cols[6].text.strip().lower()  # Yes/No column for HTTPS
        if https == "yes":
            proxies.append(f"http://{ip}:{port}")

    print(f"✅ Found {len(proxies)} HTTPS proxies.")
    return proxies

# Step 2: Fetch a URL using rotating proxies & User-Agents
def fetch_with_rotation(url, proxies, params=None, max_retries=30):
    ua = UserAgent()
    tried = set()

    for _ in range(max_retries):
        proxy = random.choice(proxies)
        if proxy in tried:
            continue
        tried.add(proxy)

        headers = {
            "User-Agent": ua.random,
            "Accept": "application/json"
        }

        try:
            print(f"🌐 Trying proxy: {proxy}")
            response = requests.get(url, headers=headers, proxies={"http": proxy, "https": proxy}, timeout=10, params=params)

            if response.status_code == 200:
                print("✅ Success!")
                return response.json()
            elif response.status_code == 429:
                print("⚠️ Rate limit. Sleeping...")
                time.sleep(60)
            else:
                print(f"⚠️ Unexpected status: {response.status_code}")
        except Exception as e:
            print(f"❌ Failed proxy {proxy}: {e}")

        # Random delay to simulate human behavior
        time.sleep(random.uniform(3, 6))

    print("🚫 All proxies failed or max retries reached.")
    return None

# Step 3: Dynamic launch info fetcher
def fetch_launch_info(tool_context: ToolContext, agency: str = "spacex", time_filter: str = "upcoming", count: int = 1) -> List[Dict[str, Any]]:
    """
    Fetches launch information from the SpaceDev API based on agency and time filter.
    
    Parameters:
    - tool_context (ToolContext): The context for the tool, including state management.
    - agency (str): The space agency to filter launches by (default: "spacex"), e.g., "spacex", "nasa", "isro", etc.
    - time_filter (str): Filter for launch time ("upcoming", "past", "first").
    - count (int): Number of launches to retrieve (default: 1).
    
    Returns:
    - List of launch information dictionaries.
    - Each dictionary contains:
        - name (str): Launch name.
        - launch_date (str): Launch date.
        - location_name (str): Launch location.
        - latitude (float): Launch pad latitude.
        - longitude (float): Launch pad longitude.
        - status (str): Launch status description.
        - failreason (str): Reason for failure, if any.
        - mission_description (str): Description of the mission.
    """
    
    proxies = get_free_proxies()
    if not proxies:
        return
    
    base_url = "https://ll.thespacedevs.com/2.2.0/launch/"
    params = {
        "search": agency.lower(),
        "limit": count,
        "ordering": "net"
    }

    if time_filter == "upcoming":
        endpoint = "upcoming/"
        params["ordering"] = "net"
    elif time_filter == "past":
        endpoint = "previous/"
        params["ordering"] = "-net"
    elif time_filter == "first":
        endpoint = ""
        params["ordering"] = "net"
        params["limit"] = count
    else:
        raise ValueError("Invalid time_filter. Choose from 'upcoming', 'past', 'first'.")

    full_url = base_url + endpoint
    print(f"📡 Querying: {full_url} with params: {params}")

    json_data = fetch_with_rotation(full_url, proxies, params=params)
    if not json_data:
        tool_context.state['launch_info_retrieval_status'] = 'failure_api_call'
        return []

    results = json_data.get("results", [])
    launches = []

    for launch in results:
        pad = launch.get("pad", {})
        location = pad.get("location", {})
        status = launch.get("status", {})
        mission = launch.get("mission", {})
        launches.append({
            "name": launch.get("name"),
            "launch_date": launch.get("net")[:10],  # Extract date part from datetime
            "location_name": location.get("name"),
            "latitude": pad.get("latitude"),
            "longitude": pad.get("longitude"),
            "status": status.get("description"),
            "failreason": launch.get("failreason"),
            "mission_description": mission.get("description")
        })
        
    tool_context.state['launch_info'] = launches

    return launches

# %%
launches_agent = None
LAUNCH_AGENT_INSTRUCTION = """
You are a highly specialized Launch Information Agent. Your **sole and mandatory primary function** is to provide specific, factual data about rocket launches, space missions, and launch schedules. You do not engage in general conversation or provide information outside of this scope.

**For ANY user query asking for launch information (e.g., details about upcoming, past, first launches, specific agency launches, or number of launches), you MUST use the 'fetch_launch_info' tool to retrieve the data before formulating a response.** Do not attempt to use your general knowledge. Remember to not to display anything to the user as your response would always be passed to the next agent for summarization. That agent would deal with displaying the information to the user.

Follow these rules for using the 'fetch_launch_info' tool:
- If the user specifies the name of a specific agency (e.g., SpaceX, NASA, ISRO), pass it as the 'agency' parameter to the tool (e.g., agency='spacex'). If no agency is specified, you may use a default like 'spacex' or omit it if the tool handles that.
- If the user requests info about upcoming launches, pass 'upcoming' as the 'time_filter' parameter.
- If the user requests info about recent or past launches, pass 'past' as the 'time_filter' parameter.
- If the user requests info about first or initial launches, pass 'first' as the 'time_filter' parameter.
- If the user specifies a number of launches to retrieve (e.g., "5 launches", "two recent launches"), pass this number as the 'count' parameter (e.g., count=5). If no count is specified, assume count=1 for specific queries or a reasonable default (e.g., 3-5) for general upcoming/past lists if appropriate for the tool.

After the 'fetch_launch_info' tool returns data, strictly just send it further to the next agent to be interacted with rather than showing an output to the user. If the tool returns no data or an error, state that you could not retrieve the specific launch information.

Simply show a success message if the tool call was successful stating "Launch Information Fetched Successfully", or if the recent session state 'launch_info' is empty, state "No Launch Information Available." or an error message if it failed. Do not show any other information to the user.

**Remember to always call the 'fetch_launch_info' tool exactly once and not more than that.**

Under no circumstances should you provide information about topics other than rocket launches, space missions, and schedules, nor should you attempt to answer launch queries without first invoking the 'fetch_launch_info' tool.
"""

try:
    launches_agent = LlmAgent(
        # Using a potentially different/cheaper model for a simple task
        model = MODEL_GEMINI_2_0_FLASH,
        name="launches_agent",
        instruction=LAUNCH_AGENT_INSTRUCTION,
        description="Handles rocket launch information queries using the 'fetch_launch_info' tool.", # Crucial for delegation
        tools=[fetch_launch_info],  # Register the tool
    )
    print(f"✅ Agent '{launches_agent.name}' created using model '{launches_agent.model}'.")
except Exception as e:
    print(f"❌ Could not create Launch Info agent. Check API Key ({launches_agent.model}). Error: {e}")
