from sqlalchemy import Column, Integer, String, Float
from pydantic import BaseModel
from database import Base

# --- SQLAlchemy Database Models ---

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="user", nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    status = Column(String(50), default="Planning", nullable=False)
    budget = Column(Float, default=0.0, nullable=False)


# --- Pydantic Schemas ---

class ProjectCreate(BaseModel):
    name: str
    status: str = "Planning"
    budget: float


class ProjectResponse(BaseModel):
    id: int
    name: str
    status: str
    budget: float

    class Config:
        from_attributes = True