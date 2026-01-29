"""
Event Tracker FastAPI Application - Live Search Edition
"""
import logging
import os
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from database import init_db
from crawl_webpage import crawl_website
from urls import START_URLS
from fastapi.staticfiles import StaticFiles

# ==================== SETUP ====================
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("app")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI(title="Live Event Tracker")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ==================== MODELS ====================
class EventQuery(BaseModel):
    """User search query with optional filters."""
    message: str


# ==================== STARTUP ====================
@app.on_event("startup")
async def startup_event():
    """Initialize system on startup."""
    logger.info("🚀 Starting Live Event Tracker...")
    init_db()  # Initialize database for persistence if needed


# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Show the search interface."""
    return templates.TemplateResponse("index.html",
                                      {"request": request})


@app.post("/api")
async def search_events(query: EventQuery):
    """
    Perform a live crawl and AI extraction based on the user's message.
    """
    all_found_events = []

    # 1. Loop through all URLs to find events
    for current_url in START_URLS:
        try:
            logger.info(f"Searching on: {current_url}")
            # The crawler returns a list of dictionaries via LLM extraction
            crawl_results = await crawl_website(current_url,
                                                query.message)

            if crawl_results:
                all_found_events.extend(crawl_results)
        except Exception as error:
            logger.error(
                f"Error during crawl of {current_url}: {error}")

    logger.info(
        f"Crawl finished. Found {len(all_found_events)} potential events.")

    # 2. Filter logic
    matching_events = all_found_events

    # 3. Apply date and location filters
    matching_events = filter_by_date(matching_events, query.message)
    matching_events = filter_by_location(matching_events,
                                         query.message)

    # 4. Handle empty results
    if not matching_events:
        return {
            "reply": "I'm sorry, I couldn't find any events matching your request.",
            "total_events": 0
        }

    # 5. Build AI summary
    # We only send the top 15 events to the AI to stay within token limits
    context_events = matching_events[:15]
    formatted_text = format_events_for_ai(context_events)

    ai_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                            "You are a professional helpful event assistant. "
                            "Use the following format for each event:\n"
                			"Titel: [Name]\n"
                			"Datum: [Date]\n"
                			"Location: [Location]\n\n"
                			"Only mention 'Free' or 'Kids' if specifically asked, "
                			"or if it is a key highlight. Otherwise, stay neutral. "
                            "Summarize the events found in a friendly way. "
                            "STRICTLY answer in the same language as the user's last question. "
                            "If the user asks in English, your entire summary must be in English, "
                            "even if the source data is in German. "
                            "If the user asks in German, answer in German."
                )
            },
            {
                "role": "user",
                "content": f"Query: {query.message}\n\nEvents:\n{formatted_text}"
            }
        ]
    )

    return {
        "reply": ai_response.choices[0].message.content,
        "total_events": len(all_found_events),
        "filtered_to": len(matching_events)
    }


# ==================== HELPER FUNCTIONS ====================

def filter_by_date(event_list: list, user_search_query: str) -> list:
    query = user_search_query.lower()
    today = datetime.now().date()

    def to_date(date_string):
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_string, fmt).date()
            except:
                continue
        return None

    mon_next = (today.replace(day=28) + timedelta(4)).replace(day=1)
    mon_after = (mon_next + timedelta(32)).replace(day=1)

    ranges = {
        ("heute", "today"): (today, today),
        ("morgen", "tomorrow"):
            (today + timedelta(1), today + timedelta(1)),
        ("übermorgen", "after tomorrow"):
            (today + timedelta(2), today + timedelta(2)),
        ("diese woche", "this week"):
            (today, today + timedelta(6 - today.weekday())),
        ("nächste woche", "next week"):
            (today + timedelta(7 - today.weekday()),
             today + timedelta(13 - today.weekday())),
        ("wochenende", "weekend"):
            (today + timedelta(5 - today.weekday()),
             today + timedelta(6 - today.weekday())),
        ("nächstes wochenende", "next weekend"):
            (today + timedelta(12 - today.weekday()),
             today + timedelta(13 - today.weekday())),
        ("diesen monat", "this month"):
            (today, mon_next - timedelta(1)),
        ("nächsten monat", "next month"):
            (mon_next, mon_after - timedelta(1))
    }

    for words, (start, end) in ranges.items():
        if any(word in query for word in words):
            return [item for item in event_list if start <=
                    (to_date(item.get("date", "")) or today) <= end]

    return event_list


def filter_by_location(event_list: list, query: str) -> list:
    """Filters events by mentioned cities in the query."""
    query = query.lower()
    cities = ["bitterfeld", "wolfen", "leipzig", "halle",
              "dessau", "pouch"]

    found_cities = [city_name for city_name in cities if city_name in query]

    if not found_cities:
        return event_list

    return [item for item in event_list if any(city_name in
            item.get("location", "").lower() for city_name in found_cities)]


def format_events_for_ai(events: list) -> str:
    """Converts event list into a readable string for AI context."""
    lines = [] #empty list to store formatted event strings
	# Keywords used to detect child-friendly events in the title
    child_keywords = ["kind", "familie", "child", "baby", "jugend"]
    for item in events:
        title = item.get("title", "No Title")
        date = item.get("date", "Unknown Date")
        loc = item.get("location", "Unknown Location")

		# Extract description or use fallback if missing
        desc = item.get("description", "No description available")

		# Truncate description to 150 chars to save AI tokens
        short_desc = (desc[:150] + '...') if len(desc) > 150 else desc

		# Convert 'is_free' boolean into a readable 'Yes' or 'No'
        is_free = "Yes" if item.get("is_free") else "No"

		# Check if any keyword exists in title for child-friendliness
        is_child = "Yes" if any(word in title.lower()
                                for word in child_keywords) else "No"

		# Build formatted string and append to the list
        lines.append(
            f"- {title} | Date: {date} | Location: {loc} | "
            f"Free: {is_free} | Kids: {is_child} | Info: {short_desc}"
        )
	# Combine all lines into a single string separated by newlines
    return "\n".join(lines)