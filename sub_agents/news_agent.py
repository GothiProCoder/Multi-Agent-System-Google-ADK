#%%

# Import necessary libraries
from typing import Any, Dict, List, Optional
import os
from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext
import warnings
# Ignore all warnings
warnings.filterwarnings("ignore")
import logging
logging.basicConfig(level=logging.ERROR)
import requests

print("Libraries imported.")

# Create a new agent for handling launch information queries

MODEL_GEMINI_2_0_FLASH = "gemini-2.0-flash"

# Step 3: Dynamic launch info fetcher
def fetch_news_articles(
    tool_context: ToolContext,
    q: Optional[str] = None,
    searchIn: str = "title",
    sources: Optional[str] = None,       # Comma-separated string of source IDs
    domains: Optional[str] = None,       # Comma-separated string of domains
    exclude_domains: Optional[str] = None,
    from_date: Optional[str] = None,     # ISO 8601 format, e.g., "2025-06-21" or "2025-06-21T10:00:00"
    to_date: Optional[str] = None,       # ISO 8601 format
    language: Optional[str] = None,      # 2-letter ISO-639-1 code
    sort_by: Optional[str] = "publishedAt", # 'relevancy', 'popularity', 'publishedAt'
    page_size: int = 10,                 # Default to a reasonable number
    page: int = 1
) -> List[Dict[str, Any]]:
    """
    Fetches news articles from NewsAPI based on various criteria determined by the LLM.

    Parameters:
    - tool_context (ToolContext): Context object.
    - q (Optional[str]): Keywords or phrases to search for.
    - searchIn (str): Set to "title" to search only in article titles.
    - sources (Optional[str]): Comma-separated source IDs.
    - domains (Optional[str]): Comma-separated domains to search.
    - exclude_domains (Optional[str]): Comma-separated domains to exclude.
    - from_date (Optional[str]): Start date for articles (ISO 8601).
    - to_date (Optional[str]): End date for articles (ISO 8601).
    - language (Optional[str]): 2-letter language code.
    - sort_by (Optional[str]): Order of articles ('relevancy', 'popularity', 'publishedAt').
    - page_size (int): Number of results per page.
    - page (int): Page number.

    Returns:
    - List of dictionaries, each representing a news article.
    """
    print(f"TOOL (news_agent.py): fetch_news_articles called with q='{q}', sources='{sources}', domains='{domains}', etc.")
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        print("❌ NEWS_API_KEY not found in environment variables.")
        tool_context.state['news_info_retrieval_status'] = 'failure_missing_api_key'
        tool_context.state['news_articles'] = []
        return []

    base_url = "https://newsapi.org/v2/everything" # Or /v2/top-headlines if more appropriate for some queries

    api_params = {
        "searchIn": searchIn,  # Always set to "title" as per the requirement
        "apiKey": api_key,
        "pageSize": page_size,
        "page": page
    }

    if q: api_params["q"] = q
    if sources: api_params["sources"] = sources
    if domains: api_params["domains"] = domains
    if exclude_domains: api_params["excludeDomains"] = exclude_domains
    if from_date: api_params["from"] = from_date
    if to_date: api_params["to"] = to_date
    if language: api_params["language"] = language
    if sort_by: api_params["sortBy"] = sort_by
    
    # Remove None values to avoid sending empty parameters
    api_params = {k: v for k, v in api_params.items() if v is not None}

    print(f"📡 Querying NewsAPI: {base_url} with params: {api_params}")

    articles_to_return = []
    try:
        # Replace this with your fetch_with_rotation if you integrate it
        response = requests.get(base_url, params=api_params, timeout=10)
        response.raise_for_status() # Raise an exception for HTTP errors
        json_data = response.json()

        if json_data.get("status") == "ok":
            raw_articles = json_data.get("articles", [])
            for article_data in raw_articles:
                articles_to_return.append({
                    "source_name": article_data.get("source", {}).get("name", "N/A"),
                    "author": article_data.get("author"),
                    "title": article_data.get("title"),
                    "description": article_data.get("description"),
                    "url": article_data.get("url"),
                    "urlToImage": article_data.get("urlToImage"),
                    "publishedAt": article_data.get("publishedAt"), # Full timestamp
                    "published_date": article_data.get("publishedAt")[:10] if article_data.get("publishedAt") else "", # Simple date
                    "content_snippet": article_data.get("content") # Truncated content
                })
            tool_context.state['news_info_retrieval_status'] = 'success'
            tool_context.state['news_articles'] = articles_to_return # Store the list of dicts
            print(f"TOOL (news_agent.py): fetch_news_articles stored {len(articles_to_return)} articles in state.")
        else:
            error_message = json_data.get("message", "Unknown API error")
            print(f"❌ NewsAPI returned error: {error_message}")
            tool_context.state['news_info_retrieval_status'] = f'failure_api_error: {error_message}'
            tool_context.state['news_articles'] = []
            
    except requests.exceptions.RequestException as e:
        print(f"❌ API Request Error for NewsAPI: {e}")
        tool_context.state['news_info_retrieval_status'] = f'failure_request_exception: {str(e)}'
        tool_context.state['news_articles'] = []
    except Exception as e:
        print(f"❌ An unexpected error occurred in fetch_news_articles: {e}")
        tool_context.state['news_info_retrieval_status'] = f'failure_unexpected: {str(e)}'
        tool_context.state['news_articles'] = []
        
    return articles_to_return

# %%
news_agent = None
NEWS_AGENT_INSTRUCTION = """
You are the News Information Agent. **Your sole mission is to call the `fetch_news_articles` tool exactly one time**.
   
Strict information:
1. Call the `fetch_news_articles` tool exactly once.
2. Remember to strictly refer to only the latest user's query.
3. Simply show a success message if the tool call was successful stating "News Articles Fetched Successfully", or if the recent session state 'news_articles' is empty, state "No relevant Articles Found." or an error message if it failed. Do not show any other information to the user.
4. Just store the results from the function tool in the session state ['news_articles']. Do not do anything else.

   - If `session.state["launch_info_retrieval_status"] == "success"`, extract  
     `launch_name = session.state["launch_info"][0]["name"]` (no modifications).  
     Set `q = launch_name`.  
     Otherwise, derive `q` from the recent user’s query by extracting relevant keywords or phrases, stripping out the word “news”
   - `searchIn`: is set by default to "title".
   - `sources`: if user named specific outlets.
   - `domains` / `exclude_domains`: if user restricted sites.
   - `from_date` / `to_date`:  
     • If user gave explicit dates or “since X,” convert to ISO.  
     • Else if `session.state["reference_date"]` exists, set a ±2-day window around it.  
   - `language`: 2-letter code (default `en` if query in English).  
   - `sort_by`:  
     • `"publishedAt"` for “latest”/“recent,”  
     • `"relevancy"` for “most relevant,”  
     • `"popularity"` for “popular” — default `"publishedAt"`.  
   - `page_size`: user-requested number or a default of `5`.

"""

try:
    news_agent = LlmAgent(
        # Using a potentially different/cheaper model for a simple task
        model = MODEL_GEMINI_2_0_FLASH,
        name="news_agent",
        instruction=NEWS_AGENT_INSTRUCTION,
        description="Fetches news articles from NewsAPI based on dynamic parameters derived from user query and context which calls 'fetch_news_articles' exactly once", # Crucial for delegation
        tools=[fetch_news_articles],  # Register the tool
    )
    print(f"✅ Agent '{news_agent.name}' created using model '{news_agent.model}'.")
except Exception as e:
    print(f"❌ Could not create News Info agent. Check API Key ({news_agent.model}). Error: {e}")

# %%
