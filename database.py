"""
Database models and configuration.
Defines the EventDB table structure.
"""
from sqlalchemy import create_engine, Column, String, Integer, \
	DateTime
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

	Stores event information with title, date, location, and source URL.
	"""
	__tablename__ = "events"

	id = Column(Integer, primary_key=True, index=True)
	title = Column(String, nullable=False)
	date = Column(DateTime, nullable=True)
	location = Column(String, nullable=True)
	source_url = Column(String, nullable=True)


def init_db():
	"""
	Initialize database by creating all tables.

	Called once at application startup.
	"""
	Base.metadata.create_all(bind=engine)