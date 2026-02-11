"""
Web crawling module using Crawl4AI.
Handles deep crawling of event websites with AI extraction.
"""
import logging
import os
import json
from typing import List
from datetime import datetime
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, LLMExtractionStrategy, LLMConfig
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class EventData(BaseModel):
    title: str = Field(..., description="Der Name der Veranstaltung")
    date: str = Field(..., description="Datum im Format DD.MM.YYYY")
    location: str = Field(..., description="Wo es stattfindet")
    is_free: bool = Field(..., description="Ist es kostenlos?")
    description: str = Field(...,
                             description="Kurze Zusammenfassung des Inhalts")

async def crawl_website(url: str, user_query: str) -> List[dict]:
    """
    Crawl a website and use AI to extract events matching the user query.
    """

    today_str = datetime.now().strftime("%d.%m.%Y")
    # 1. AI Strategy Setup
    extraction_instruction = (
        f"CRITICAL TASK: Extract ONLY events matching: '{user_query}'."
    	f"Today is {datetime.now().strftime('%d.%m.%Y')}."
    	"Follow these date definitions strictly:\n"
    	"- 'today': only events on this exact date.\n"
    	"- 'this weekend': only events on the upcoming Saturday and Sunday.\n"
    	"- 'next weekend': only events on the Saturday/Sunday of the following week.\n"
    	"If an event date is outside the requested range, DISCARD IT."
		"Only extract events where a specific date is clearly visible."
		"DO NOT change the date to match the user's search query."
		"If an event is on the 19.02., the date field MUST be '19.02.2026'."
		"If you are unsure about the date, skip the event."
		"Format the date strictly as DD.MM.YYYY. "
    	"Provide title, date (DD.MM.YYYY), location, is_free, and a short description."
    )
    strategy = LLMExtractionStrategy(
        llm_config=LLMConfig(
            provider="openai/gpt-4o-mini",
            api_token=os.getenv("OPENAI_API_KEY")
        ),
        schema=EventData.model_json_schema(),
        instruction=extraction_instruction, #This is where the dynamic information comes into play
        extraction_type="schema"
    )

    # 2. JavaScript to click Cookie Banners
    js_click_cookies = """
        (async () => {
        const terms = ['alle akzeptieren', 'akzeptieren', 'verstanden', 'zustimmen', 'ok',
        'einverstanden', 'weiter', 'weitermachen','alle annehmen'];
        const elements = document.querySelectorAll('button, a, div[role="button"]');
        
        for (const btn of buttons) {
            const text = bt.innerText.toLowerCase().trim();
            if (terms.some(term => text.includes(term))) {
                el.click();
                console.log('Cookie Banner geklickt:', text);
                await new Promise(r => setTimeout(r, 2000)); // Kurze Pause nach Klick
                break;
            }
        }
    })();
    """

    # 3. Start Crawling Process
    try:
        logger.info(f"🕷️ Starting live-crawl: {url}")

        browser_config = BrowserConfig(
            headless=True, #app is working in background
            viewport_width=1280,
            viewport_height=800,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            extra_args=["--disable-gpu", "--disable-dev-shm-usage"]
        )

        run_config = CrawlerRunConfig(
            extraction_strategy=strategy,
			# 1. Präzision: Nur in diesen Bereichen nach Events suchen (ignoriert Banner/Menüs)
			#css_selector="#content, .veranstaltungskalender, .veranstaltungen_liste, main",
			# 2. Aktion: Erst Scrollen, dann Banner wegklicken
			js_code=[
				"window.scrollTo(0, document.body.scrollHeight);",
				"await new Promise(r => setTimeout(r, 3000));",
				# Warte 3 Sek nach Scrollen
				js_click_cookies,
				"window.scrollTo(0, document.body.scrollHeight);"
				# Nochmal scrollen nach Klick
			],
			# 3. Geduld: Dem Browser Zeit geben, das JS auszuführen und Inhalte zu laden
            delay_before_return_html=15.0,
            stream=False,
            wait_until="networkidle" # Warte, bis keine Daten mehr geladen werden
        )

        async with AsyncWebCrawler(
                config=browser_config) as crawler:  # Config hier übergeben!
            results = await crawler.arun(
                url=url,
                config=run_config,  # Und hier die Run-Config!
                session_id="event_session"
            )

            # --- DEBUG PRINT ---
            content_preview = results.markdown[:500] if results.success else "Crawl fehlgeschlagen"
            print(f"\n--- DEBUG VORSCHAU ({url}) ---")
            print(content_preview)
            print("--- DEBUG ENDE ---\n")

            all_found_events = []
            if results.success and results.extracted_content:
                all_found_events = json.loads(results.extracted_content)

            return all_found_events

    except Exception as e:
        logger.error(f"❌ Crawl error for {url}: {e}", exc_info=True)
        return []