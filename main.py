import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect, or_
from jose import JWTError, jwt
from passlib.context import CryptContext
from google import genai
from dotenv import load_dotenv

from database import get_db, engine, Base
from models import User, Team, Project, Task, ActivityLog, Notification

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY")) if os.getenv("GEMINI_API_KEY") else None

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# --- Auth Helpers ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


# --- Lifespan: Table Init & Admin Seeder ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure MySQL tables are initialized
    Base.metadata.create_all(bind=engine)

    # Auto-seed initial admin user if database is empty
    db = next(get_db())
    try:
        admin_exists = db.query(User).filter(User.username == "admin").first()
        if not admin_exists:
            default_admin = User(
                username="admin",
                hashed_password=get_password_hash("admin123"),
                role="admin"
            )
            db.add(default_admin)
            db.commit()
            print("🚀 Default Admin Created! (Username: 'admin', Password: 'admin123')")
    except Exception as e:
        print(f"⚠️ Startup seed warning: {e}")
    finally:
        db.close()

    yield


app = FastAPI(title="AI Remote Team Workspace Platform", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# --- Dynamic Schema Inspector ---

def get_dynamic_schema() -> str:
    """Inspects all live tables and views in MySQL to give Gemini full schema context."""
    inspector = inspect(engine)
    schema_info = []
    for table_name in inspector.get_table_names() + inspector.get_view_names():
        columns = inspector.get_columns(table_name)
        col_desc = ", ".join([f"{col['name']} ({col['type']})" for col in columns])
        schema_info.append(f"Table/View '{table_name}': {col_desc}")
    return "\n".join(schema_info)


# --- Pydantic Request & Response Schemas ---

class Token(BaseModel):
    access_token: str
    token_type: str


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


class QueryRequest(BaseModel):
    prompt: str


class ReassignTaskRequest(BaseModel):
    task_id: int
    new_user_id: int


# --- Auth & UI Routes ---

@app.get("/")
async def serve_home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/login")
async def serve_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.username == form_data.username).first()
        if not user:
            raise HTTPException(status_code=401, detail="Incorrect username or password")

        if not verify_password(form_data.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect username or password")

        access_token = create_access_token(
            data={"sub": user.username, "role": user.role}
        )
        return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"🔥 Login Error Exception: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")


@app.get("/api/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# --- User Management (RBAC Filtered) ---

@app.get("/api/users", response_model=List[UserResponse])
def get_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == "admin":
        return db.query(User).all()
    if current_user.team_id:
        return db.query(User).filter(User.team_id == current_user.team_id).all()
    return [current_user]


@app.post("/api/users", response_model=UserResponse)
def create_user(
        user_data: UserCreate,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Permission Denied: Only admins can register teammates.")

    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists.")

    new_user = User(
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        role=user_data.role,
        timezone=user_data.timezone,
        skills=user_data.skills,
        team_id=user_data.team_id
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


# --- Team Management Endpoints (RBAC Filtered) ---

@app.get("/api/teams", response_model=List[TeamResponse])
def get_teams(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == "admin":
        return db.query(Team).all()
    if current_user.team_id:
        return db.query(Team).filter(Team.id == current_user.team_id).all()
    return []


@app.post("/api/teams", response_model=TeamResponse)
def create_team(
        team_data: TeamCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create teams.")

    new_team = Team(
        name=team_data.name,
        created_by=current_user.id
    )
    db.add(new_team)
    db.commit()
    db.refresh(new_team)
    return new_team


# --- Project REST Endpoints (RBAC Filtered) ---

@app.get("/api/projects", response_model=List[ProjectResponse])
def get_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == "admin":
        return db.query(Project).all()
    if current_user.team_id:
        return db.query(Project).filter(Project.team_id == current_user.team_id).all()
    return []


@app.post("/api/projects", response_model=ProjectResponse)
def create_project(
        project_data: ProjectCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin" and project_data.team_id != current_user.team_id:
        raise HTTPException(status_code=403, detail="Permission Denied to create project outside your team.")

    new_project = Project(
        name=project_data.name,
        status=project_data.status,
        budget=project_data.budget,
        team_id=project_data.team_id
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return new_project


# --- Task Management Endpoints (RBAC Filtered) ---

@app.get("/api/tasks", response_model=List[TaskResponse])
def get_tasks(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if current_user.role == "admin":
        return db.query(Task).all()

    team_project_ids = []
    if current_user.team_id:
        team_projects = db.query(Project.id).filter(Project.team_id == current_user.team_id).all()
        team_project_ids = [p[0] for p in team_projects]

    return db.query(Task).filter(
        or_(
            Task.assigned_to_id == current_user.id,
            Task.project_id.in_(team_project_ids) if team_project_ids else False
        )
    ).all()


@app.post("/api/tasks", response_model=TaskResponse)
def create_task(
        task_data: TaskCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    new_task = Task(
        title=task_data.title,
        project_id=task_data.project_id,
        assigned_to_id=task_data.assigned_to_id,
        status=task_data.status,
        priority=task_data.priority,
        due_date=task_data.due_date
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return new_task


# --- Database Views & Procedure Endpoints ---

@app.get("/api/views/workload")
def get_team_workload(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = db.execute(text("SELECT * FROM v_team_workload")).mappings().all()
    return list(result)


@app.get("/api/views/overdue")
def get_overdue_tasks(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = db.execute(text("SELECT * FROM v_overdue_tasks")).mappings().all()
    return list(result)


@app.post("/api/tasks/reassign")
def reassign_task(
        req: ReassignTaskRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Permission Denied: Only admins can reassign tasks.")
    try:
        db.execute(
            text("CALL sp_reassign_task(:task_id, :new_user_id, :actor_id)"),
            {"task_id": req.task_id, "new_user_id": req.new_user_id, "actor_id": current_user.id}
        )
        db.commit()
        return {"status": "success", "message": f"Task #{req.task_id} successfully reassigned to User #{req.new_user_id}."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Procedure execution failed: {str(e)}")


# --- Conversational AI Engine ---

@app.post("/api/query")
async def execute_conversational_ai(
        req: QueryRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if not gemini_client:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY environment variable missing.")

    schema_context = get_dynamic_schema()

    intent_prompt = f"""
    You are an AI assistant managing a Remote Team Collaboration MySQL database.

    Database Schema & Views:
    {schema_context}

    Determine the user's intent and output strictly JSON in one of these structures:

    1. SELECT / Read Data Query (Views, Audits, Analytics, Tasks):
    {{"action": "SELECT", "sql": "SELECT ... FROM ... LIMIT 100"}}

    2. Reassign Task (Must use Stored Procedure):
    {{"action": "REASSIGN_TASK", "task_id": <int>, "new_user_id": <int>}}

    3. Create Project:
    {{"action": "CREATE_PROJECT", "name": "<val>", "status": "Planning"|"Active"|"Completed", "budget": <float>, "team_id": <int|null>}}

    4. Create Team:
    {{"action": "CREATE_TEAM", "name": "<val>"}}

    5. Create User / Teammate:
    {{"action": "CREATE_USER", "username": "<val>", "password": "<val>", "role": "admin"|"member", "team_id": <int|null>}}

    6. Execute Raw Dynamic Database Statement (INSERT, UPDATE, DELETE):
    {{"action": "EXECUTE_DML", "sql": "UPDATE tasks SET ... WHERE ..."}}

    7. General / Conversational:
    {{"action": "CHAT", "message": "<your answer>"}}

    User prompt: "{req.prompt}"
    """

    try:
        intent_response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=intent_prompt
        )

        clean_json_str = intent_response.text.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean_json_str)
        action = parsed.get("action")

        # --- ACTION 1: Atomic Stored Procedure Execution ---
        if action == "REASSIGN_TASK":
            if current_user.role != "admin":
                return {"action": "REASSIGN_TASK", "reply": "⚠️ Permission Denied: Only admins can reassign tasks.", "sql": None}

            task_id = parsed.get("task_id")
            new_user_id = parsed.get("new_user_id")

            if not task_id or not new_user_id:
                return {"action": "REASSIGN_TASK", "reply": "⚠️ Task ID and New User ID are required to reassign a task.", "sql": None}

            db.execute(
                text("CALL sp_reassign_task(:task_id, :new_user_id, :actor_id)"),
                {"task_id": task_id, "new_user_id": new_user_id, "actor_id": current_user.id}
            )
            db.commit()

            return {
                "action": "REASSIGN_TASK",
                "refresh_table": True,
                "reply": f"🔄 Executed stored procedure `sp_reassign_task`. Task **#{task_id}** is now assigned to User **#{new_user_id}**.",
                "sql": f"CALL sp_reassign_task({task_id}, {new_user_id}, {current_user.id})"
            }

        # --- ACTION 2: CREATE_USER ---
        elif action == "CREATE_USER":
            if current_user.role != "admin":
                return {"action": "CREATE_USER", "reply": "⚠️ Permission Denied: Only admins can register teammates.", "sql": None}

            username = parsed.get("username")
            password = parsed.get("password")
            role = parsed.get("role", "member")
            team_id = parsed.get("team_id")

            if not username or not password:
                return {"action": "CREATE_USER", "reply": "Username and password required.", "sql": None}

            if db.query(User).filter(User.username == username).first():
                return {"action": "CREATE_USER", "reply": f"Username **'{username}'** already exists.", "sql": None}

            new_user = User(username=username, hashed_password=get_password_hash(password), role=role, team_id=team_id)
            db.add(new_user)
            db.commit()

            return {
                "action": "CREATE_USER",
                "refresh_table": True,
                "reply": f"✅ Created teammate **{username}** with role **'{role}'**.",
                "sql": f"INSERT INTO users (username, role, team_id) VALUES ('{username}', '{role}', {team_id})"
            }

        # --- ACTION 3: CREATE_TEAM ---
        elif action == "CREATE_TEAM":
            if current_user.role != "admin":
                return {"action": "CREATE_TEAM", "reply": "⚠️ Permission Denied: Only admins can create teams.", "sql": None}

            team_name = parsed.get("name")
            if not team_name:
                return {"action": "CREATE_TEAM", "reply": "Team name is required.", "sql": None}

            new_team = Team(name=team_name, created_by=current_user.id)
            db.add(new_team)
            db.commit()

            return {
                "action": "CREATE_TEAM",
                "refresh_table": True,
                "reply": f"👥 Created team **'{team_name}'** successfully.",
                "sql": f"INSERT INTO teams (name, created_by) VALUES ('{team_name}', {current_user.id})"
            }

        # --- ACTION 4: CREATE_PROJECT ---
        elif action == "CREATE_PROJECT":
            p_name = parsed.get("name")
            p_status = parsed.get("status", "Planning")
            p_budget = float(parsed.get("budget", 0.0))
            p_team_id = parsed.get("team_id")

            if current_user.role != "admin" and p_team_id != current_user.team_id:
                return {"action": "CREATE_PROJECT", "reply": "⚠️ Permission Denied: Cannot create project outside your team.", "sql": None}

            if not p_name:
                return {"action": "CREATE_PROJECT", "reply": "Please supply a project name.", "sql": None}

            new_project = Project(name=p_name, status=p_status, budget=p_budget, team_id=p_team_id)
            db.add(new_project)
            db.commit()

            return {
                "action": "CREATE_PROJECT",
                "refresh_table": True,
                "reply": f"🚀 Created project **'{p_name}'** under status **'{p_status}'** with budget **${p_budget:,.2f}**.",
                "sql": f"INSERT INTO projects (name, status, budget, team_id) VALUES ('{p_name}', '{p_status}', {p_budget}, {p_team_id})"
            }

        # --- ACTION 5: Dynamic DML Updates ---
        elif action == "EXECUTE_DML":
            raw_sql = parsed.get("sql", "").strip()

            if any(kw in raw_sql.upper() for kw in ["DROP", "ALTER", "TRUNCATE"]):
                raise HTTPException(status_code=400, detail="Security Guardrail: DDL operations are forbidden.")

            db.execute(text(raw_sql))
            db.commit()

            return {
                "action": "EXECUTE_DML",
                "refresh_table": True,
                "reply": "✅ Executed database update successfully.",
                "sql": raw_sql
            }

        # --- ACTION 6: SELECT Queries & Analytics ---
        elif action == "SELECT":
            raw_sql = parsed.get("sql", "").strip()

            if not raw_sql.lower().startswith("select") or any(kw in raw_sql.upper() for kw in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]):
                raise HTTPException(status_code=400, detail="Security Guardrail: Only read-only SELECT operations allowed.")

            if "limit" not in raw_sql.lower():
                raw_sql += " LIMIT 100"

            result = db.execute(text(raw_sql))
            data = [dict(row) for row in result.mappings()]

            synthesis_prompt = f"""
            User Asked: "{req.prompt}"
            Executed Query: `{raw_sql}`
            Query Results: {json.dumps(data, default=str)}

            Provide a clear, human-friendly summary of the query results.
            Use bold text or bullet points for readability. Avoid showing raw JSON output.
            """

            summary_response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=synthesis_prompt
            )

            return {
                "action": "SELECT",
                "reply": summary_response.text.strip(),
                "sql": raw_sql
            }

        # --- ACTION 7: Fallback Chat ---
        else:
            return {
                "action": "CHAT",
                "reply": parsed.get("message", "I can help you analyze workload, manage tasks, or run database reports."),
                "sql": None
            }

    except Exception as e:
        db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"AI Engine Error: {str(e)}")