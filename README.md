# 🤖 AI Enterprise Database Workspace

**Your database, your words — powered by AI.**

AI Enterprise Database Workspace makes database management simpler by letting users interact with their data using everyday language instead of writing SQL queries manually. Built with FastAPI and Google Gemini, it combines AI-powered database interaction, project management, and secure team access in one workspace.

## ✨ Key Features

- 💬 **Talk to Your Database:** Ask questions in plain English and get easy-to-understand answers.
- 🧠 **AI-Powered SQL:** Uses Google Gemini to interpret requests and generate SQL queries.
- 📊 **Smart Data Insights:** Turns database results into clear, conversational summaries.
- 🔐 **Secure Authentication:** JWT-based login with hashed passwords.
- 👥 **Team Management:** Allows administrators to create and manage teammate accounts.
- 📁 **Project Management:** Create and retrieve project details through APIs or AI chat.
- 🔎 **Dynamic Schema Detection:** Automatically discovers database tables and columns to help the AI understand your data.

## 🛠️ Tech Stack

- **Backend:** Python, FastAPI
- **Database:** SQLAlchemy and a configured relational database
- **AI:** Google Gemini (`gemini-2.5-flash`)
- **Security:** JWT, OAuth2, Passlib, bcrypt
- **Templates:** HTML and Jinja2

## 📂 Project Structure

```text
project/
├── main.py              # API routes and AI logic
├── database.py          # Database connection
├── models.py            # User and project models
├── templates/
│   ├── index.html       # Main workspace
│   └── login.html       # Login page
├── .env                 # Private configuration
├── requirements.txt     # Python dependencies
└── README.md
```

## 🚀 Getting Started

**1. Clone the repository**

```bash
git clone <YOUR_REPOSITORY_URL>
cd <PROJECT_FOLDER>
```

**2. Set up your environment**

```bash
python -m venv .venv
.venv\Scripts\activate
pip install fastapi "uvicorn[standard]" sqlalchemy "python-jose[cryptography]" "passlib[bcrypt]" bcrypt python-multipart jinja2 google-genai python-dotenv
```

**3. Configure your `.env` file**

```env
SECRET_KEY=your_secure_secret_key
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=your_database_connection_url
```

Make sure `database.py` uses the corresponding database environment variable.

**4. Launch the application**

```bash
uvicorn main:app --reload
```

Visit **http://127.0.0.1:8000** to open the workspace or **http://127.0.0.1:8000/docs** to explore the API.

## 🔌 API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/token` | Authenticate users |
| GET | `/api/me` | View the current user |
| POST | `/api/users` | Create teammates (admin only) |
| GET | `/api/projects` | Retrieve projects |
| POST | `/api/projects` | Create projects |
| POST | `/api/query` | Interact with the AI assistant |

## 🧠 How It Works

1. **Ask:** Enter a question or command in natural language.
2. **Understand:** Gemini identifies the intent using the database schema.
3. **Execute:** The backend processes supported actions and database queries.
4. **Respond:** The AI presents results in a clear, human-friendly format.

**Try asking:**
- "Show me all active projects."
- "Which projects have the highest budgets?"
- "Create a project with a budget of 50,000."
- "Create a new teammate."

## 🔒 Security & Reliability

The application includes JWT authentication, password hashing, and role-based permissions. Before production use, strengthen SQL validation, restrict AI-generated queries with database-level read-only permissions, and validate all AI-generated actions. Keep API keys and database credentials private, and never commit your `.env` file to GitHub.

## 🔮 What's Next?

Future improvements could include interactive dashboards, saved queries, chat history, data exports, audit logs, and automated testing.

## 📄 License

Add a `LICENSE` file to define how others can use, modify, and contribute to the project.

---

*Built with Python, FastAPI, SQLAlchemy, and Google Gemini — making database interaction more natural, accessible, and efficient.*
