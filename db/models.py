from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()

class Trip(Base):
    __tablename__ = "trips"

    trip_id = Column(String, primary_key=True)      # same value as LangGraph thread_id
    user_id = Column(String, nullable=True)

    destination = Column(String, nullable=False)
    origin_city = Column(String, nullable=False)
    start_date = Column(String, nullable=False)  # store as ISO date string for now
    end_date = Column(String, nullable=False)
    num_travelers = Column(Integer, nullable=False)
    budget = Column(Float, nullable=False)
    currency = Column(String, nullable=False)

    status = Column(String, nullable=False, default="planning")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Itinerary(Base):
    __tablename__ = "itineraries" 

    trip_id = Column(String, ForeignKey("trips.trip_id"), primary_key=True)
    itinerary = Column(JSON, nullable=False)
    approved_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))