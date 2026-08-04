from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean
from sqlalchemy.sql import func
from pydantic import BaseModel
from database import Base

# --- SQLAlchemy Database Models ---

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="member", nullable=False)
    timezone = Column(String(50), default="UTC")
    skills = Column(String(255), nullable=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    status = Column(String(50), default="Planning", nullable=False)
    budget = Column(Float, default=0.0, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(150), nullable=False)
    status = Column(String(20), default="todo")
    priority = Column(String(20), default="medium")
    assigned_to_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(DateTime, nullable=True)


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    action = Column(String(255), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message = Column(String(255), nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


# --- Pydantic Schemas ---

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "member"
    timezone: str = "UTC"
    skills: Optional[str] = None
    team_id: Optional[int] = None


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    timezone: str
    skills: Optional[str] = None
    team_id: Optional[int] = None

    class Config:
        from_attributes = True


class TeamCreate(BaseModel):
    name: str


class TeamResponse(BaseModel):
    id: int
    name: str
    created_by: Optional[int] = None

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    name: str
    status: str = "Planning"
    budget: float = 0.0
    team_id: Optional[int] = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    status: str
    budget: float
    team_id: Optional[int] = None

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    title: str
    project_id: int
    assigned_to_id: Optional[int] = None
    status: str = "todo"
    priority: str = "medium"
    due_date: Optional[datetime] = None


class TaskResponse(BaseModel):
    id: int
    project_id: int
    title: str
    status: str
    priority: str
    assigned_to_id: Optional[int] = None
    due_date: Optional[datetime] = None

    class Config:
        from_attributes = True