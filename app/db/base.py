from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import all models here so Alembic/Base can discover them
from app.db.models import *
from app.db.settings_models import *
from app.db.inbox_models import *
from app.db.flow_models import *
