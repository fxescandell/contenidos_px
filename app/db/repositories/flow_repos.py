from typing import List, Optional, Any, Dict
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.repositories.base import BaseRepository
from app.db.flow_models import Flow


class FlowRepository(BaseRepository[Flow]):
    def __init__(self):
        super().__init__(Flow)

    def get_by_municipality(self, db: Session, municipality: str) -> List[Flow]:
        return db.execute(
            select(self.model).where(self.model.municipality == municipality).order_by(self.model.name)
        ).scalars().all()

    def get_enabled(self, db: Session) -> List[Flow]:
        return db.execute(
            select(self.model).where(self.model.enabled == True).order_by(self.model.municipality, self.model.name)
        ).scalars().all()

    def get_by_municipality_and_category(self, db: Session, municipality: str, category: str) -> Optional[Flow]:
        return db.execute(
            select(self.model).where(
                self.model.municipality == municipality,
                self.model.category == category
            )
        ).scalar_one_or_none()

    def get_all_ordered(self, db: Session) -> List[Flow]:
        return db.execute(
            select(self.model).order_by(self.model.municipality, self.model.name)
        ).scalars().all()


flow_repo = FlowRepository()
