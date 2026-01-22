"""
Web crawling module using Crawl4AI.
Handles deep crawling of event websites up to 2 levels.
"""
import logging
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

logger = logging.getLogger(__name__)


async def crawl_website(url: str) -> str:
	"""
	Crawl a website with 2-level deep crawling.

	Level 0: Main events page
	Level 1: Individual event detail pages
		url: Starting URL (events/calendar page)
		Combined text content from all pages
	"""
	try:
		logger.info(f"🕷️ Starting crawl: {url}")

		# Browser configuration
		browser_config = BrowserConfig(
			headless=True,  # Run browser invisibly
		)

		# Deep crawling strategy
		run_config = CrawlerRunConfig(
			deep_crawl_strategy=BFSDeepCrawlStrategy(
				max_depth=2,  # Main page + 1 level of links
				include_external=False,  # Stay on same domain
				max_pages=30  # Limit to 30 pages
			),
			word_count_threshold=50,  # Minimum words per page
			exclude_external_links=True,
			remove_overlay_elements=True,
			wait_for="css:.event-item, .veranstaltung, [data-event]",
			# Wait for event elements
			delay_before_return_html=5.0
			# IMPORTANT: Wait 5 seconds for JS to load
		)

		async with AsyncWebCrawler() as crawler:
			results = await crawler.arun(
				url=url,
				browser_config=browser_config,
				crawler_run_config=run_config
			)

			if not results:
				logger.warning(f"❌ No results from {url}")
				return ""

			# Process results (can be single or list)
			if isinstance(results, list):
				return process_multiple_results(results)
			elif hasattr(results, 'success') and results.success:
				return process_single_result(results)
			else:
				logger.warning(f"❌ Crawl failed for {url}")
				return ""

	except Exception as e:
		logger.error(f"❌ Crawl error for {url}: {e}", exc_info=True)
		return ""


def process_multiple_results(results: list) -> str:
	"""
	Process list of crawl results from multiple pages.
		results: List of crawl result objects
		Combined text content
	"""
	all_content = []

	for idx, result in enumerate(results):
		if not (result and hasattr(result,
								   'success') and result.success):
			continue

		# Use extracted_content instead of raw html (cleaner!)
		content = getattr(result, 'extracted_content', '') or getattr(
			result, 'markdown', '') or getattr(result, 'html', '')

		if not content:
			continue

		page_url = getattr(result, 'url', f"Page {idx}")

		# Filter out unwanted pages
		if not should_include_page(page_url):
			logger.info(f"⏭️ Skipped: {page_url}")
			continue

		all_content.append(
			f"=== PAGE {idx + 1}: {page_url} ===\n{content}")
		logger.info(
			f"✅ Included page {idx + 1}: {len(content)} chars")

	if all_content:
		combined = "\n\n<!-- NEXT PAGE -->\n\n".join(all_content)
		logger.info(
			f"✅ Combined {len(all_content)} pages → {len(combined)} total chars")
		return combined
	else:
		logger.warning("⚠️ No relevant content after filtering")
		return ""


def process_single_result(result) -> str:
	"""
	Process single crawl result.
		result: Single crawl result object
		Text content
	"""
	# Try to get extracted_content first (cleaner than raw HTML)
	content = getattr(result, 'extracted_content', '') or getattr(
		result, 'markdown', '') or getattr(result, 'html', '')

	if content:
		logger.info(f"✅ Single page: {len(content)} chars")
		return content
	else:
		logger.warning("⚠️ Empty content")
		return ""


def should_include_page(url: str) -> bool:
	"""
	Check if a URL should be included in results.
	Filters out admin, legal, and navigation pages.
		True if page should be included, False otherwise
	"""
	# Pages to exclude
	excluded_keywords = [
		"impressum", "kontakt", "datenschutz", "agb",
		"newsletter", "login", "suche", "search",
		"vermietung", "grundstueck", "ausschreibung",
		"verwaltung", "rathaus", "satzung", "formulare",
		"cookie", "nutzungsbedingungen"
	]

	url_lower = url.lower()

	# Check if any excluded keyword is in URL
	for keyword in excluded_keywords:
		if keyword in url_lower:
			return False

	return True