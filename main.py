from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json
from decimal import Decimal

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
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from langchain_core.documents import Document
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _safe_float(value, default=0):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _safe_int(value, default=0):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

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
# ===================== ChromaDB collections(reports, books) =====================
embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key=OPENAI_API_KEY
)

CHROMA_PERSIST_DIR = "./chroma_db"

reports_vectorstore = None
books_vectorstore = None

def init_chroma():
    """Création des collections ChromaDB """
    global reports_vectorstore, books_vectorstore
    
    reports_vectorstore = Chroma(
        collection_name="reports",
        embedding_function=embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
    )
    books_vectorstore = Chroma(
        collection_name="books",
        embedding_function=embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
    )
    logger.info("Collections ChromaDB créées")

def load_books_to_chroma():
    """Charge les livres de la DB dans ChromaDB"""
    global books_vectorstore
    if books_vectorstore is None:
        init_chroma()
    
    # Évite de recharger plusieurs fois
    if len(books_vectorstore.get()["ids"]) > 0:
        return
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id_livre, titre, auteur, prix FROM livres LIMIT 100")
            books = cursor.fetchall()
            
            docs = []
            for b in books:
                text = f"Livre : {b['titre']}\nAuteur : {b.get('auteur', 'Inconnu')}\nPrix : {b.get('prix', 0)} TND"
                docs.append(Document(page_content=text, metadata={"book_id": b["id_livre"], "titre": b["titre"]}))
            
            if docs:
                books_vectorstore.add_documents(docs)
                logger.info(f"{len(docs)} livres ajoutés dans ChromaDB")
    finally:
        conn.close()

def add_report(text: str, title: str, metadata: dict = None):
    """Ajoute un rapport dans ChromaDB """
    global reports_vectorstore
    if reports_vectorstore is None:
        init_chroma()
    meta = metadata or {}
    meta["title"] = title
    doc = Document(page_content=text, metadata=meta)
    reports_vectorstore.add_documents([doc])
    logger.info(f"Rapport '{title}' ajouté")

def semantic_search_reports(query: str, k: int = 4):
    """Recherche sémantique dans les rapports """
    global reports_vectorstore
    if reports_vectorstore is None:
        init_chroma()
    return reports_vectorstore.similarity_search(query, k=k)

def get_report_context(query: str, k: int = 4):
    """Retourne les résultats ChromaDB comme contexte pour le LLM """
    docs = semantic_search_reports(query, k)
    if not docs:
        return "Aucun rapport trouvé dans la base."
    
    parts = []
    for i, doc in enumerate(docs, 1):
        title = doc.metadata.get("title", "Sans titre")
        parts.append(f"**Rapport {i} — {title}**\n{doc.page_content}")
    return "\n\n" + "="*50 + "\n\n".join(parts)

# Chain pour les rapports (intent "report")
_report_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "Tu es un assistant spécialisé dans les rapports internes de Smart Book Hub. "
        "Réponds toujours en français, de façon professionnelle et précise. "
        "Utilise UNIQUEMENT les rapports fournis. Si l'info n'est pas là, dis-le clairement."
    ),
    (
        "human",
        "Rapports trouvés :\n{report_context}\n\nQuestion : {question}"
    ),
])
_report_chain = _report_prompt | _llm_chat | StrOutputParser()
# ===================== FIN CHROMADB =====================
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
            return float(result["total_sales"] or 0)
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
            return int(result["books_sold"] or 0)
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
            return int(result["total_orders"] or 0)
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

        try:
            total_sales = _safe_float(get_total_sales())
        except Exception as e:
            logger.error(f"[stats_admin] get_total_sales failed: {e}")
            total_sales = 0.0

        try:
            total_orders = _safe_int(get_total_orders())
        except Exception as e:
            logger.error(f"[stats_admin] get_total_orders failed: {e}")
            total_orders = 0

        try:
            books_sold = _safe_int(get_books_sold())
        except Exception as e:
            logger.error(f"[stats_admin] get_books_sold failed: {e}")
            books_sold = 0

        try:
            best_books = get_best_selling_books() or []
        except Exception as e:
            logger.error(f"[stats_admin] get_best_selling_books failed: {e}")
            best_books = []

        try:
            best_author = get_best_author()
        except Exception as e:
            logger.error(f"[stats_admin] get_best_author failed: {e}")
            best_author = None

        try:
            most_expensive = get_most_expensive_book()
        except Exception as e:
            logger.error(f"[stats_admin] get_most_expensive_book failed: {e}")
            most_expensive = None

        try:
            sales_by_cat = get_sales_by_category() or []
        except Exception as e:
            logger.error(f"[stats_admin] get_sales_by_category failed: {e}")
            sales_by_cat = []

        try:
            orders_per_month = get_orders_per_month() or []
        except Exception as e:
            logger.error(f"[stats_admin] get_orders_per_month failed: {e}")
            orders_per_month = []

        try:
            top_clients = get_top_clients() or []
        except Exception as e:
            logger.error(f"[stats_admin] get_top_clients failed: {e}")
            top_clients = []

        best_books_txt = "\n".join(
            "  {}. {} - {} exemplaire(s)".format(i + 1, b["titre"], _safe_int(b["total_sold"]))
            for i, b in enumerate(best_books)
        ) if best_books else "  Aucune donnee"

        sales_cat_txt = "\n".join(
            "  - {} : {:.2f} TND".format(c["nom_categ"], _safe_float(c["revenue"]))
            for c in sales_by_cat
        ) if sales_by_cat else "  Aucune donnee"

        orders_month_txt = "\n".join(
            "  - {} : {} commande(s)".format(
                month_names.get(_safe_int(m["month"]), str(m["month"])), _safe_int(m["total_orders"])
            )
            for m in orders_per_month
        ) if orders_per_month else "  Aucune donnee"

        top_clients_txt = "\n".join(
            "  - {} : {} commande(s)".format(c["name"], _safe_int(c["total_orders"]))
            for c in top_clients
        ) if top_clients else "  Aucune donnee"

        best_author_txt = (
            "{} ({} exemplaires)".format(best_author["auteur"], _safe_int(best_author["total_sold"]))
            if best_author else "N/A"
        )
        most_expensive_txt = (
            "{} - {} TND".format(most_expensive["titre"], _safe_float(most_expensive["prix"]))
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

       # REPORT INTENT (employe + admin) — CHROMADB ACTIVÉ
    elif intent == "report":
        report_context = get_report_context(question.prompt)
        
        try:
            answer = _report_chain.invoke({
                "report_context": report_context,
                "question":      question.prompt,
            })
            logger.info(f"[ask] report answer: {len(answer)} chars")
        except Exception as e:
            logger.error(f"[ask] report LangChain error: {e}")
            answer = "Voici les rapports trouvés :\n\n" + report_context

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
# ===================== INITIALISATION CHROMADB AU DÉMARRAGE =====================
init_chroma()

# Ajout de 2 rapports exemples (pour tester tout de suite)
if len(reports_vectorstore.get()["ids"]) == 0:
    sample_docs = [
        Document(
            page_content="Rapport annuel 2025 : Le chiffre d'affaires a atteint 125 000 TND (+18% vs 2024). Les catégories Fiction et Romance représentent 62% des ventes.",
            metadata={"title": "Rapport Annuel 2025", "date": "2025"}
        ),
        Document(
            page_content="Rapport Q1 2026 : Meilleures ventes : 'Le Petit Prince' (245 ex) et 'Harry Potter'. Hausse de 30% sur les livres pour enfants.",
            metadata={"title": "Rapport Trimestriel Q1 2026", "date": "2026"}
        )
    ]
    reports_vectorstore.add_documents(sample_docs)
    logger.info("✅ 2 rapports exemples ajoutés")

load_books_to_chroma()

logger.info("🚀 ChromaDB prêt (rapports + livres)")