import logging
import os
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

# Setup
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()
templates = Jinja2Templates(directory="templates")


# Models
class EventQuery(BaseModel):
	"""User search query model."""
	message: str


# Startup
@app.on_event("startup")
async def startup_event():
	"""Initialize database and auto-crawl if empty."""
	init_db()

	events = load_events()
	if events:
		logger.info(f"✓ Database contains {len(events)} events")
	else:
		logger.info("Database empty → starting auto-crawl...")
		await crawl_all()


# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
	"""Render home page."""
	return templates.TemplateResponse("index.html",
									  {"request": request})


@app.get("/crawl")
async def crawl_all():
	"""
	Crawl all URLs, extract events with OpenAI, save to database.

	Returns:
		JSON with crawl summary
	"""
	all_events = []
	errors = []

	for url in START_URLS:
		try:
			logger.info(f"Starting crawl: {url}")

			# Step 1: Crawl website and get HTML content
			html_content = await crawl_website(url)

			if not html_content or len(html_content) < 100:
				error_msg = f"{url}: Insufficient content"
				logger.warning(error_msg)
				errors.append(error_msg)
				continue

			logger.info(
				f"✓ Crawled {len(html_content)} characters from {url}")

			# Step 2: Extract events using OpenAI
			events = extract_events_with_openai(html_content, url)

			if events:
				logger.info(
					f"✓ Extracted {len(events)} events from {url}")
				all_events.extend(events)
			else:
				logger.warning(f"No events found in {url}")

		except Exception as e:
			error_msg = f"{url}: {str(e)}"
			logger.error(error_msg, exc_info=True)
			errors.append(error_msg)

	# Step 3: Save to database
	if all_events:
		save_events(all_events)
		logger.info(f"✓ Saved {len(all_events)} events to database")
	else:
		logger.warning("✗ No events found to save")

	return {
		"message": "Crawling completed",
		"events_found": len(all_events),
		"urls_crawled": len(START_URLS),
		"errors": errors if errors else None
	}


@app.post("/api")
async def search_events(query: EventQuery):
	"""
	Search events using OpenAI based on user query.

	Args:
		query: User search query

	Returns:
		JSON with AI-generated response
	"""
	events = load_events()

	if not events:
		return {
			"reply": "No events in database. Please click 'Refresh Events' to crawl first."
		}

	# Format events for OpenAI
	events_text = "\n".join([
		f"- {e.title} on {e.date.strftime('%d.%m.%Y') if e.date else 'Date unknown'} "
		f"in {e.location} (Link: {e.source_url})"
		for e in events
	])

	# Call OpenAI for intelligent search
	response = client.chat.completions.create(
		model="gpt-4o-mini",
		messages=[
			{
				"role": "system",
				"content": "You are an event assistant for Bitterfeld-Wolfen and surrounding areas. "
						   "Answer questions about events. Be friendly and precise. "
						   "Always include title, date, location, and link."
			},
			{
				"role": "user",
				"content": f"Question: {query.message}\n\nEvents:\n{events_text}"
			}
		]
	)

	return {"reply": response.choices[0].message.content}


# Helper Functions
def extract_events_with_openai(html_content: str,
							   source_url: str) -> list:
	"""
	Extract events from HTML using OpenAI.

	Args:
		html_content: Raw HTML text
		source_url: Source URL for reference

	Returns:
		List of event dictionaries
	"""
	try:
		# Truncate if too long (OpenAI token limit)
		max_chars = 20000
		if len(html_content) > max_chars:
			html_content = html_content[:max_chars]
			logger.info(
				f"Truncated content to {max_chars} characters")

		# Call OpenAI to extract events
		response = client.chat.completions.create(
			model="gpt-4o-mini",
			messages=[
				{
					"role": "system",
					"content": """You are an event extractor. Extract ALL events from HTML content.

Respond ONLY in this format (no explanations):

EVENT_START
TITEL: [Event title]
DATUM: [DD.MM.YYYY or DD.MM.YYYY-DD.MM.YYYY for ranges]
ORT: [Location or "unbekannt"]
EVENT_END

Important:
- Extract ALL events
- For date ranges use start date
- Pay attention to Christmas markets, festivals, concerts"""
				},
				{
					"role": "user",
					"content": f"Extract all events from this HTML:\n\n{html_content}"
				}
			],
			temperature=0.3
		)

		ai_response = response.choices[0].message.content
		events = parse_openai_response(ai_response, source_url)

		return events

	except Exception as e:
		logger.error(f"OpenAI extraction error: {e}", exc_info=True)
		return []


def parse_openai_response(text: str, source_url: str) -> list:
	"""
	Parse OpenAI response into event dictionaries.

	Args:
		text: OpenAI response text
		source_url: Source URL

	Returns:
		List of event dictionaries
	"""
	from datetime import datetime

	events = []
	blocks = text.split("EVENT_START")

	for block in blocks:
		if "EVENT_END" not in block:
			continue

		# Extract content between START and END
		block = block.split("EVENT_END")[0].strip()
		lines = block.strip().split("\n")

		event = {
			"url": source_url,
			"location": "unbekannt",
			"date": None
		}

		# Parse each line
		for line in lines:
			line = line.strip()

			if line.startswith("TITEL:"):
				event["title"] = line.replace("TITEL:", "").strip()

			elif line.startswith("DATUM:"):
				date_str = line.replace("DATUM:", "").strip()
				if date_str.lower() != "unbekannt":
					# Handle date ranges (take start date)
					if "-" in date_str and "." in date_str:
						date_str = date_str.split("-")[0].strip()

					# Try parsing date
					try:
						event["date"] = datetime.strptime(date_str,
														  "%d.%m.%Y")
					except:
						try:
							event["date"] = datetime.strptime(
								date_str, "%d.%m.%y")
						except:
							logger.warning(
								f"Could not parse date: {date_str}")

			elif line.startswith("ORT:"):
				location = line.replace("ORT:", "").strip()
				if location.lower() != "unbekannt":
					event["location"] = location

		# Only add if has title
		if "title" in event and event["title"]:
			events.append(event)

	return events