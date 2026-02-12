"""
Event Tracker FastAPI Application - Live Search Edition
"""
import logging
import os
import json
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from fastapi.staticfiles import StaticFiles

# Eigene Module
from database import init_db, get_smart_cache, update_url_cache
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
	init_db()


# ==================== SMART LOGIC ====================
async def get_events_logic(url: str, user_query: str):
	"""
	Smart Trigger: Prüft erst die Datenbank, ob die URL kürzlich gecrawlt wurde.
	Falls nicht, wird ein Live-Crawl gestartet.
	"""
	# 1. Prüfe DB (Cache für 1 Stunde gültig)
	cached_data = get_smart_cache(url, max_age_hours=1)

	if cached_data:
		logger.info(f"✅ DB HIT: Daten für {url} aus Cache geladen.")
		return cached_data

	# 2. FALLBACK: Live Crawl
	logger.info(f"🌐 LIVE CRAWL: Starte frische Extraktion für {url}")
	live_results = await crawl_website(url, user_query)

	# 3. UPDATE: In Datenbank speichern für nächste Anfrage
	if live_results:
		update_url_cache(url, live_results)

	return live_results


# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
	"""Show the search interface."""
	return templates.TemplateResponse("index.html",
									  {"request": request})


@app.post("/api")
async def search_events(query: EventQuery):
	"""
	Perform a search using Smart Trigger (DB or Crawl).
	"""
	all_found_events = []

	# 1. Daten beschaffen (DB oder Live)
	for current_url in START_URLS:
		try:
			crawl_results = await get_events_logic(current_url,
												   query.message)
			if crawl_results:
				all_found_events.extend(crawl_results)
		except Exception as error:
			logger.error(f"Error processing {current_url}: {error}")

	logger.info(
		f"Data retrieval finished. Total events to filter: {len(all_found_events)}")

	# Debug-Speicherung
	with open("debug_raw_events.json", "w", encoding="utf-8") as f:
		json.dump(all_found_events, f, ensure_ascii=False, indent=4)

	# 2. Python Filtering (Date & Location)
	matching_events = filter_by_date(all_found_events, query.message)
	matching_events = filter_by_location(matching_events,
										 query.message)

	logger.info(
		f"After filtering: {len(matching_events)} events remaining.")

	# 3. Handle empty results
	if not matching_events:
		return {
			"reply": "I'm sorry, I couldn't find any events matching your request in the specified timeframe or location.",
			"total_events": len(all_found_events),
			"filtered_to": 0
		}

	# 4. Build AI summary
	context_events = matching_events[:15]
	formatted_text = format_events_for_ai(context_events)

	ai_response = client.chat.completions.create(
		model="gpt-4o-mini",
		messages=[
			{
				"role": "system",
				"content": (
					f"Today is {datetime.now().strftime('%d.%m.%Y')}. "
                	"You are an event assistant. The Python filter has already selected the "
                	"appropriate events for the user's request. Accept the provided events "
                	"as correct for the requested timeframe.\n\n"
                	"Present the events in this format:\n"
                	"**Title**: [Name]\n"
                	"**Date**: [Date]\n"
                	"**Location**: [Location]\n"
               	 	"**Info**: [Summary]\n\n"
               	 	"Always respond in the same language the user used."
             )
			},
			{
				"role": "user",
				"content": f"User Request: {query.message}\n\nEvents:\n{formatted_text}"
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
		if not date_string: return None
		for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
			try:
				return datetime.strptime(date_string, fmt).date()
			except:
				continue
		return None

	# ---PRÜFUNG AUF KONKRETES DATUM (z.B. 14.02.2026) ---
	# Dieser Block fängt exakte Daten ab, bevor die Keywords gescannt werden
	date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})',
						   user_search_query)
	if date_match:
		try:
			target_date = datetime.strptime(date_match.group(1),
											"%d.%m.%Y").date()
			# Filtert alles raus, was nicht exakt an diesem Tag ist
			return [e for e in event_list if
					to_date(e.get("date")) == target_date]
		except:
			pass  # Fall

	# --- KEYWORD LOGIC ---
	# Dynamische Zeiträume berechnen
	mon_next = (today.replace(day=28) + timedelta(4)).replace(day=1)

	# Weekend Logic
	days_to_sat = (5 - today.weekday())
	this_sat = today + timedelta(days=days_to_sat)
	this_sun = this_sat + timedelta(days=1)

	next_sat = this_sat + timedelta(days=7)
	next_sun = next_sat + timedelta(days=1)

	ranges = {
		# 1. Spezifische Zeiträume zuerst (Wichtig für die Erkennung!)
		("nächstes wochenende", "next weekend"): (next_sat, next_sun),
		("nächste woche", "next week"): (
			today + timedelta(days=(7 - today.weekday())),
			today + timedelta(days=(13 - today.weekday()))
		),

		# 2. Aktuelle/Allgemeine Zeiträume
		("dieses wochenende", "wochenende", "weekend"): (this_sat,
														 this_sun),
		("diese woche", "this week"): (today, today + timedelta(
			days=(6 - today.weekday()))),
		("heute", "today"): (today, today),
		("morgen", "tomorrow"): (today + timedelta(1),
								 today + timedelta(1)),
		("dieses monat", "dieser monat", "this month"): (
			today.replace(day=1), mon_next),

	# --- Monate (Beispielhaft für das Frühjahr 2026) ---
		("februar", "february"): (datetime(2026, 2, 1).date(),
								  datetime(2026, 2, 28).date()),
		("märz", "march"): (datetime(2026, 3, 1).date(),
							datetime(2026, 3, 31).date()),
		("april", "april"): (datetime(2026, 4, 1).date(),
							 datetime(2026, 4, 30).date()),
		("mai", "may"): (datetime(2026, 5, 1).date(),
						 datetime(2026, 5, 31).date())
	}


	# Prüfen, ob ein Zeitraum-Keyword in der Query vorkommt
	for words, (start, end) in ranges.items():
		if any(word in query for word in words):
			filtered = []
			for item in event_list:
				ev_date = to_date(item.get("date", ""))
				if ev_date and start <= ev_date <= end:
					filtered.append(item)
			return filtered

	return event_list


def filter_by_location(event_list: list, query: str) -> list:
	if not event_list: return []
	query = query.lower()
	cities = ["bitterfeld", "wolfen", "leipzig", "halle", "dessau",
			  "pouch"]
	found_cities = [c for c in cities if c in query]

	if not found_cities:
		return event_list

	return [item for item in event_list if any(
		c in item.get("location", "").lower() for c in found_cities)]


def format_events_for_ai(events: list) -> str:
	lines = []
	child_keywords = ["kind", "familie", "child", "baby", "jugend"]
	for item in events:
		title = item.get("title", "No Title")
		date = item.get("date", "Unknown Date")
		loc = item.get("location", "Unknown Location")
		desc = item.get("description", "No description available")
		short_desc = (desc[:150] + '...') if len(desc) > 150 else desc
		is_free = "Yes" if item.get("is_free") else "No"
		is_child = "Yes" if any(word in title.lower() for word in
								child_keywords) else "No"

		lines.append(
			f"- {title} | Date: {date} | Location: {loc} | Free: {is_free} | Kids: {is_child} | Info: {short_desc}")
	return "\n".join(lines)