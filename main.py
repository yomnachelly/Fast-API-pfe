from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json
import jwt
import datetime
import os
import re
import pymysql
import bcrypt
import logging
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Chatbot Service")

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# DB CONFIG
DB_CONFIG = {
    "host":        os.getenv("DB_HOST",     "127.0.0.1"),
    "port":        int(os.getenv("DB_PORT", "3306")),
    "user":        os.getenv("DB_USERNAME", "root"),
    "password":    os.getenv("DB_PASSWORD", ""),
    "database":    os.getenv("DB_DATABASE", "bookhub2"),
    "cursorclass": pymysql.cursors.DictCursor,
    "connect_timeout": 5,
}

def get_db_connection():
    try:
        return pymysql.connect(**DB_CONFIG)
    except pymysql.err.OperationalError as e:
        logger.error(f"DB connection failed: {e}")
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)}")

def get_user_from_db(email: str) -> Optional[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, email, password, role, is_active "
                "FROM users WHERE email = %s LIMIT 1",
                (email,)
            )
            return cursor.fetchone()
    except pymysql.err.ProgrammingError as e:
        logger.error(f"DB query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")
    finally:
        conn.close()

# MODELS
class LoginRequest(BaseModel):
    email: str
    password: str

class Question(BaseModel):
    prompt: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str

# JWT HELPERS
def create_token(email: str, role: str) -> str:
    payload = {
        "sub": email,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# AUTH DEPENDENCIES
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    return decode_token(credentials.credentials)

def require_role(allowed_roles: list):
    def role_checker(user: dict = Depends(get_current_user)):
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {allowed_roles}"
            )
        return user
    return role_checker

# INTENT KEYWORDS (loaded from intent_config.json)
with open("intent_config.json", "r", encoding="utf-8") as f:
    _INTENT_KEYWORDS: dict = json.load(f)

STATS_KEYWORDS  = _INTENT_KEYWORDS.get("stats", [])
REPORT_KEYWORDS = _INTENT_KEYWORDS.get("report", [])

# INTENT DETECTION
def _normalize(text: str) -> str:
    """Lowercase + strip accents => robust matching"""
    return (
        text.lower().strip()
        .replace("é", "e").replace("è", "e").replace("ê", "e")
        .replace("à", "a").replace("â", "a")
        .replace("ù", "u").replace("û", "u")
        .replace("î", "i").replace("ï", "i")
        .replace("ô", "o").replace("ç", "c")
    )

def detect_intent(prompt: str) -> str:
    """
    Classify the user's message into one of three intents:
      - 'stats'  -> user wants sales/analytics data (-> SQL queries)
      - 'report' -> user wants to search reports/documents (-> ChromaDB)
      - 'chat'   -> general bookstore conversation (-> LLM)

    Strategy: keyword matching first (fast & free) -> then LLM fallback for ambiguous messages

    => Returns: 'chat' | 'stats' | 'report'
    """
    normalized = _normalize(prompt)

    # keyword-based detection
    for kw in STATS_KEYWORDS:
        if re.search(r'\b' + re.escape(_normalize(kw)) + r'\b', normalized):
            logger.info(f"Intent detected via keyword (stats): '{kw}'")
            return "stats"

    for kw in REPORT_KEYWORDS:
        if re.search(r'\b' + re.escape(_normalize(kw)) + r'\b', normalized):
            logger.info(f"Intent detected via keyword (report): '{kw}'")
            return "report"

    # LLM fallback for ambiguous messages
    if OPENAI_API_KEY:
        try:
            classification_prompt = (
                "You are an intent classifier for a French online bookstore chatbot.\n"
                "Classify the following user message into exactly one of these intents:\n"
                "  - 'stats'  : the user is asking about sales figures, revenues, orders, "
                "best-selling books, or any numerical/analytics data.\n"
                "  - 'report' : the user is looking for a specific document, report, "
                "book description, catalogue entry, or wants to search stored files.\n"
                "  - 'chat'   : general conversation, product questions, recommendations, "
                "or anything else.\n\n"
                "Reply with ONLY one word: stats, report, or chat.\n\n"
                f"User message: \"{prompt}\""
            )
            completion = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": classification_prompt}],
                max_tokens=5,
                temperature=0,
            )
            intent = completion.choices[0].message.content.strip().lower()
            if intent in ("stats", "report", "chat"):
                logger.info(f"Intent detected via LLM: '{intent}'")
                return intent
        except Exception as e:
            logger.warning(f"LLM intent detection failed, defaulting to 'chat': {e}")

    logger.info("Intent defaulting to: 'chat'")
    return "chat"

# GLOBAL EXCEPTION HANDLER
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.error(f"Unhandled error on {request.url}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {str(exc)}"}
    )

# ROUTES
@app.get("/")
def home():
    return {"message": "AI service is running!"}

@app.get("/health")
def health():
    try:
        conn = get_db_connection()
        conn.close()
        db_status = "ok"
    except Exception as e:
        db_status = str(e)
    openai_status = "ok" if OPENAI_API_KEY else "missing OPENAI_API_KEY"
    return {"api": "ok", "database": db_status, "openai": openai_status}

@app.post("/auth/token", response_model=TokenResponse)
def login(data: LoginRequest):
    logger.info(f"Login attempt for: {data.email}")

    user = get_user_from_db(data.email)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Account is disabled")

    password_hash = user["password"]
    if password_hash.startswith("$2y$"):
        password_hash = "$2b$" + password_hash[4:]

    try:
        password_matches = bcrypt.checkpw(
            data.password.encode("utf-8"),
            password_hash.encode("utf-8")
        )
    except Exception as e:
        logger.error(f"bcrypt error: {e}")
        raise HTTPException(status_code=500, detail=f"Password verification error: {str(e)}")

    if not password_matches:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(user["email"], user["role"])
    logger.info(f"Login successful for: {data.email} (role: {user['role']})")
    return TokenResponse(access_token=token, role=user["role"])

@app.post("/ask")
def ask_ai(
    question: Question,
    current_user: dict = Depends(require_role(["client", "employe", "admin"]))
):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    intent = detect_intent(question.prompt)
    logger.info(f"Routing '{current_user['sub']}' prompt to intent: {intent}")

    if intent == "stats":
        answer = "[stats intent detected — SQL handler not yet implemented]"

    elif intent == "report":
        answer = "[report intent detected — ChromaDB handler not yet implemented]"

    else:
        try:
            completion = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Tu es un assistant virtuel pour Smart Book Hub, une librairie en ligne. "
                            "Tu aides les clients à trouver des livres, répondre à leurs questions sur les commandes, "
                            "les catégories, et les services de la librairie. Réponds toujours en français."
                        )
                    },
                    {
                        "role": "user",
                        "content": question.prompt
                    }
                ],
                max_tokens=1000,
                temperature=0.7,
            )
            answer = completion.choices[0].message.content
            logger.info(f"OpenAI response for {current_user['sub']}: {len(answer)} chars")

        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            return {"answer": f"Erreur OpenAI: {str(e)}"}

    return {
        "answer": answer,
        "intent": intent,
        "asked_by": current_user["sub"],
        "role": current_user["role"]
    }

@app.get("/admin/stats")
def admin_stats(current_user: dict = Depends(require_role(["admin"]))):
    return {
        "message": "Admin stats endpoint",
        "accessed_by": current_user["sub"]
    }