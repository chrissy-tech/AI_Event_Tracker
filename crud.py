"""
Database CRUD operations for events.
Handles saving, loading, and deleting events.
"""
import logging
from database import SessionLocal, EventDB

logger = logging.getLogger(__name__)


def save_events(events: list) -> None:
	"""
	Save events to database, avoiding duplicates.

	Checks for existing events based on title and source URL.

	Args:
		events: List of event dictionaries with keys:
				- title (required)
				- date (optional)
				- location (optional)
				- url (optional)
	"""
	session = SessionLocal()

	try:
		saved_count = 0
		duplicate_count = 0

		for event_data in events:
			# Check if event already exists
			existing = session.query(EventDB).filter_by(
				title=event_data["title"],
				source_url=event_data.get("url", "")
			).first()

			if not existing:
				# Create new event
				new_event = EventDB(
					title=event_data["title"],
					date=event_data.get("date"),
					location=event_data.get("location", "unbekannt"),
					source_url=event_data.get("url", "")
				)
				session.add(new_event)
				saved_count += 1
			else:
				duplicate_count += 1

		session.commit()
		logger.info(
			f"✓ Saved {saved_count} events, skipped {duplicate_count} duplicates")

	except Exception as e:
		session.rollback()
		logger.error(f"Error saving events: {e}", exc_info=True)
		raise

	finally:
		session.close()


def load_events() -> list:
	"""
	Load all events from database, ordered by date.

	Returns:
		List of EventDB objects (SQLAlchemy ORM objects)
	"""
	session = SessionLocal()

	try:
		events = session.query(EventDB).order_by(EventDB.date).all()
		logger.info(f"Loaded {len(events)} events from database")
		return events

	finally:
		session.close()


def clear_events() -> None:
	"""
	Delete all events from database.

	Warning: This cannot be undone!
	"""
	session = SessionLocal()

	try:
		deleted_count = session.query(EventDB).delete()
		session.commit()
		logger.info(f"✓ Deleted {deleted_count} events from database")

	finally:
		session.close()