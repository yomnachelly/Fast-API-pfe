# 🤖 Smart Book Hub — AI Chatbot Service

A **FastAPI**-powered AI microservice for **Smart Book Hub**, a French online bookstore. It acts as an intelligent backend layer that classifies user intent, routes queries to the appropriate handler (SQL analytics, document search, or OpenAI), and returns contextual responses — all secured with JWT authentication shared with the main **Laravel** application.

---

## 🏗️ Architecture Overview

```
Laravel App (port 8000)
       │
       │  HTTP + Bearer JWT
       ▼
FastAPI AI Service (port 8001)
       │
       ├── Intent Detection
       │     ├── Keyword matching (fast, free)
       │     └── LLM fallback (OpenAI — for ambiguous queries)
       │
       ├── stats  ──► SQL queries on MySQL (sales, rankings, analytics)
       ├── report ──► ChromaDB vector search (documents, catalogues)
       └── chat   ──► OpenAI GPT (general bookstore assistant)
```

The service authenticates users against the **same MySQL database** as Laravel, issues its own short-lived JWTs, and uses OpenAI both for general chat and as an intent classification fallback.

---

## 📁 Project Structure

```
ai-service/
├── main.py              # FastAPI app — routes, auth, intent detection, AI handlers
├── intent_config.json   # Keyword lists for intent classification (French + English)
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (create from template below)
└── README.md
```

### Key Components in `main.py`

| Component | Description |
|-----------|-------------|
| `/auth/token` | Validates Laravel user credentials via bcrypt, issues JWT |
| `detect_intent()` | Classifies prompts into `stats`, `report`, or `chat` |
| `/ask` | Main chat endpoint — routes to the correct handler based on intent |
| `/admin/stats` | Admin-only endpoint (role-based access control) |
| `intent_config.json` | Editable keyword lists — extend without touching Python code |

---

## ⚙️ Prerequisites

| Tool | Minimum Version | Notes |
|------|----------------|-------|
| Python | 3.8+ | |
| pip | Latest | |
| MySQL | 5.7+ | Shared with Laravel (Laragon / XAMPP) |
| OpenAI API key | — | [Get one here](https://platform.openai.com/api-keys) |

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/yomnachelly/Fast-API-pfe.git
cd Fast-API-pfe
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file at the project root:

```env
# OpenAI
OPENAI_API_KEY=sk-...your-key-here...
OPENAI_MODEL=gpt-4o-mini

# JWT signing secret — use a long random string in production
SECRET_KEY=your-very-long-random-jwt-secret

# MySQL — same database as your Laravel app
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USERNAME=root
DB_PASSWORD=
DB_DATABASE=bookhub2
```

> ⚠️ Never commit `.env` to version control. Add it to `.gitignore`.

---

## ▶️ Running the Service

### Start the FastAPI AI service

```bash
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
"C:\Users\HP\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

The API will be live at **http://127.0.0.1:8001**  
Interactive docs available at **http://127.0.0.1:8001/docs**

### Verify everything is working

```bash
curl http://127.0.0.1:8001/health
```

Expected response:

```json
{"api": "ok", "database": "ok", "openai": "ok"}
```

---

## 🌐 Running the Full Stack (Laravel + FastAPI)

### Additional prerequisites for Laravel

- PHP 8.1+, Composer
- Node.js & npm

### Laravel setup

```bash
composer install
npm install
cp .env.example .env
php artisan key:generate
php artisan migrate
```

### Start all services (3 terminals)

| Terminal | Command | URL |
|----------|---------|-----|
| 1 — FastAPI | `uvicorn main:app --host 127.0.0.1 --port 8001 --reload` | http://127.0.0.1:8001 |
| 2 — Laravel | `php artisan serve` | http://127.0.0.1:8000 |
| 3 — Vite (assets) | `npm run dev` | — |

> ⚠️ **Start FastAPI first.** Laravel requests a token from the AI service at login time — if FastAPI isn't running, login will fail.

---

## 📡 API Reference

### `GET /`
Health ping.
```json
{"message": "AI service is running!"}
```

---

### `GET /health`
Checks database connectivity and OpenAI key availability.
```json
{"api": "ok", "database": "ok", "openai": "ok"}
```

---

### `POST /auth/token`
Authenticates a user from the Laravel `users` table and returns a JWT.

**Request:**
```json
{"email": "user@example.com", "password": "yourpassword"}
```

**Response:**
```json
{"access_token": "eyJ...", "token_type": "bearer", "role": "client"}
```

> Roles: `client`, `employe`, `admin`

---

### `POST /ask` 🔒 *(requires JWT)*
Sends a user question through the intent detection pipeline and returns an AI-generated response.

**Headers:**
```
Authorization: Bearer <access_token>
```

**Request:**
```json
{"prompt": "Quels livres recommandez-vous pour débuter en Python ?"}
```

**Response:**
```json
{
  "answer": "Je vous recommande...",
  "intent": "chat",
  "asked_by": "user@example.com",
  "role": "client"
}
```

The `intent` field reveals which handler processed the request: `chat`, `stats`, or `report`.

---

### `GET /admin/stats` 🔒 *(admin role only)*
Reserved for administrators. Returns admin-level data.

---

## 🧠 Intent Detection

Each incoming prompt is classified before routing:

```
User prompt
    │
    ▼
Keyword matching against intent_config.json
    │
    ├── Match found → route immediately (fast, no API cost)
    │
    └── No match → LLM classification via OpenAI (fallback)
                       │
                       └── Returns: stats | report | chat
```

**Extending keywords:** Edit `intent_config.json` directly — no Python changes needed.

```json
{
  "stats":  ["ventes", "chiffre", "revenue", "best-selling", ...],
  "report": ["rapport", "document", "catalogue", "find report", ...]
}
```

The normalizer strips French accents before matching, so `"ventes"` matches `"Ventes"`, `"vèntès"`, etc.

---

## 🔐 Authentication & Security

- Users are verified against the Laravel `users` table using **bcrypt** password hashing
- The service handles both `$2b$` (standard) and `$2y$` (PHP-style) bcrypt prefixes
- JWTs are signed with `HS256` and expire after **60 minutes**
- Role-based access control enforced on every protected endpoint (`client`, `employe`, `admin`)

---

## 🛠️ Troubleshooting

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| `Session expirée` | Token expired or missing | Log out and log back in |
| `missing OPENAI_API_KEY` | Key not set in `.env` | Add `OPENAI_API_KEY` to your `.env` file |
| `Database connection failed` | MySQL not running | Start Laragon or XAMPP |
| `Port 8001 already in use` | Another process on that port | Use `--port 8002` |
| `OpenAI error` | Invalid key or quota exceeded | Check key at [platform.openai.com](https://platform.openai.com) |
| `403 Access denied` | Wrong role for endpoint | Use an account with the required role |

---

## 🗺️ Roadmap

The following handlers are detected but not yet implemented:

- [ ] **`stats` handler** — SQL queries against the `bookhub2` database for sales analytics and rankings
- [ ] **`report` handler** — ChromaDB vector search over stored book reports and catalogues
- [ ] **Conversation memory** — maintain multi-turn context per user session
- [ ] **Streaming responses** — stream OpenAI tokens for a faster perceived response time

---

## ✅ Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI (Python) |
| AI provider | OpenAI (`gpt-4o-mini` by default) |
| Database | MySQL via PyMySQL (shared with Laravel) |
| Auth | JWT (PyJWT) + bcrypt |
| Intent classification | Keyword matching + OpenAI fallback |
| Future: vector search | ChromaDB (planned) |
