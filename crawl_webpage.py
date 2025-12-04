import asyncio
import logging
import re
from typing import List

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy

logger = logging.getLogger(__name__)


async def crawl_site(url: str) -> str:
    """
    Crawl a site 2 levels deep and return combined text content
    for pages that pass the URL filter.
    Returns empty string on failure or if nothing relevant found.
    """

    # Minimal, safe config - avoid unsupported args
    config = CrawlerRunConfig(
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=2,
            include_external=False,
        ),
        scraping_strategy=LXMLWebScrapingStrategy(),
        verbose=False,
    )

    try:
        logger.info(f"Starting deep crawling (2 levels): {url}")

        async with AsyncWebCrawler() as crawler:
            results = await crawler.arun(url, config=config)

        if not results:
            logger.warning(f"No results returned for {url}")
            return ""

        # results may be a list of page results
        pages_content: List[str] = []
        filtered_count = 0
        total_pages = len(results) if isinstance(results, list) else 1
        logger.info(f"Processing {total_pages} crawled pages...")

        # iterate results (robust for both dict-like and attr-like result objects)
        iterable = results if isinstance(results, list) else [results]

        for idx, result in enumerate(iterable):
            try:
                # Get URL from result (try attribute then dict keys)
                page_url = (
                    getattr(result, "url", None)
                    or result.get("url") if isinstance(result, dict) else None
                    or f"page_{idx}"
                )

                # Determine content: try common fields used by crawl4ai
                content = None
                if hasattr(result, "extracted_content"):
                    content = getattr(result, "extracted_content")
                elif hasattr(result, "content"):
                    content = getattr(result, "content")
                elif isinstance(result, dict):
                    # check common dict keys
                    for key in ("extracted_content", "content", "markdown", "text"):
                        if key in result and result[key]:
                            content = result[key]
                            break

                if not content:
                    logger.debug(f"No textual content for {page_url}, skipping")
                    filtered_count += 1
                    continue

                # Decide whether to include the page
                if not _should_include_page(page_url):
                    logger.debug(f"Filtered out non-event page: {page_url}")
                    filtered_count += 1
                    continue

                # Append a small page marker + content (trim very long pages)
                trimmed = content.strip()
                if len(trimmed) == 0:
                    filtered_count += 1
                    continue

                page_marker = "MAIN PAGE" if idx == 0 else f"SUBPAGE {idx}"
                pages_content.append(f"=== {page_marker}: {page_url} ===\n{trimmed}")

            except Exception as e:
                logger.warning(f"Skipping result #{idx} due to error: {e}")
                filtered_count += 1
                continue

        logger.info(f"Kept {len(pages_content)} pages, filtered out {filtered_count} pages")

        if pages_content:
            combined = "\n\n".join(pages_content)
            logger.info(f"Total combined content length: {len(combined)}")
            return combined

        logger.warning(f"No relevant event content found for {url}")
        return ""

    except Exception as e:
        logger.error(f"Error crawling {url}: {e}", exc_info=True)
        return ""


def _should_include_page(url: str) -> bool:
    """
    Return True if page URL looks like an event page, False if it should be excluded.
    This is a whitelist-ish approach: include pages that contain typical event path segments,
    but also explicitly exclude obvious admin/contact pages.
    """

    if not url:
        return False

    url = url.lower()

    # Explicit deny list (skip pages that are definitely not event related)
    denied_patterns = [
        r"/impressum", r"/kontakt", r"/datenschutz", r"/agb", r"/newsletter",
        r"/login", r"/suche", r"/search", r"/vermietung", r"/grundstueck",
        r"/ausschreibung", r"/verwaltung", r"/rathaus", r"/satzung", r"/formulare",
        r"/buergerservice", r"/kontaktformular", r"/kontakt-"
    ]

    for p in denied_patterns:
        if re.search(p, url):
            return False

    # Whitelist signals: URLs that likely contain event pages.
    # This is permissive
    allowed_signals = [
        r"/veranstalt",  # catches /veranstaltungen, /veranstaltung, etc.
        r"/event",       # english /event or /events
        r"/konzert", r"/markt", r"/messe", r"/theater", r"/festival"
    ]

    # If we detect an allowed signal, accept it.
    for s in allowed_signals:
        if re.search(s, url):
            return True

    # If no explicit allowed signal is present, reject (prevents crawling whole site)
    return False