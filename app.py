import os
import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from crud import load_events, save_events
from crawl_webpage import crawl_site
from urls import START_URLS

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()
templates = Jinja2Templates(directory="templates")


class EventQuery(BaseModel):
    message: str


@app.on_event("startup")
async def startup_event():
    events = load_events()

    if events:
        logger.info(f"Database already contains {len(events)} events.")
        return

    logger.info("Database empty → automatic first crawl …")
    await crawl_and_save_events()


@app.get("/crawl")
async def crawl_all():
    return await crawl_and_save_events()


async def crawl_and_save_events():
    all_events = []
    errors = []

    for url in START_URLS:
        try:
            logger.info(f"Crawling {url} …")
            content = await crawl_site(url)

            if not content or len(content) < 50:
                errors.append(f"{url}: no content")
                continue

            events = parse_events(content, url)

            if not events:
                errors.append(f"{url}: no events extracted")
                continue

            all_events.extend(events)

        except Exception as e:
            logger.error(str(e), exc_info=True)
            errors.append(f"{url}: {e}")

    if all_events:
        save_events(all_events)
        logger.info(f"Saved {len(all_events)} events.")
    else:
        logger.warning("No events to save")

    return {
        "message": "Crawl finished",
        "events_found": len(all_events),
        "errors": errors or None
    }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api")
async def search_events(query: EventQuery):
    events = load_events()

    if not events:
        return {"reply": "No events found. Please run crawl first."}

    events_text = "\n".join([
        f"- {e.title} ({e.date if e.date else 'kein Datum'}) in {e.location} – {e.source_url}"
        for e in events
    ])

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an event assistant."},
            {"role": "user", "content": f"Query: {query.message}\n\nEvents:\n{events_text}"}
        ]
    )

    return {"reply": response.choices[0].message.content}


def parse_events(content: str, source_url: str):
    import re
    from datetime import datetime

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract events as a list using EXACTLY this format:\n"
                    "EVENT_START\n"
                    "TITEL: <title>\n"
                    "DATUM: <dd.mm.yyyy or empty>\n"
                    "ORT: <location>\n"
                    "EVENT_END\n\n"
                    "NO explanation, no extra text!"
                )
            },
            {"role": "user", "content": content}
        ]
    )

    text = response.choices[0].message.content
    events = []
    blocks = text.split("EVENT_START")

    for b in blocks:
        if "EVENT_END" not in b:
            continue

        b = b.split("EVENT_END")[0]

        title = re.search(r"TITEL:\s*(.*)", b)
        date = re.search(r"DATUM:\s*(.*)", b)
        loc = re.search(r"ORT:\s*(.*)", b)

        title = title.group(1).strip() if title else None
        loc = loc.group(1).strip() if loc else "unbekannt"
        ds = date.group(1).strip() if date else None

        date_obj = None
        if ds:
            try:
                date_obj = datetime.strptime(ds, "%d.%m.%Y")
            except:
                date_obj = None

        if title:
            events.append({
                "title": title,
                "location": loc,
                "date": date_obj,
                "source_url": source_url
            })

    return events