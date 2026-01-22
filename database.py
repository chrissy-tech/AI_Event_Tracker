"""
Database models and configuration.
Defines the EventDB table structure.
"""
from sqlalchemy import (create_engine, Column, String, Integer,
						DateTime, Boolean)
from sqlalchemy.orm import sessionmaker, declarative_base

# Create SQLite database engine
engine = create_engine("sqlite:///events.db", echo=False)

# Create session factory for database operations
SessionLocal = sessionmaker(bind=engine)

# Create declarative base for ORM models
Base = declarative_base()


class EventDB(Base):
	"""
	Event database model.

	Attributes:
		id: Primary key
		title: Event name (required)
		date: Event date (optional)
		location: Venue/city (optional)
		source_url: Where event was found (optional)
		category: Type of event (Music, Market, etc.)
		is_free: True if entry is free
		is_outdoor: True if event is outside
	"""
	__tablename__ = "events"

	id = Column(Integer, primary_key=True, index=True)
	title = Column(String, nullable=False)
	date = Column(DateTime, nullable=True)
	location = Column(String, nullable=True)
	source_url = Column(String, nullable=True)
	category = Column(String)  # "Konzert", "Festival", "Markt"
	#category = Column(String, default="Sonstiges")
	is_free = Column(Boolean, default=False)
	is_outdoor = Column(Boolean, default=False)


def init_db():
	"""
	Initialize database by creating all tables.
	Called once at application startup.
	"""
	Base.metadata.create_all(bind=engine)