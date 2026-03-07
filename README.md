# 🤖 Smart Book Hub — AI Chatbot Service

Service de chatbot IA pour **Smart Book Hub**, une librairie en ligne. Construit avec **FastAPI** (Python) et intégré à une application **Laravel**, il utilise l'API **OpenAI** pour répondre aux questions des utilisateurs en français.

---

## 📁 Structure du projet

```
ai-service/
├── main.py              # Serveur FastAPI principal
├── requirements.txt     # Dépendances Python
├── .env                 # Variables d'environnement (à créer)
├── .gitignore
└── README.md
```

---

## ⚙️ Prérequis

| Outil | Version minimale |
|-------|-----------------|
| Python | 3.8+ |
| pip | dernière version |
| MySQL | 5.7+ (via Laragon / XAMPP) |
| Clé API OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) |

---

## 🚀 Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/yomnachelly/Fast-API-pfe.git
cd Fast-API-pfe
```

### 2. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

Ou manuellement :

```bash
pip install fastapi uvicorn pydantic pymysql bcrypt PyJWT requests python-dotenv openai
```

### 3. Configurer les variables d'environnement

Créez un fichier `.env` à la racine du projet :

```env
# OpenAI
OPENAI_API_KEY=sk-...votre-clé-ici...
OPENAI_MODEL=gpt-4o-mini

# JWT
SECRET_KEY=votre-secret-jwt-très-long

# Base de données Laravel (même DB)
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USERNAME=root
DB_PASSWORD=
DB_DATABASE=bookhub2
```

---

## ▶️ Lancement

### Service FastAPI (IA)

```bash
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

Le service sera accessible à : **http://127.0.0.1:8001**

### Vérifier que tout fonctionne

```bash
curl http://127.0.0.1:8001/health
```

Réponse attendue :

```json
{"api": "ok", "database": "ok", "openai": "ok"}
```

---

## 🌐 Lancer le projet Laravel (SmartBookHub)

### Prérequis supplémentaires

- PHP 8.1+
- Composer
- Node.js & npm

### Installation Laravel

```bash
composer install
npm install
cp .env.example .env
php artisan key:generate
php artisan migrate
```

### Lancement (3 terminaux séparés)

| Terminal | Commande | URL |
|----------|----------|-----|
| 1 — Laravel | `php artisan serve` | http://127.0.0.1:8000 |
| 2 — Vite (assets) | `npm run dev` | — |
| 3 — FastAPI (IA) | `uvicorn main:app --host 127.0.0.1 --port 8001 --reload` | http://127.0.0.1:8001 |

> ⚠️ **Ordre recommandé :** démarrez toujours FastAPI **avant** de vous connecter à Laravel, pour que le token IA soit généré correctement à la connexion.

---

## 📡 Endpoints API

### `GET /`
Vérifie que le service tourne.
```json
{"message": "AI service is running!"}
```

### `GET /health`
Vérifie la connexion à la base de données et à OpenAI.
```json
{"api": "ok", "database": "ok", "openai": "ok"}
```

### `POST /auth/token`
Authentifie un utilisateur Laravel et retourne un JWT.
```json
// Body
{"email": "user@example.com", "password": "motdepasse"}

// Réponse
{"access_token": "eyJ...", "token_type": "bearer", "role": "client"}
```

### `POST /ask` 🔒 *(JWT requis)*
Envoie une question à OpenAI et retourne la réponse.
```json
// Body
{"prompt": "Quels livres recommandez-vous pour débuter en Python ?"}

// Réponse
{"answer": "Je vous recommande...", "asked_by": "user@example.com", "role": "client"}
```

### `GET /admin/stats` 🔒 *(admin uniquement)*
Endpoint réservé aux administrateurs.

---

## 🔐 Authentification

Le service utilise des **JWT** (JSON Web Tokens) :

1. À la connexion Laravel, un token est automatiquement généré via `/auth/token` et stocké en session
2. Chaque requête vers `/ask` envoie ce token dans le header `Authorization: Bearer <token>`
3. Le token expire après **60 minutes**

---

## 🛠️ Dépannage

| Erreur | Cause probable | Solution |
|--------|---------------|----------|
| `Session expirée` | Token absent ou expiré | Se déconnecter et se reconnecter |
| `missing OPENAI_API_KEY` | Clé non configurée | Vérifier le fichier `.env` |
| `Database connection failed` | MySQL non démarré | Démarrer Laragon / XAMPP |
| `Port 8001 déjà utilisé` | Processus en conflit | Changer le port : `--port 8002` |
| `Erreur OpenAI` | Quota dépassé ou clé invalide | Vérifier la clé sur platform.openai.com |

---

## ✅ Récapitulatif

- ✅ FastAPI sur le **port 8001**
- ✅ Authentification JWT liée à la base de données Laravel
- ✅ Intégration OpenAI (`gpt-4o-mini` par défaut)
- ✅ Réponses en français, contextualisées pour Smart Book Hub
- ✅ Toutes les URLs configurables via `.env`