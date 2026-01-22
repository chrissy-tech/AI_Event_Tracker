"""
Event Tracker FastAPI Application
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
from crud import save_events, load_events
from database import init_db
from crawl_webpage import crawl_website
from urls import START_URLS

# ==================== SETUP ====================
load_dotenv()
logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("app")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI(title="Event Tracker")
templates = Jinja2Templates(directory="templates")


# ==================== MODELS ====================
class EventQuery(BaseModel):
	"""User search query with optional filters."""
	message: str
	free_only: bool = False  # Filter for free events
	child_friendly: bool = False  # Filter for kids


# ==================== STARTUP ====================
@app.on_event("startup")
async def startup_event():
	"""Initialize database and load events on startup."""
	logger.info("🚀 Starting Event Tracker...")
	init_db()

	events = load_events()
	if events:
		logger.info(f"✓ Database has {len(events)} events")
	else:
		logger.info("Database empty - starting auto-crawl...")
		await crawl_all()


# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
	"""Show home page."""
	return templates.TemplateResponse("index.html",
									  {"request": request})


@app.get("/crawl")
async def crawl_all():
	"""
	Crawl websites and save events.
	3-step-process: Crawl → Extract → Save
	"""
	logger.info("📥 Starting crawl...")
	all_events = []
	errors = []

	# Step 1: Crawl each URL
	for url in START_URLS:
		try:
			logger.info(f"Crawling: {url}")
			html = await crawl_website(url)

			if not html or len(html) < 100:
				errors.append(f"{url}: No content")
				continue

			# Step 2: Extract events with AI
			events = extract_events(html, url)
			all_events.extend(events)
			logger.info(f"✓ Found {len(events)} events from {url}")

		except Exception as e:
			logger.error(f"❌ Error: {url} - {e}")
			errors.append(f"{url}: {str(e)}")

	# Step 3: Save to database
	if all_events:
		save_events(all_events)
		logger.info(f"✅ Saved {len(all_events)} total events")
	else:
		logger.warning("⚠️ No events found!")

	return {
		"message": "Crawling done",
		"events_found": len(all_events),
		"errors": errors if errors else None
	}


@app.post("/api")
async def search_events(query: EventQuery):
    """
    Search for events using a hybrid approach:
    Hard filters first, then AI-driven natural language processing.
    """
    # 1. Load all data from the database
    all_available_events = load_events()

    if not all_available_events:
        return {"reply": "No events found in the database."
						 " Please crawl some websites first!"}

    # 2. Apply Boolean Filters (Hard criteria from checkboxes)
    # start with all events and narrow them down
    matching_events = all_available_events

    if query.free_only:
        matching_events = [
            event for event in matching_events
            if getattr(event, 'is_free', False) is True
        ]
        logger.info(f"Filter applied: Free events only. Remaining:"
					f" {len(matching_events)}")

    if query.child_friendly:
        matching_events = [
            event for event in matching_events
            if "child" in event.title.lower() or "kind" in event.title.lower()
        ]

    # 3. Apply Text-Based Filters (Date and Location keywords)
    matching_events = filter_by_date(matching_events, query.message)
    matching_events = filter_by_location(matching_events, query.message)

    logger.info(f"Filtering complete: {len(all_available_events)}"
				f" total -> {len(matching_events)} matches")

    # 4. Limit the context size for the AI (Context Window Management)
    if len(matching_events) > 50:
        events_for_ai_context = matching_events[:50]
    else:
        events_for_ai_context = matching_events

    # 5. Handle empty results before calling the API to save costs
    if not events_for_ai_context:
        return {
            "reply": "I couldn't find any events matching your"
					 " specific criteria. Try a broader search!",
            "total_events": len(all_available_events),
            "filtered_to": 0
        }

    # 6. Generate AI Response
    formatted_events_text = format_events_for_ai(events_for_ai_context)

    ai_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional event assistant. "
                    "Use the provided event list to answer the user's question. "
                    "Include the title, date, and location for each event. "
                    "If an event is free, mention it clearly."
                )
            },
            {
                "role": "user",
                "content": f"User Question: {query.message}\n"
						   f"\nAvailable Events:\n{formatted_events_text}"
            }
        ],
        temperature=0.3
    )

    return {
        "reply": ai_response.choices[0].message.content,
        "total_events": len(all_available_events),
        "filtered_to": len(matching_events)
    }

# ==================== HELPER FUNCTIONS ====================

def extract_events(html_or_text: str, url: str) -> list:
	"""
	Extract events from HTML/text using OpenAI with better prompting.
		html_or_text: Raw HTML or extracted text
		url: Source URL
		List of event dictionaries
	"""
	try:
		# Limit content size (OpenAI token limit)
		max_chars = 25000  # Increased from 20k
		if len(html_or_text) > max_chars:
			html_or_text = html_or_text[:max_chars]
			logger.info(f"✂️ Truncated to {max_chars} chars")

		# Debug: Log preview of content
		logger.info(f"📄 Content preview:\n{html_or_text[:500]}\n...")

		# Call OpenAI
		response = client.chat.completions.create(
			model="gpt-4o-mini",
			messages=[
				{
					"role": "system",
					"content": """You are an expert event extractor. 
Extract ALL events from the provided text/HTML.

IMPORTANT: Look for:
- Event titles/names
- Dates (any format: DD.MM.YYYY, 24. Dezember, etc.)
- Locations/venues
- Price information (free, Eintritt frei, kostenlos = free)
- Keywords: outdoor, draußen, open air = outdoor

Format each event EXACTLY like this:

EVENT_START
TITEL: [Full event title]
DATUM: [DD.MM.YYYY or "unbekannt"]
ORT: [Location or "unbekannt"]
KOSTENLOS: [Ja/Nein]
DRAUSSEN: [Ja/Nein]
EVENT_END

Extract EVERY event you can find, even if some information is missing."""
				},
				{
					"role": "user",
					"content": f"Extract all events from this content:\n\n{html_or_text}"
				}
			],
			temperature=0.2  # Lower = more consistent
		)

		ai_text = response.choices[0].message.content

		# Debug: Log AI response
		logger.info(f"🤖 AI response preview:\n{ai_text[:300]}\n...")

		events = parse_ai_response(ai_text, url)

		if not events:
			logger.warning(f"⚠️ No events extracted from {url}")
			logger.warning(f"AI said: {ai_text[:200]}...")

		return events

	except Exception as e:
		logger.error(f"❌ AI extraction failed: {e}", exc_info=True)
		return []

def parse_ai_response(response_text: str, source_url: str) -> list:
	"""
	Parses the raw text from the AI into a structured
	list of event dictionaries.
	"""
	extracted_events_list = []
	event_blocks = response_text.split("EVENT_START")

	for block in event_blocks:
		if "EVENT_END" not in block:
			continue

		# Initialize event dictionary with default values
		current_event = {
			"url": source_url,
			"location": "unknown",
			"date": None,
			"is_free": False,
			"is_outdoor": False
		}

		# Process each line within the block
		lines = block.split("EVENT_END")[0].split("\n")
		for line in lines:
			clean_line = line.strip()

			if clean_line.startswith("TITEL:"):
				current_event["title"] = clean_line.replace("TITEL:",
															"").strip()

			elif clean_line.startswith("DATUM:"):
				date_string = clean_line.replace("DATUM:", "").strip()
				current_event["date"] = parse_date(date_string)

			elif clean_line.startswith("ORT:"):
				current_event["location"] = clean_line.replace("ORT:",
															   "").strip()

			elif clean_line.startswith("KOSTENLOS:"):
				status_text = clean_line.replace("KOSTENLOS:",
												 "").strip().lower()
				current_event["is_free"] = (status_text == "ja")

			elif clean_line.startswith("DRAUSSEN:"):
				status_text = clean_line.replace("DRAUSSEN:",
												 "").strip().lower()
				current_event["is_outdoor"] = (status_text == "ja")

		# After collecting all lines, finalize the event
		if "title" in current_event and current_event["title"]:
			current_event["category"] = detect_category(
				current_event["title"],
				current_event.get("location", "")
			)
			extracted_events_list.append(current_event)

	return extracted_events_list

def parse_date(date_str: str):
	"""Parse date string to datetime."""
	if not date_str or date_str.lower() == "unbekannt":
		return None

	# Handle ranges (take first date)
	if "-" in date_str and "." in date_str:
		date_str = date_str.split("-")[0].strip()

	for fmt in ["%d.%m.%Y", "%d.%m.%y"]:
		try:
			return datetime.strptime(date_str, fmt)
		except:
			continue

	logger.warning(f"Could not parse date: {date_str}")
	return None


def filter_by_date(event_list: list,
				   user_search_query: str) -> list:
	"""
	Filters the list of events based on date-related
	keywords in the user's message.
	"""
	search_text_lower = user_search_query.lower()
	current_date = datetime.now().date()

	# 1. Check for "today"
	if any(keyword in search_text_lower for keyword in
		   ["today", "heute"]):
		return [
			event for event in event_list
			if event.date and event.date.date() == current_date
		]

	# 2. Check for "tomorrow"
	if any(keyword in search_text_lower for keyword in
		   ["tomorrow", "morgen"]):
		tomorrow_date = current_date + timedelta(days=1)
		return [
			event for event in event_list
			if event.date and event.date.date() == tomorrow_date
		]

	# 3. Check for "weekend" (Saturday and Sunday)
	if any(keyword in search_text_lower for keyword in
		   ["weekend", "wochenende", "samstag", "sonntag"]):
		# weekday() returns 5 for Saturday and 6 for Sunday
		return [
			event for event in event_list
			if event.date and event.date.weekday() in [5, 6]
		]

	# 4. Check for a specific date pattern like "24.12."
	# This regex looks for 1 or 2 digits, a dot, and another 1 or 2 digits
	date_pattern = r'\d{1,2}\.\d{1,2}'
	regex_match = re.search(date_pattern, search_text_lower)

	if regex_match:
		day_and_month_string = regex_match.group()
		return [
			event for event in event_list
			if event.date and event.date.strftime(
				"%d.%m") == day_and_month_string
		]

	# 5. If no date keywords are found, return the full list (no filtering)
	return event_list


def filter_by_location(event_list: list,
					   user_search_query: str) -> list:
	"""
	Filters events if a specific city name is mentioned in the search query.
	"""
	search_text_lower = user_search_query.lower()

	# List of cities the tracker currently supports
	target_cities = [
		"bitterfeld", "wolfen", "leipzig", "halle",
		"dessau", "muldestausee", "pouch"
	]

	for city_name in target_cities:
		# If the user mentioned one of our target cities
		if city_name in search_text_lower:
			logger.info(
				f"Filtering results for city: {city_name.capitalize()}")
			return [
				event for event in event_list
				if city_name in (event.location or "").lower()
			]

	# If no city was mentioned, we don't filter anything
	return event_list


def format_events_for_ai(events: list) -> str:
	"""Format events nicely for AI."""
	return "\n".join([
		f"- {e.title} | {e.date.strftime('%d.%m.%Y') if e.date else 'No date'} | {e.location}"
		for e in events
	])

def detect_category(title: str, location: str) -> str:
	"""Recognizes the category based on keywords."""
	text = f"{title} {location}".lower()
	if any(word in text for word in ["konzert", "musik", "band", "live"]):
		return "Musik"
	elif any(word in text for word in ["markt", "weihnachtsmarkt", "flohmarkt"]):
		return "Markt"
	elif any(word in text for word in ["theater", "oper", "aufführung"]):
		return "Theater"
	elif any(word in text for word in ["sport", "fußball", "lauf", "yoga"]):
		return "Sport"
	return "Sonstiges"

app.get("/debug-crawl")
async def debug_crawl():
    """
    DEBUG ENDPOINT: Shows what content is being crawled.
    Use this to see if events are in the HTML!
    """
    url = START_URLS[0]  # Test first URL

    logger.info(f"🔍 DEBUG: Crawling {url}")
    html = await crawl_website(url)

    return {
        "url": url,
        "content_length": len(html),
        "content_preview": html[:2000],  # First 2000 chars
        "has_event_keywords": any(word in html.lower() for word in [
            "veranstaltung", "event", "konzert", "festival", "markt"
        ])
    }