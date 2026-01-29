"""
Web crawling module using Crawl4AI.
Handles deep crawling of event websites with AI extraction.
"""
import logging
import os
import json
from typing import List
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, LLMExtractionStrategy, LLMConfig
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class EventData(BaseModel):
    title: str = Field(..., description="Der Name der Veranstaltung")
    date: str = Field(..., description="Datum im Format DD.MM.YYYY")
    location: str = Field(..., description="Wo es stattfindet")
    is_free: bool = Field(..., description="Ist es kostenlos?")

async def crawl_website(url: str, user_query: str) -> List[dict]:
    """
    Crawl a website and use AI to extract events matching the user query.
    """
    # 1. AI Strategy Setup
    extraction_instruction = (
        "Extract ALL events found on this page. "
        "For each event, provide the title, date, location, and whether it is free. "
        "Use the schema provided. If information is missing, use 'Unknown'."
    )

    strategy = LLMExtractionStrategy(
        llm_config=LLMConfig(
            provider="openai/gpt-4o-mini",
            api_token=os.getenv("OPENAI_API_KEY")
        ),
        schema=EventData.model_json_schema(),
        instruction=extraction_instruction,
        extraction_type="schema"
    )
    # 2. JavaScript to click Cookie Banners
    js_click_cookies = """
    (async () => {
        const terms = ['alle akzeptieren', 'akzeptieren', 'verstanden', 'zustimmen', 'ok'];
        const elements = document.querySelectorAll('button, a, div[role="button"]');
        
        for (const el of elements) {
            const text = el.innerText.toLowerCase();
            if (terms.some(term => text.includes(term))) {
                el.click();
                console.log('Clicked:', text);
            }
        }
        // Warte kurz, falls der Banner weg-animiert wird
        await new Promise(r => setTimeout(r, 2000));
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
            js_code=["window.scrollTo(0, document.body.scrollHeight);"],
            delay_before_return_html=10.0,
			stream=False,
			wait_until="domcontentloaded"
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