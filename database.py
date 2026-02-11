import json
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, String, Integer, \
	DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite DB Setup
engine = create_engine("sqlite:///crawl_cache.db", echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class UrlCache(Base):
	"""Speichert die Ergebnisse pro URL mit Zeitstempel"""
	__tablename__ = "url_cache"

	id = Column(Integer, primary_key=True)
	url = Column(String, unique=True, index=True)
	raw_results = Column(
		Text)  # Das extrahierte JSON der AI als String
	last_crawled = Column(DateTime, default=datetime.now)


def init_db():
	Base.metadata.create_all(bind=engine)


def get_smart_cache(url: str, max_age_hours: int = 1):
	"""
	Prüft: Haben wir diese URL in den letzten X Stunden gecrawlt?
	Gibt die Daten zurück oder None, wenn ein Live-Crawl nötig ist.
	"""
	session = SessionLocal()
	try:
		# Suche nach der URL in der DB
		cached_entry = session.query(UrlCache).filter_by(
			url=url).first()

		if cached_entry:
			# Check, ob der Crawl noch frisch genug ist
			age_limit = datetime.now() - timedelta(
				hours=max_age_hours)
			if cached_entry.last_crawled > age_limit:
				print(
					f"--- DB HIT: Nutze Cache für {url} (Alter: {datetime.now() - cached_entry.last_crawled}) ---")
				return json.loads(cached_entry.raw_results)

		return None
	finally:
		session.close()


def update_url_cache(url: str, results: list):
	"""Speichert oder aktualisiert die Ergebnisse für eine URL"""
	session = SessionLocal()
	try:
		results_json = json.dumps(results)
		entry = session.query(UrlCache).filter_by(url=url).first()

		if entry:
			entry.raw_results = results_json
			entry.last_crawled = datetime.now()
		else:
			new_entry = UrlCache(url=url, raw_results=results_json)
			session.add(new_entry)

		session.commit()
	finally:
		session.close()