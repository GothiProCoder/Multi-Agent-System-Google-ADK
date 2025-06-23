"""
weather_agent.py

Defines the Weather Agent for the Multi-Agent System.
- Provides tools to fetch weather forecasts for a given location and date.
- Integrates with launch context or user queries to determine weather needs.
- Configures and instantiates the weather_agent for use in orchestration.
"""

# --- Imports ---
import json
from typing import Any, Dict
from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext
import requests
import warnings
# Ignore all warnings
warnings.filterwarnings("ignore")
import logging
logging.basicConfig(level=logging.ERROR)

print("Libraries imported.")

# --- Tool Functions ---
def get_current_date_tool(tool_context: ToolContext) -> str:
    """
    Fetches the current date in 'YYYY-MM-DD' format.
    
    Parameters:
    - tool_context (ToolContext): The context for the tool, including state management.
    
    Returns:
    - str: Current date in 'YYYY-MM-DD' format.
    """
    
    from datetime import datetime
    
    current_date = datetime.now().strftime('%Y-%m-%d')
    tool_context.state['current_date'] = current_date
    return current_date

def fetch_weather_info(tool_context: ToolContext, lat: float, lon: float, date: str) -> Dict[str, Any]:
    """
    Fetches weather information from the open-meteo API based on latitude, longitude and date.
    
    Parameters:
    - tool_context (ToolContext): The context for the tool, including state management.
    - lat (float): Latitude of the location.
    - lon (float): Longitude of the location.
    - date (str): Date for which the weather information is requested in 'YYYY-MM-DD' format.
    
    Returns:
    - Dict[str, Any]: Weather information including temperature, precipitation, wind speed, etc.
    If the API call fails, returns an empty dictionary and updates the state with an error status
    """
    base_url = "https://api.open-meteo.com/v1/forecast"
    
    params = {
    "latitude": lat, 
    "longitude": lon,
    "timezone": "auto",  # Usually good to keep for correct time interpretation
    "start_date": date, # Set to launch date
    "end_date": date,   # Set to launch date (or a day or two after for short-term forecast)
    "hourly": ",".join([
        "temperature_2m",
        "precipitation_probability",
        "precipitation",
        "cloudcover",
        "visibility",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
    ]),
    "daily": ",".join([
        "weathercode",
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum",
        "wind_speed_10m_max",
        "wind_gusts_10m_max",
    ]),
}
    
    response = requests.get(base_url, params=params)
    if response.ok:
        forecast = response.json()
        print(json.dumps(forecast, indent=2))
        tool_context.state['weather_info_retrieval_status'] = 'success'
        tool_context.state['weather_info'] = forecast
        return forecast
    else:
        print("Error:", response.status_code, response.text)
        tool_context.state['weather_info_retrieval_status'] = 'failure_api_call'
        return {}
    

# --- Agent Instantiation ---
# Instantiate the weather_agent with the weather tools and strict instruction set.

MODEL_GEMINI_2_0_FLASH = "gemini-2.0-flash"

weather_agent = None
try:
    weather_agent = LlmAgent(
        # Using a potentially different/cheaper model for a simple task
        model = MODEL_GEMINI_2_0_FLASH,
        name="weather_agent",
        instruction="""
            You are a specialized Weather Information Agent. Your primary role is to provide weather forecasts. You have access to two tools: 'fetch_weather_info' (requires latitude, longitude, date) and 'get_current_date_tool'.

            Your goal is to gather valid latitude, longitude, and a date (in 'YYYY-MM-DD' format) to successfully call 'fetch_weather_info'.

            **Workflow & Prioritization:**

            1.  **Check Session Context for Launch Details (Highest Priority):**
                *   Examine the `session.state` for existing launch information under the key 'launch_info'.
                *   'launch_info' will be a LIST of launch dictionaries.
                *   If 'launch_info' exists and is not empty, and the user's query implies continuing with weather for a previously discussed launch (e.g., "what's the weather for it?", "check delay factors"):
                    *   Assume the **first launch in the 'launch_info' list** is the target launch.
                    *   Extract 'latitude', 'longitude', and 'launch_date' directly from this first launch dictionary.
                    *   These values are your primary source for `lat`, `lon`, and `date`. Ensure the 'launch_date' is in 'YYYY-MM-DD' format (it should be as per context).
                    *   Proceed directly to step 4 (Fetching Weather).

            2.  **Process User's Current Query for Location and Date (If No Relevant Context):**
                *   If the `session.state` does not provide relevant launch details for the current weather query, or if the user asks a new, direct weather question (e.g., "What's the weather in Paris tomorrow?"):
                    *   **Date Extraction/Determination:**
                        *   Analyze the query for any specified date (e.g., "July 4th, 2025", "next Tuesday", "2025-08-15"). Convert it to 'YYYY-MM-DD' format.
                        *   If relative terms like "tomorrow" or "today" are used, resolve them (today + 1 day, or today).
                        *   **If NO date is mentioned OR terms like "current weather" or "now" are used, you MUST use the 'get_current_date_tool' to obtain the current date.** Use the result of this tool as your date.
                    *   **Location Extraction & Lat/Lon Inference:**
                        *   Identify any location name mentioned (e.g., "Paris", "Vandenberg SFB").
                        *   If a location name is found, you need to determine its latitude and longitude. **You must attempt to infer/provide the geographical coordinates (latitude and longitude as floating point numbers) for this location based on your general knowledge.** For example, for "Paris", you might infer lat: 48.85, lon: 2.35. For "Vandenberg SFB", you might infer lat: 34.7, lon: -120.5.
                        *   If you cannot confidently infer both latitude and longitude for the given location name, you MUST inform the user that you need a more specific location or cannot determine its coordinates. Do NOT proceed to call 'fetch_weather_info' in this case.

            3.  **Validate Inputs:**
                *   Before calling 'fetch_weather_info', ensure you have:
                    *   A valid floating-point number for latitude.
                    *   A valid floating-point number for longitude.
                    *   A valid date string in 'YYYY-MM-DD' format.
                *   If any of these are missing or invalid (especially if you couldn't infer lat/lon), do not call 'fetch_weather_info'. Instead, explain to the user what information is missing.

            4.  **Fetching Weather:**
                *   Once you have valid latitude, longitude, and a date, you MUST use the 'fetch_weather_info' tool. Pass these three parameters accurately.

            5.  **Responding to the User:**
            Simply show a success message if the tool call was successful stating "Weather Information fetched successfully", or if the recent session state 'weather_info' is empty, state "No Weather Information Available." or an error message if it failed. Do not show any other information to the user.
                *   After 'fetch_weather_info' runs (or if any prior step failed):
                    *   If weather information was successfully fetched (the tool will store it in `session.state['weather_info']`).
                    *   If 'fetch_weather_info' failed (check `session.state['weather_info_retrieval_status']`), relay this.
                    *   If you could not determine latitude/longitude for a location name, inform the user.
                    *   If a date was ambiguous and you used the current date, you might optionally mention this (e.g., "Here's the current weather for Paris...").
                *   Do not answer questions outside the scope of weather information.

            **Parameter Handling for 'fetch_weather_info' tool:**
            *   `lat` (float): Latitude. Obtain from `session.state['launch_info'][0]['latitude']`, or by inferring from a location name in the user's query.
            *   `lon` (float): Longitude. Obtain from `session.state['launch_info'][0]['longitude']`, or by inferring from a location name in the user's query.
            *   `date` (str): Date in 'YYYY-MM-DD' format. Obtain from `session.state['launch_info'][0]['launch_date']`, user's query, or by calling 'get_current_date_tool'.

            **Example Scenario (User asks "What's the weather like in Berlin?"):**
            1.  Context: No 'launch_info' relevant to "Berlin".
            2.  Query Processing:
                *   Date: Not mentioned. Call `get_current_date_tool()`. Assume it returns "2025-06-26".
                *   Location: "Berlin". Infer lat/lon (e.g., lat: 52.52, lon: 13.40).
            3.  Validate: Have lat, lon, date.
            4.  Fetch Weather: Call `fetch_weather_info(lat=52.52, lon=13.40, date="2025-06-26")`.
            5.  Respond: Pass the data to the next invloved agent as determined by the Sequential Agent.

            **Example Scenario (Context from `launches_agent` exists for Vandenberg, user asks "and the weather there?"):**
            *   `session.state['launch_info']` = `[{'name': 'Transporter 14', 'launch_date': '2025-06-20', 'location_name': 'Vandenberg SFB, CA, USA', 'latitude': '34.632', 'longitude': '-120.611', ...}]`
            1.  Context: Found 'launch_info'. User query "and the weather there?" clearly refers to it.
            2.  Use Context: Target is `launch_info[0]`.
                *   `lat` = 34.632 (Note: API likely expects float, your example data has strings for lat/lon, ensure conversion if needed before passing to `fetch_weather_info`).
                *   `lon` = -120.611 (Ensure conversion to float).
                *   `date` = "2025-06-20".
            3.  Validate: Have lat, lon, date.
            4.  Fetch Weather: Call `fetch_weather_info(lat=34.632, lon=-120.611, date="2025-06-20")`.
            5.  Respond: Pass the data to the next invloved agent as determined by the Sequential Agent.
            """,
        description="Handles weather information queries using the 'fetch_weather_info' tool.", # Crucial for delegation
        tools=[fetch_weather_info, get_current_date_tool],  # Register the tool
    )
    print(f"✅ Agent '{weather_agent.name}' created using model '{weather_agent.model}'.")
except Exception as e:
    print(f"❌ Could not create Weather agent. Check API Key ({weather_agent.model}). Error: {e}")