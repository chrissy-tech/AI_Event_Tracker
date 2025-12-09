import logging
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

logger = logging.getLogger(__name__)


async def crawl_website(url: str) -> str:
	"""
	Crawl a website with deep crawling (2 levels).

	Crawls the main event page and linked event detail pages.

	Args:
		url: Starting URL (should be an events/calendar page)

	Returns:
		Combined HTML content from all crawled pages
	"""
	try:
		logger.info(f"Crawling {url} with deep strategy...")

		# Configure browser
		browser_config = BrowserConfig(
			headless=True,
			java_script_enabled=True
		)

		# Configure deep crawling
		run_config = CrawlerRunConfig(
			deep_crawl_strategy=BFSDeepCrawlStrategy(
				max_depth=2,  # Main page + linked pages
				include_external=False,  # Stay on same domain
				max_pages=30  # Limit to prevent crawling entire site
			),
			word_count_threshold=10,
			exclude_external_links=True,
			remove_overlay_elements=True
		)

		async with AsyncWebCrawler() as crawler:
			results = await crawler.arun(
				url=url,
				browser_config=browser_config,
				crawler_run_config=run_config
			)

			# Handle both single result and list of results
			if not results:
				logger.warning(f"No results from {url}")
				return ""

			# If results is a list (multiple pages crawled)
			if isinstance(results, list):
				all_content = []

				for idx, result in enumerate(results):
					if result and hasattr(result,
										  'success') and result.success:
						if result.html:
							# Filter out non-event pages
							page_url = result.url if hasattr(result,
															 'url') else url

							if should_include_page(page_url):
								all_content.append(result.html)
								logger.info(
									f"✓ Included page {idx + 1}: {len(result.html)} chars")
							else:
								logger.info(
									f"✗ Filtered page: {page_url}")

				if all_content:
					combined = "\n\n<!-- PAGE SEPARATOR -->\n\n".join(
						all_content)
					logger.info(
						f"✓ Combined {len(all_content)} pages → {len(combined)} total chars")
					return combined
				else:
					logger.warning(
						"No relevant pages found after filtering")
					return ""

			# Single result (fallback)
			elif hasattr(results, 'success') and results.success:
				if results.html:
					logger.info(
						f"✓ Single page: {len(results.html)} chars")
					return results.html

			logger.warning(f"Crawl failed for {url}")
			return ""

	except Exception as e:
		logger.error(f"Crawl error for {url}: {e}", exc_info=True)
		return ""


def should_include_page(url: str) -> bool:
	"""
	Filter to include only event-related pages.

	Excludes admin, contact, privacy pages etc.

	Args:
		url: URL to check

	Returns:
		True if page should be included
	"""
	# Exclude these patterns
	excluded = [
		"impressum", "kontakt", "datenschutz", "agb",
		"newsletter", "login", "suche", "search",
		"vermietung", "grundstueck", "ausschreibung",
		"verwaltung", "rathaus", "satzung", "formulare"
	]

	url_lower = url.lower()

	for pattern in excluded:
		if pattern in url_lower:
			return False

	return True