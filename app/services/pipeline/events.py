import logging
from uuid import UUID
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.repositories.all_repos import processing_event_repo
from app.core.enums import EventLevel

logger = logging.getLogger(__name__)

class EventLogger:
    def __init__(self):
        pass

    def log(self,
            db: Optional[Session],
            level: EventLevel, 
            event_type: str, 
            stage: str, 
            message: str, 
            batch_id: Optional[UUID] = None,
            candidate_id: Optional[UUID] = None,
            payload: Optional[Dict[str, Any]] = None):

        owns_session = db is None
        if owns_session:
            db = SessionLocal()

        event = {
            "level": level,
            "event_type": event_type,
            "stage": stage,
            "message": message,
            "batch_id": batch_id,
            "candidate_id": candidate_id,
            "payload_json": payload or {}
        }

        try:
            processing_event_repo.create(db, obj_in=event)
        except Exception:
            logger.exception("No se ha podido registrar el evento %s", event_type)
        finally:
            if owns_session and db is not None:
                db.close()

event_logger = EventLogger()
