from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json

# jwt tokens auth import
import jwt

import datetime
import os
import re
import pymysql
import bcrypt
import logging
from typing import Optional
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logging.getLogger("langchain").setLevel(logging.WARNING)
logging.getLogger("langchain_core").setLevel(logging.WARNING)
logging.getLogger("langchain_openai").setLevel(logging.WARNING)

app = FastAPI(title="AI Chatbot Service")

SECRET_KEY          = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM           = "HS256"
TOKEN_EXPIRE_MINUTES = 60

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# LangChain LLM instances
# One fast+cheap model for intent classification
_llm_intent = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=0,
    max_tokens=10,
    api_key=OPENAI_API_KEY,
)

# One model for generating natural language
_llm_chat = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=0.7,
    max_tokens=1000,
    api_key=OPENAI_API_KEY,
)

# One model for stats
_llm_stats = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=0.3,
    max_tokens=600,
    api_key=OPENAI_API_KEY,
)

# LangChain chains

# Intent classification
_intent_prompt = PromptTemplate.from_template(
    "You are an intent classifier for a French online bookstore chatbot.\n"
    "Classify the following user message into exactly one of these intents:\n"
    "  - stats_admin  : the user asks about sensitive business data such as revenue, total sales,\n"
    "                   total orders, profit, sales reports, client rankings, or monthly figures.\n"
    "  - stats_public : the user asks about best-selling books, popular books, trending titles,\n"
    "                   or book recommendations based on popularity. This is NOT sensitive.\n"
    "  - report       : the user is looking for a document, report, book description,\n"
    "                   catalogue entry, or wants to search stored files.\n"
    "  - chat         : general conversation, product questions, or anything else.\n\n"
    "Reply with ONLY one word (stats_admin, stats_public, report, or chat). "
    "No punctuation, no explanation.\n\n"
    "User message: {prompt}"
)
_intent_chain = _intent_prompt | _llm_intent | StrOutputParser()

# Stats answer chain
_stats_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "Tu es un assistant analytique pour Smart Book Hub, une librairie en ligne. "
        "On te fournit des donnees de vente reelles. "
        "Reponds a la question de l'utilisateur de facon concise et naturelle en francais, "
        "en utilisant uniquement les donnees pertinentes a sa question. "
        "N'invente aucun chiffre. Si la donnee n'est pas disponible, dis-le clairement."
    ),
    (
        "human",
        "Donnees disponibles :\n{stats_context}\n\nQuestion : {question}"
    ),
])
_stats_chain = _stats_prompt | _llm_stats | StrOutputParser()

# Public stats answer chain (best-sellers only)
_stats_public_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "Tu es un assistant pour Smart Book Hub, une librairie en ligne. "
        "On te fournit uniquement la liste des livres les plus vendus. "
        "Reponds a la question de l'utilisateur de facon conviviale en francais. "
        "Ne mentionne jamais de chiffres de vente, revenus ou donnees financieres."
    ),
    (
        "human",
        "Livres les plus populaires :\n{books_context}\n\nQuestion : {question}"
    ),
])
_stats_public_chain = _stats_public_prompt | _llm_chat | StrOutputParser()

# General chat
_chat_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "Tu es un assistant virtuel pour Smart Book Hub, une librairie en ligne. "
        "Tu aides les clients a trouver des livres, repondre a leurs questions sur les commandes, "
        "les categories, et les services de la librairie. Reponds toujours en francais."
    ),
    ("human", "{question}"),
])
_chat_chain = _chat_prompt | _llm_chat | StrOutputParser()

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

# DB QUERY FUNCTIONS

def get_total_sales():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT SUM(total) AS total_sales
                FROM commandes
                WHERE statut = 'validee'
                AND YEAR(created_at) = YEAR(NOW())
            """)
            result = cursor.fetchone()
            return result["total_sales"] or 0
    finally:
        conn.close()

def get_books_sold():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT SUM(cl.quantite) AS books_sold
                FROM commande_livre cl
                JOIN commandes c ON cl.commande_id = c.id
                WHERE c.statut = 'validee'
                AND YEAR(c.created_at) = YEAR(NOW())
            """)
            result = cursor.fetchone()
            return result["books_sold"] or 0
    finally:
        conn.close()

def get_best_selling_books():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT l.titre, SUM(cl.quantite) AS total_sold
                FROM commande_livre cl
                JOIN livres l ON cl.livre_id = l.id_livre
                JOIN commandes c ON cl.commande_id = c.id
                WHERE c.statut = 'validee'
                AND YEAR(c.created_at) = YEAR(NOW())
                GROUP BY l.id_livre, l.titre
                ORDER BY total_sold DESC
                LIMIT 5
            """)
            return cursor.fetchall()
    finally:
        conn.close()

def get_total_orders():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) AS total_orders
                FROM commandes
                WHERE statut = 'validee'
            """)
            result = cursor.fetchone()
            return result["total_orders"] or 0
    finally:
        conn.close()

def get_best_author():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT l.auteur, SUM(cl.quantite) AS total_sold
                FROM commande_livre cl
                JOIN livres l ON cl.livre_id = l.id_livre
                JOIN commandes c ON cl.commande_id = c.id
                WHERE c.statut = 'validee'
                AND YEAR(c.created_at) = YEAR(NOW())
                GROUP BY l.auteur
                ORDER BY total_sold DESC
                LIMIT 1
            """)
            return cursor.fetchone()
    finally:
        conn.close()

def get_most_expensive_book():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT titre, prix
                FROM livres
                ORDER BY prix DESC
                LIMIT 1
            """)
            return cursor.fetchone()
    finally:
        conn.close()

def get_sales_by_category():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT cat.nom_categ, SUM(cl.quantite * l.prix) AS revenue
                FROM commande_livre cl
                JOIN livres l ON cl.livre_id = l.id_livre
                JOIN categories cat ON l.categorie_id = cat.id_categ
                JOIN commandes c ON cl.commande_id = c.id
                WHERE c.statut = 'validee'
                AND YEAR(c.created_at) = YEAR(NOW())
                GROUP BY cat.id_categ, cat.nom_categ
                ORDER BY revenue DESC
            """)
            return cursor.fetchall()
    finally:
        conn.close()

def get_orders_per_month():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT MONTH(created_at) AS month, COUNT(*) AS total_orders
                FROM commandes
                WHERE statut = 'validee'
                AND YEAR(created_at) = YEAR(NOW())
                GROUP BY MONTH(created_at)
                ORDER BY month
            """)
            return cursor.fetchall()
    finally:
        conn.close()

def get_top_clients():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT u.name, COUNT(c.id) AS total_orders
                FROM commandes c
                JOIN users u ON c.user_id = u.id
                WHERE c.statut = 'validee'
                GROUP BY u.id, u.name
                ORDER BY total_orders DESC
                LIMIT 5
            """)
            return cursor.fetchall()
    finally:
        conn.close()

# AUTH

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str

class Question(BaseModel):
    prompt: str

security = HTTPBearer()

STAFF_ONLY_INTENTS = {"stats_admin", "report"}

def create_token(email: str, role: str) -> str:
    payload = {
        "sub":  email,
        "role": role,
        "exp":  datetime.datetime.utcnow() + datetime.timedelta(minutes=TOKEN_EXPIRE_MINUTES),
        "iat":  datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_role(allowed_roles: list):
    def checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(status_code=403, detail="Access forbidden")
        return current_user
    return checker

def detect_intent(prompt: str) -> str:
    try:
        result = _intent_chain.invoke({"prompt": prompt})
        intent = result.strip().lower()
        valid_intents = {"stats_admin", "stats_public", "report", "chat"}
        return intent if intent in valid_intents else "chat"
    except Exception as e:
        logger.error(f"Intent detection failed: {e}")
        return "chat"

# GLOBAL EXCEPTION HANDLER

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.error(f"Unhandled error on {request.url}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "{}: {}".format(type(exc).__name__, str(exc))}
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
    langchain_status = "ok" if OPENAI_API_KEY else "missing OPENAI_API_KEY"
    return {
        "api": "ok",
        "database": db_status,
        "openai": openai_status,
        "langchain": langchain_status,
    }

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

    user_role = current_user.get("role")
    intent    = detect_intent(question.prompt)
    logger.info(f"[ask] user='{current_user['sub']}' role={user_role} intent={intent}")

    # ACCESS CONTROL
    if user_role == "client" and intent in STAFF_ONLY_INTENTS:
        logger.warning(
            f"[ask] Access denied: client '{current_user['sub']}' "
            f"attempted restricted intent '{intent}'"
        )
        return {
            "answer": (
                "Je suis désolé, je ne peux pas vous fournir ces informations. "
                "Les données administratives (chiffre d'affaires, commandes, rapports, etc.) "
                "sont réservées au personnel interne. "
                "Je peux vous aider à trouver des livres, consulter vos commandes, "
                "ou répondre à toute autre question sur notre catalogue. 😊"
            ),
            "intent": intent,
            "asked_by": current_user["sub"],
            "role": user_role,
        }

    # STATS INTENT (employe + admin)
    if intent == "stats_admin":

        month_names = {
            1: "Janvier",  2: "Fevrier",   3: "Mars",      4: "Avril",
            5: "Mai",      6: "Juin",      7: "Juillet",   8: "Aout",
            9: "Septembre",10: "Octobre",  11: "Novembre", 12: "Decembre"
        }

        total_sales      = get_total_sales()
        total_orders     = get_total_orders()
        books_sold       = get_books_sold()
        best_books       = get_best_selling_books()
        best_author      = get_best_author()
        most_expensive   = get_most_expensive_book()
        sales_by_cat     = get_sales_by_category()
        orders_per_month = get_orders_per_month()
        top_clients      = get_top_clients()

        best_books_txt = "\n".join(
            "  {}. {} - {} exemplaire(s)".format(i + 1, b["titre"], b["total_sold"])
            for i, b in enumerate(best_books)
        ) if best_books else "  Aucune donnee"

        sales_cat_txt = "\n".join(
            "  - {} : {:.2f} TND".format(c["nom_categ"], c["revenue"])
            for c in sales_by_cat
        ) if sales_by_cat else "  Aucune donnee"

        orders_month_txt = "\n".join(
            "  - {} : {} commande(s)".format(
                month_names.get(m["month"], str(m["month"])), m["total_orders"]
            )
            for m in orders_per_month
        ) if orders_per_month else "  Aucune donnee"

        top_clients_txt = "\n".join(
            "  - {} : {} commande(s)".format(c["name"], c["total_orders"])
            for c in top_clients
        ) if top_clients else "  Aucune donnee"

        best_author_txt = (
            "{} ({} exemplaires)".format(best_author["auteur"], best_author["total_sold"])
            if best_author else "N/A"
        )
        most_expensive_txt = (
            "{} - {} TND".format(most_expensive["titre"], most_expensive["prix"])
            if most_expensive else "N/A"
        )

        stats_context = (
            "Donnees de vente actuelles de Smart Book Hub :\n\n"
            "- Chiffre d'affaires total (annee en cours) : {:.2f} TND\n"
            "- Nombre de commandes validees (tous temps) : {}\n"
            "- Livres vendus (annee en cours) : {}\n\n"
            "Livres les plus vendus :\n{}\n\n"
            "Auteur le plus vendu : {}\n\n"
            "Livre le plus cher : {}\n\n"
            "Revenus par categorie :\n{}\n\n"
            "Commandes validees par mois :\n{}\n\n"
            "Meilleurs clients :\n{}"
        ).format(
            total_sales, total_orders, books_sold,
            best_books_txt, best_author_txt, most_expensive_txt,
            sales_cat_txt, orders_month_txt, top_clients_txt,
        )

        try:
            answer = _stats_chain.invoke({
                "stats_context": stats_context,
                "question":      question.prompt,
            })
            logger.info(f"[ask] stats_admin answer: {len(answer)} chars")
        except Exception as e:
            logger.error(f"[ask] stats_admin LangChain error: {e}")
            answer = "Statistiques Smart Book Hub\n\n" + stats_context

    # STATS PUBLIC INTENT (all roles)
    elif intent == "stats_public":
        best_books = get_best_selling_books()
        books_context = "\n".join(
            "  {}. {}".format(i + 1, b["titre"])
            for i, b in enumerate(best_books)
        ) if best_books else "  Aucun livre disponible pour le moment."

        try:
            answer = _stats_public_chain.invoke({
                "books_context": books_context,
                "question":      question.prompt,
            })
            logger.info(f"[ask] stats_public answer: {len(answer)} chars")
        except Exception as e:
            logger.error(f"[ask] stats_public LangChain error: {e}")
            answer = "Voici les livres les plus populaires :\n\n" + books_context

    # REPORT INTENT (employe + admin)
    elif intent == "report":
        answer = "[report intent detected - ChromaDB handler not yet implemented]"

    # CHAT INTENT (all roles)
    else:
        try:
            answer = _chat_chain.invoke({"question": question.prompt})
            logger.info(f"[ask] chat answer: {len(answer)} chars")
        except Exception as e:
            logger.error(f"[ask] chat LangChain error: {e}")
            return {"answer": "Erreur LangChain: " + str(e)}

    return {
        "answer":    answer,
        "intent":    intent,
        "asked_by":  current_user["sub"],
        "role":      user_role,
    }


@app.get("/admin/stats")
def admin_stats(current_user: dict = Depends(require_role(["admin"]))):
    return {
        "message":     "Admin stats endpoint",
        "accessed_by": current_user["sub"],
    }