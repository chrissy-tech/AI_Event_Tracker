from database import SessionLocal, EventDB
import logging

logger = logging.getLogger(__name__)


def save_events(events):
	"""
	Saves events to database without creating duplicates.

	Checks for existing events based on title and source URL
	before inserting new records.

	Args:
		events: List of event dictionaries containing title, date,
				location, and url keys

	Raises:
		Exception: If database operation fails
	"""
	session = SessionLocal()
	try:
		saved_count = 0
		duplicate_count = 0

		for evt in events:
			# Check if event already exists
			existing = session.query(EventDB).filter_by(
				title=evt["title"],
				source_url=evt.get("url", "")
			).first()

			if not existing:
				new_event = EventDB(
					title=evt["title"],
					date=evt.get("date"),
					location=evt.get("location", ""),
					source_url=evt.get("url", "")
				)
				session.add(new_event)
				saved_count += 1
			else:
				duplicate_count += 1

		session.commit()
		logger.info(
			f"Saved {saved_count} new events, skipped {duplicate_count} duplicates")

	except Exception as e:
		session.rollback()
		logger.error(f"Error saving events: {e}")
		raise
	finally:
		session.close()


def load_events():
	"""
	Loads all events from database sorted by date.

	Returns:
		list: List of EventDB objects ordered by date (ascending)
	"""
	session = SessionLocal()
	try:
		events = session.query(EventDB).order_by(EventDB.date).all()
		logger.info(f"Loaded {len(events)} events from database")
		return events
	finally:
		session.close()


def clear_events():
	"""
	Deletes all events from database.

	Warning: This operation cannot be undone.
	"""
	session = SessionLocal()
	try:
		deleted_count = session.query(EventDB).delete()
		session.commit()
		logger.info(f"Deleted {deleted_count} events from database")
	finally:
		session.close()