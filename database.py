from sqlalchemy import create_engine, Column, String, Integer, \
	DateTime
from sqlalchemy.orm import sessionmaker, declarative_base

# Create SQLite database engine
engine = create_engine("sqlite:///events.db", echo=False)

# Create session factory for database operations
SessionLocal = sessionmaker(bind=engine)

# Create declarative base class for ORM models
Base = declarative_base()


class EventDB(Base):
	"""
	Database model for storing event information.

	Attributes:
		id: Primary key, auto-incrementing integer
		title: Event name/title (required)
		date: Event date as datetime object (optional)
		location: Event location/venue (optional)
		source_url: Original URL where event was found (optional)
	"""
	__tablename__ = "events"

	id = Column(Integer, primary_key=True, index=True)
	title = Column(String, nullable=False)
	date = Column(DateTime)
	location = Column(String)
	source_url = Column(String)


# Create all tables in the database
Base.metadata.create_all(bind=engine)