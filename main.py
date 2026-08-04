import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates 
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect
from jose import JWTError, jwt
from passlib.context import CryptContext
from google import genai
from dotenv import load_dotenv

from database import get_db, engine, Base
from models import User, Project, ProjectCreate, ProjectResponse

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY")) if os.getenv("GEMINI_API_KEY") else None

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI(title="AI Enterprise Database Workspace")
templates = Jinja2Templates(directory="templates")

Base.metadata.create_all(bind=engine)


# --- Dynamic Schema Inspector ---

def get_dynamic_schema() -> str:
    inspector = inspect(engine)
    schema_info = []
    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        col_desc = ", ".join([f"{col['name']} ({col['type']})" for col in columns])
        schema_info.append(f"Table '{table_name}': {col_desc}")
    return "\n".join(schema_info)


# --- Auth Helpers ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
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


# --- Schemas ---

class Token(BaseModel):
    access_token: str
    token_type: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"


class UserResponse(BaseModel):
    id: int
    username: str
    role: str

    class Config:
        from_attributes = True


class QueryRequest(BaseModel):
    prompt: str


# --- Routes ---

@app.get("/")
async def serve_home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/login")
async def serve_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/api/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# Standard REST Endpoints
@app.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_teammate(user_data: UserCreate, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create teammates.")
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists.")

    new_user = User(username=user_data.username, hashed_password=get_password_hash(user_data.password),
                    role=user_data.role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.get("/api/projects", response_model=List[ProjectResponse])
def get_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Project).all()


@app.post("/api/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(project: ProjectCreate, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    db_project = Project(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


# --- Conversational AI Assistant Route ---

@app.post("/api/query")
async def execute_conversational_ai(
        req: QueryRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if not gemini_client:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY environment variable missing.")

    schema_context = get_dynamic_schema()

    # Pass 1: Parse User Intent & Action
    intent_prompt = f"""
    You are an AI assistant managing a MySQL database.

    Database Schema:
    {schema_context}

    Determine the user's intent and output strictly JSON in one of these four structures:

    1. SELECT Query (Reading data):
    {{"action": "SELECT", "sql": "SELECT ... FROM ... LIMIT 100"}}

    2. Create User (Register teammate):
    {{"action": "CREATE_USER", "username": "<val>", "password": "<val>", "role": "user" or "admin"}}

    3. Create Project:
    {{"action": "CREATE_PROJECT", "name": "<val>", "status": "Planning"|"Active"|"Completed", "budget": <float>}}

    4. General / Out of scope:
    {{"action": "CHAT", "message": "<your answer>"}}

    User prompt: "{req.prompt}"
    """

    try:
        # Step 1: Detect intent
        intent_response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=intent_prompt
        )

        # Clean raw JSON response
        clean_json_str = intent_response.text.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean_json_str)
        action = parsed.get("action")

        # --- Handle Action 1: CREATE_USER via Chat ---
        if action == "CREATE_USER":
            if current_user.role != "admin":
                return {
                    "action": "CREATE_USER",
                    "reply": "⚠️ Permission Denied: Only administrator accounts can create new teammates via AI chat.",
                    "sql": None
                }

            username = parsed.get("username")
            password = parsed.get("password")
            role = parsed.get("role", "user")

            if not username or not password:
                return {"action": "CREATE_USER",
                        "reply": "Please provide both a username and password to create a teammate.", "sql": None}

            if db.query(User).filter(User.username == username).first():
                return {"action": "CREATE_USER", "reply": f"The username **'{username}'** is already taken.",
                        "sql": None}

            new_user = User(username=username, hashed_password=get_password_hash(password), role=role)
            db.add(new_user)
            db.commit()

            return {
                "action": "CREATE_USER",
                "reply": f"✅ Successfully created teammate **{username}** with role **'{role}'**.",
                "sql": f"INSERT INTO users (username, role) VALUES ('{username}', '{role}')"
            }

        # --- Handle Action 2: CREATE_PROJECT via Chat ---
        elif action == "CREATE_PROJECT":
            p_name = parsed.get("name")
            p_status = parsed.get("status", "Planning")
            p_budget = float(parsed.get("budget", 0.0))

            if not p_name:
                return {"action": "CREATE_PROJECT", "reply": "Please specify a project name.", "sql": None}

            new_project = Project(name=p_name, status=p_status, budget=p_budget)
            db.add(new_project)
            db.commit()

            return {
                "action": "CREATE_PROJECT",
                "refresh_table": True,
                "reply": f"🚀 Created new project **'{p_name}'** under status **'{p_status}'** with budget **${p_budget:,.2f}**.",
                "sql": f"INSERT INTO projects (name, status, budget) VALUES ('{p_name}', '{p_status}', {p_budget})"
            }

        # --- Handle Action 3: SELECT Data Query ---
        elif action == "SELECT":
            raw_sql = parsed.get("sql", "").strip()

            # Guardrails: Read-only check
            if not raw_sql.lower().startswith("select") or any(
                    kw in raw_sql.upper() for kw in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]):
                raise HTTPException(status_code=400,
                                    detail="Security Violation: Only read-only SELECT queries are allowed.")

            # Automatic Pagination Enforcement
            if "limit" not in raw_sql.lower():
                raw_sql += " LIMIT 100"

            # Execute SQL
            result = db.execute(text(raw_sql))
            data = [dict(row) for row in result.mappings()]

            # Step 2: Pass data back to Gemini for conversational translation
            synthesis_prompt = f"""
            User Asked: "{req.prompt}"
            Executed SQL: `{raw_sql}`
            SQL Query Results: {json.dumps(data)}

            Summarize these results into a friendly, clear, human conversational answer. 
            Do NOT display raw JSON. Use bullet points or bold text if listing multiple items.
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

        # --- Handle Action 4: General Chat / Fallback ---
        else:
            return {
                "action": "CHAT",
                "reply": parsed.get("message", "I can help you view data or create projects and teammates."),
                "sql": None
            }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"AI Assistant Error: {str(e)}")