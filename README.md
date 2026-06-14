# AI-Powered Zoho Projects Assistant

A production-grade conversational AI assistant that integrates with Zoho Projects via its REST API. Users authenticate with their own Zoho account and manage projects and tasks through a natural language chat interface — no Zoho UI required.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [LangGraph Execution Flow](#langgraph-execution-flow)
- [End-to-End Request Flow](#end-to-end-request-flow)
- [Tech Stack](#tech-stack)
- [Key Design Decisions](#key-design-decisions)
- [Database Schema](#database-schema)
- [Memory Design](#memory-design)
- [Security Considerations](#security-considerations)
- [Local Setup](#local-setup)
- [Running Tests](#running-tests)
- [Example Usage](#example-usage)
- [Project Structure](#project-structure)
- [Interview Discussion Topics](#interview-discussion-topics)
- [Future Improvements](#future-improvements)

---

## Overview

Users sign in with their Zoho account via OAuth 2.0. Once authenticated, they interact with a multi-agent AI system that understands natural language requests, fetches live data from the Zoho Projects API, and executes write operations only after explicit user confirmation.

**Example conversations:**

```
You:  What projects do I have?
Bot:  You have 3 projects: Test, Backend, Configuration.

You:  Show tasks in the Test project
Bot:  Test project has 4 tasks: API Integration, Fix login bug...

You:  Create a task called Deploy to staging
Bot:  I'm about to create task "Deploy to staging" in Test project. Confirm?
You:  Confirm
Bot:  ✅ Task created. Task ID: 12345

You:  (new session, next day)
      Show tasks
Bot:  Using your last active project: Test
      Here are the tasks in Test...
```

---

## Features

### Authentication
- Zoho OAuth 2.0 — users authenticate with their own Zoho account; no shared credentials
- Session-based authentication with secure, HTTP-only cookies
- OAuth access and refresh tokens encrypted at rest using Fernet symmetric encryption

### Project Management
- List all active projects in your Zoho portal
- View tasks in any project with optional filters (status, assignee)
- View full task details
- View all project members

### Task Management
- Create a task with optional assignee, due date, and priority
- Update a task (name, status, assignee, due date, and more)
- Delete a task
- All write operations pause for explicit Human-in-the-Loop (HIL) confirmation before execution

### Memory
- **Thread memory** — each chat thread maintains its own message history in PostgreSQL; switching threads fully restores context
- **Long-term memory** — persisted across sessions per user:
  - `last_active_project` — used automatically when no project is specified in a new thread
  - `recent_projects` — the last 5 projects interacted with
  - `frequent_assignees` — assignees repeatedly used in task creation

---

## Architecture

The system follows a layered architecture. The Next.js frontend communicates with a FastAPI backend, which delegates reasoning and tool execution to a LangGraph multi-agent graph. The graph calls the Zoho Projects REST API and persists state to PostgreSQL.

```
┌──────────────────────────────────┐
│         Browser (Next.js)        │
│  Chat UI · Thread sidebar        │
│  HIL confirm/cancel cards        │
└────────────────┬─────────────────┘
                 │ HTTPS / HTTP
┌────────────────▼─────────────────┐
│         FastAPI Backend          │
│  POST /chat  · GET|POST /threads │
│  GET /auth/login · GET /callback │
│  Session validation middleware   │
└────────────────┬─────────────────┘
                 │ Python in-process
┌────────────────▼─────────────────┐
│       LangGraph Agent Graph      │
│                                  │
│  ┌────────────────────────────┐  │
│  │ Router Node                │  │  Classifies intent: read / write / clarify
│  ├────────────────────────────┤  │
│  │ Query Agent (ReAct)        │  │  Handles all read operations via LangChain tools
│  ├────────────────────────────┤  │
│  │ Action Agent               │  │  Parses write intent, constructs pending action
│  ├────────────────────────────┤  │
│  │ HIL Node                   │  │  Graph interrupt — awaits user confirm or cancel
│  ├────────────────────────────┤  │
│  │ Memory Writer              │  │  Persists project and assignee context to DB
│  └────────────────────────────┘  │
└────────────────┬─────────────────┘
                 │ HTTPS REST
┌────────────────▼─────────────────┐
│      Zoho Projects REST API      │
│  Portals · Projects · Tasks      │
│  Members · Task details          │
└────────────────┬─────────────────┘
                 │
┌────────────────▼─────────────────┐
│          PostgreSQL              │
│  users · sessions · tokens       │
│  chat_threads · chat_messages    │
│  long_term_memory                │
└──────────────────────────────────┘
```

---

## LangGraph Execution Flow

Every chat message runs through the following deterministic graph. Each node is an async Python function. The graph is compiled with a LangGraph `MemorySaver` checkpointer and an `interrupt_before` on the HIL node to support multi-turn confirmation.

```
User Message
     │
     ▼
┌──────────────┐
│ Router Node  │  LLM classifies intent as: read | write | clarify
└──────┬───────┘
       │
       ├─── read ────►  ┌─────────────────────┐
       │                │ Query Agent (ReAct)  │  Calls list_projects, list_tasks,
       │                │                     │  get_task_details, list_project_members,
       │                └──────────┬──────────┘  get_task_utilisation
       │                           │
       ├─── write ───►  ┌──────────▼──────────┐
       │                │   Action Agent      │  Parses intent into a PendingAction JSON
       │                └──────────┬──────────┘
       │                           │
       │                ┌──────────▼──────────┐
       │                │     HIL Node        │  Graph pauses — frontend shows confirm/cancel
       │                └──────────┬──────────┘
       │                           │  (user confirms)
       │                ┌──────────▼──────────┐
       │                │   Action Agent      │  Executes create_task / update_task / delete_task
       │                └──────────┬──────────┘
       │                           │
       └─── clarify ──► ┌──────────▼──────────┐
                        │  Memory Writer      │  Updates last_active_project, recent_projects,
                        └──────────┬──────────┘  frequent_assignees in PostgreSQL
                                   │
                                   ▼
                             Response returned to frontend
```

**Key graph properties:**
- `interrupt_before=["hil_confirmation"]` — the graph checkpoints its state and pauses before executing any write, enabling stateful resumption
- `MemorySaver` checkpointer — stores in-process graph state per `thread_id`, providing short-term conversational continuity within a server session
- Thread history from PostgreSQL — loaded on every request and injected into the initial graph state, providing durable cross-restart continuity

---

## End-to-End Request Flow

The following describes the complete lifecycle of a single user message.

**1. User submits a message**
The Next.js frontend sends a `POST /api/chat` request with `{ message, session_id, thread_id }`.

**2. Session validation**
FastAPI extracts the session token from the HTTP-only cookie. The `get_current_user` dependency validates it against the `sessions` table and returns the authenticated `User` object. Requests with invalid or expired sessions receive a `401` and are redirected to `/login`.

**3. Thread resolution**
If a `thread_id` is provided, the chat endpoint retrieves the existing `ChatThread` and verifies it belongs to the authenticated user. If no `thread_id` is provided, a new thread is created and auto-titled from the first 60 characters of the message.

**4. History loading**
All `ChatMessage` rows for the thread are loaded from PostgreSQL, converted to LangChain `HumanMessage` / `AIMessage` objects, and prepended to the graph input. This gives the LLM full conversational context across page reloads and server restarts.

**5. Long-term memory injection**
The user's `long_term_memory` record is loaded. If it contains a `last_active_project_id` and the thread has no prior project context, it is injected into the graph's initial state. `recent_projects` and `frequent_assignees` are prepended to the user's message as a silent context hint for the LLM.

**6. LangGraph execution**
The graph is invoked via `graph.ainvoke(input_state, config={"configurable": {"thread_id": ...}})`. The Router node classifies intent, and the appropriate agent executes. For write operations, the graph pauses at the HIL node and returns a `pending_action` in the response — no write has occurred yet.

**7. HIL confirmation (write operations only)**
The frontend renders a confirmation card. When the user clicks Confirm or Cancel, a follow-up request is sent with `hil_response: "confirm" | "cancel"`. The graph resumes from its checkpoint and either executes or discards the pending action.

**8. Persistence**
After the graph completes, the user's message and the assistant's reply are written to `chat_messages`. The Memory Writer node has already updated `long_term_memory` with the latest project and assignee context.

**9. Response**
The `ChatResponse` is returned with `reply`, `thread_id`, and optionally `pending_action` if a write is awaiting confirmation.

---

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Frontend | Next.js, React, TypeScript | 15 / 19 / 5.7 |
| Backend | FastAPI, Python | 0.115 / 3.11+ |
| AI Agents | LangGraph, LangChain Core | 0.2 / 0.3 |
| LLM | AWS Bedrock or Google Gemini | — |
| Database ORM | SQLAlchemy (async) + asyncpg | 2.0 / 0.30 |
| Migrations | Alembic | 1.14 |
| Database | PostgreSQL | 14+ |

---

## Key Design Decisions

**Why FastAPI?**
FastAPI provides native `async/await` support, which is essential for non-blocking I/O when concurrently calling the Zoho REST API and PostgreSQL. Its automatic OpenAPI schema generation and Pydantic-based request validation reduce boilerplate significantly.

**Why LangGraph?**
LangGraph enables a stateful, interruptible multi-agent graph. The `interrupt_before` mechanism is what makes Human-in-the-Loop confirmation possible without polling or websockets — the graph checkpoints its state and resumes on the next HTTP request. A simpler chain-based approach cannot model this pattern cleanly.

**Why PostgreSQL?**
All application state — users, sessions, OAuth tokens, chat history, and long-term memory — lives in a single relational database. PostgreSQL's JSONB columns store flexible memory structures (recent projects, frequent assignees) without requiring a separate document store. Cascading deletes enforce referential integrity automatically.

**Why Alembic?**
Alembic provides version-controlled, reversible schema migrations. Each change to the database schema is a tracked migration file, making the schema history auditable and deployments reproducible. `alembic upgrade head` is the only command needed to bring any environment up to date.

**Why OAuth 2.0 (not API keys)?**
Zoho's OAuth 2.0 flow means the application never stores a user's Zoho password. Each user authenticates directly with Zoho and grants scoped permissions. Tokens are refreshed automatically and encrypted at rest. This is the correct security model for a multi-user SaaS integration.

---

## Database Schema

| Table | Purpose |
|---|---|
| `users` | One row per authenticated Zoho user (`zoho_user_id`, `email`, `display_name`) |
| `oauth_tokens` | Fernet-encrypted Zoho access and refresh tokens, one per user |
| `sessions` | HTTP session tokens with expiry timestamps, used for cookie-based auth |
| `chat_threads` | Named conversation threads belonging to a user |
| `chat_messages` | Individual messages (`user` or `assistant`) ordered within a thread |
| `long_term_memory` | Per-user persistent context: last active project, recent projects, frequent assignees |

Deleting a `User` cascades to all child rows. Deleting a `ChatThread` cascades to its `ChatMessage` rows.

---

## Memory Design

### Short-term Memory (Thread-scoped)

- Every message exchange is persisted to `chat_messages`
- On each request, the full thread history is loaded and injected into the LangGraph input state as `HumanMessage` / `AIMessage` objects
- Switching threads fully restores the context of that thread, including project references

### Long-term Memory (Cross-session, Per-user)

Stored in the `long_term_memory` table and updated by the Memory Writer node at the end of every graph turn.

| Field | Type | Description |
|---|---|---|
| `last_active_project_id` | `VARCHAR` | Zoho numeric ID of the most recently used project |
| `recent_projects` | `JSONB` | Ordered list of up to 5 recently used project names |
| `frequent_assignees` | `JSONB` | Names of assignees repeatedly used in task creation (up to 10) |

When a user starts a new thread without specifying a project, the assistant automatically falls back to `last_active_project_id` and notifies the user: `Using your last active project: Test`.

---

## Security Considerations

### OAuth 2.0 Authentication
The application implements the OAuth 2.0 Authorization Code flow. Users are redirected to Zoho's authorization server, grant scoped permissions, and are redirected back with an authorization code. The backend exchanges this code for access and refresh tokens. The application never has access to the user's Zoho credentials.

### Token Encryption at Rest
Zoho OAuth tokens are encrypted using Fernet symmetric encryption (`cryptography` library) before being written to the database. The `SECRET_KEY` environment variable holds the Fernet key. Tokens are decrypted in memory only when an API request is being made and are never logged or returned to the client.

### Session Management
Sessions are stored in the `sessions` table with an expiry timestamp. The session token is issued as an HTTP-only, `SameSite=Lax` cookie — it is not accessible from JavaScript, which eliminates XSS-based session theft. Expired sessions are rejected at the `get_current_user` dependency layer.

### HTTP-only Cookies
All authentication state is stored in HTTP-only cookies. The frontend never holds or transmits the session token explicitly — it is automatically included by the browser on same-origin requests.

### Human-in-the-Loop Confirmation
No write operation (create, update, or delete task) is executed without a separate confirmation request from the user. The LangGraph graph checkpoints its state before the HIL node and only proceeds when `hil_response: "confirm"` is received. Cancel is permanent — the pending action is discarded.

### Environment Variable Management
All secrets (`SECRET_KEY`, `ZOHO_CLIENT_SECRET`, `DATABASE_URL`, AWS credentials) are loaded exclusively from environment variables via Pydantic `Settings`. A `.env.example` file documents all required variables without containing any real values. The `.env` file is excluded from version control via `.gitignore`.

---

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL (running locally)
- A Zoho account with Projects access
- AWS credentials configured (for Bedrock) **or** a Google Gemini API key

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/AI-Powered-Zoho-Project-Chatbot.git
cd AI-Powered-Zoho-Project-Chatbot
```

### 2. Configure Zoho OAuth

1. Go to [https://api-console.zoho.in/](https://api-console.zoho.in/)
2. Create a **Server-based Application**
3. Set the redirect URI to `http://localhost:3000/auth/callback`
4. Copy your **Client ID** and **Client Secret**

Required OAuth scopes (the application configures these automatically in the redirect URL):
- `ZohoProjects.projects.READ`
- `ZohoProjects.tasks.ALL`
- `ZohoProjects.users.READ`

### 3. Set Up the Backend

```bash
cd backend
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -e ".[dev]"
```

### 4. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `backend/.env` with your values:

| Variable | Description |
|---|---|
| `ZOHO_CLIENT_ID` | From Zoho API Console |
| `ZOHO_CLIENT_SECRET` | From Zoho API Console |
| `ZOHO_REDIRECT_URI` | Must be `http://localhost:3000/auth/callback` |
| `DATABASE_URL` | e.g. `postgresql+asyncpg://postgres:password@localhost:5432/zoho_chatbot` |
| `SECRET_KEY` | Fernet encryption key — generate with the command below |
| `LLM_PROVIDER` | `bedrock` (default) or `gemini` |
| `BEDROCK_MODEL_ID` | e.g. `us.amazon.nova-lite-v1:0` |
| `AWS_REGION` | e.g. `us-east-1` |
| `GOOGLE_API_KEY` | Required only when `LLM_PROVIDER=gemini` |

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 5. Create the Database and Run Migrations

```bash
createdb zoho_chatbot

cd backend
alembic upgrade head
```

### 6. Start the Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

### 7. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## Running Tests

```bash
cd backend
pytest tests/ -v
```

---

## Example Usage

| Prompt | Behaviour |
|---|---|
| `What projects do I have?` | Lists all active Zoho projects in the portal |
| `Show tasks in the Test project` | Lists all tasks in the named project |
| `Show tasks` | Uses the last active project from long-term memory |
| `Who are the project members?` | Lists all members of the current project |
| `Show task utilisation` | Summarises task count per team member |
| `Create a task called Deploy to staging` | Shows a confirmation card — no action until approved |
| `Update task Deploy to staging, set status to completed` | Shows a confirmation card — no action until approved |
| `Delete task 12345` | Shows a confirmation card — no action until approved |
| `Show tasks in that project` | Resolves the anaphoric reference from conversation context |

---

## Project Structure

```
AI-Powered-Zoho-Project-Chatbot/
│
├── backend/
│   ├── app/
│   │   │
│   │   ├── agents/
│   │   │   ├── graph.py            # Assembles and compiles the LangGraph state machine
│   │   │   ├── router.py           # Classifies each user message as read / write / clarify
│   │   │   ├── query_agent.py      # ReAct agent that handles all read operations via tools
│   │   │   ├── action_agent.py     # Parses write intent, enforces HIL, executes on confirm
│   │   │   ├── hil_node.py         # Pauses the graph until the user confirms or cancels
│   │   │   ├── memory_writer.py    # Persists project and assignee context after every turn
│   │   │   └── state.py            # GraphState TypedDict shared across all agent nodes
│   │   │
│   │   ├── models/
│   │   │   ├── db.py               # SQLAlchemy ORM models for all database tables
│   │   │   └── schemas.py          # Pydantic request / response schemas for the API
│   │   │
│   │   ├── routers/
│   │   │   ├── auth.py             # OAuth 2.0 login, callback, and session creation
│   │   │   ├── chat.py             # POST /chat — loads history, invokes graph, persists reply
│   │   │   ├── threads.py          # Thread CRUD: create, list, get messages, delete
│   │   │   └── health.py           # GET /health — liveness check endpoint
│   │   │
│   │   ├── services/
│   │   │   ├── zoho_client.py      # Async HTTP client for the Zoho Projects REST API
│   │   │   ├── oauth_service.py    # Token exchange, refresh, and Zoho user info fetch
│   │   │   ├── llm_service.py      # LLM factory — returns a Bedrock or Gemini model instance
│   │   │   ├── memory_store.py     # load_memory / save_memory helpers for long-term memory
│   │   │   └── crypto.py           # Fernet encryption / decryption for OAuth tokens at rest
│   │   │
│   │   ├── tools/
│   │   │   ├── read_tools.py       # LangChain tools: list_projects, list_tasks, get_task_details, list_project_members, get_task_utilisation
│   │   │   └── write_tools.py      # LangChain tools: create_task, update_task, delete_task (with assignee resolution)
│   │   │
│   │   ├── config.py               # Pydantic Settings — loads and validates all environment variables
│   │   ├── database.py             # Async SQLAlchemy engine, session factory, and get_db dependency
│   │   ├── dependencies.py         # FastAPI dependency: get_current_user from session cookie
│   │   ├── logging_config.py       # Structured logging configuration
│   │   └── main.py                 # FastAPI application entry point — registers routers and middleware
│   │
│   ├── alembic/
│   │   ├── versions/
│   │   │   ├── 20260613_190053_initial_schema.py     # Creates users, oauth_tokens, sessions, long_term_memory
│   │   │   ├── 20260614_000001_add_chat_threads.py   # Adds chat_threads and chat_messages tables
│   │   │   └── 20260614_000002_add_memory_fields.py  # Adds recent_projects and frequent_assignees columns
│   │   └── env.py                  # Alembic migration environment and async engine configuration
│   │
│   ├── tests/
│   │   ├── test_auth.py            # OAuth login flow and session handling
│   │   ├── test_chat_endpoint.py   # POST /chat endpoint integration tests
│   │   ├── test_hil.py             # Human-in-the-Loop confirm and cancel flows
│   │   ├── test_llm_service.py     # LLM provider factory and model selection
│   │   ├── test_router.py          # Intent classification: read / write / clarify
│   │   ├── test_tools.py           # LangChain read and write tool execution
│   │   └── test_zoho_client.py     # ZohoClient HTTP calls and error handling
│   │
│   ├── pyproject.toml              # Project metadata, pinned dependencies, pytest configuration
│   └── .env.example                # Documented template for all required environment variables
│
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx            # Root page — redirects to /chat or /login based on auth state
│       │   ├── layout.tsx          # Global HTML layout and font configuration
│       │   ├── globals.css         # Global CSS reset and base styles
│       │   ├── chat/
│       │   │   └── page.tsx        # Chat UI — thread sidebar, message list, input bar, HIL cards
│       │   └── login/
│       │       └── page.tsx        # Login page with "Sign in with Zoho" button
│       └── lib/
│           ├── api.ts              # Typed fetch wrappers for all backend API endpoints
│           └── types.ts            # TypeScript interfaces: Message, Thread, ChatResponse, PendingAction
│
└── README.md
```

---

## Interview Discussion Topics

This project demonstrates the following engineering concepts, which are commonly explored in technical interviews:

**System Design**
- Multi-agent architecture with a stateful, interruptible LangGraph execution graph
- Intent-based routing separating read and write concerns into distinct agents
- Stateful resumption using LangGraph checkpointing and HTTP-level request correlation

**Backend Engineering**
- Async Python with FastAPI and SQLAlchemy 2.0 for non-blocking I/O
- OAuth 2.0 Authorization Code flow with automatic token refresh
- Fernet symmetric encryption for secrets stored in a relational database
- Pydantic v2 for schema validation and typed settings management

**Data Modelling**
- Relational schema design with cascading deletes and referential integrity
- JSONB columns for flexible, schema-less memory structures alongside structured relational data
- Alembic migration versioning for reproducible, auditable schema evolution

**AI / LLM Engineering**
- Prompt engineering for deterministic intent classification (router node)
- ReAct agent pattern for tool-augmented LLM reasoning (query agent)
- Human-in-the-Loop design pattern for safe AI-driven write operations
- Two-tier memory architecture: thread-scoped short-term + persistent long-term

**Security**
- HTTP-only, SameSite cookies for session management
- Token encryption at rest — never stored or logged in plaintext
- Scoped OAuth permissions — principle of least privilege
- Capability gating — action agent rejects any operation not in the supported write set

**Frontend**
- Next.js App Router with server-side redirect for unauthenticated users
- Stateful thread sidebar with optimistic UI updates
- TypeScript-typed API client with centralised error handling

---

## Future Improvements

- Docker Compose setup for simplified local development
- Redis caching for improved performance and session management
- Support for additional Zoho operations (milestones, sprints, project creation, issue tracking)
- Markdown rendering and streaming responses in the chat UI
- Vector-based memory for semantic retrieval and long-term context
- LangSmith integration for agent tracing and observability
- Role-Based Access Control (RBAC) for team and organization use cases
- CI/CD pipeline for automated testing and deployment
- Production deployment guide with HTTPS, monitoring, and backup strategies