# FastAPI Chatbot Service

Service AI chatbot utilisant FastAPI et Ollama avec le modèle llama3.

## Prérequis

- Python 3.8+
- [Ollama](https://ollama.ai/) installé sur votre machine
- Le modèle llama3 téléchargé

## Installation

1. **Cloner le dépôt**
```bash
git clone https://github.com/yomnachelly/Fast-API-pfe.git
cd Fast-API-pfe
Installer les dépendances Python

bash
pip install fastapi uvicorn requests pydantic
Lancer Ollama
Démarrer le serveur Ollama
bash
ollama serve
Le serveur sera accessible à l'adresse : http://127.0.0.1:11434/

Vérifier qu'Ollama fonctionne
bash
# Tester la connexion (dans un autre terminal)
curl http://127.0.0.1:11434/api/generate
Si le modèle llama3 n'est pas installé
bash
ollama pull llama3:latest
Lancer le service FastAPI
Démarrer le serveur FastAPI
bash
# Dans le dossier du projet (C:/ai-service)
uvicorn main:app --reload --port 8001
Le service sera disponible à : http://127.0.0.1:8001

Vérifier que le service tourne
Ouvrez http://127.0.0.1:8001 dans votre navigateur - vous devriez voir :

json
{"message": "AI service is running!"}
Utilisation de l'API
Endpoint POST /ask
Envoyez une question au chatbot :

bash
curl -X POST "http://127.0.0.1:8001/ask" \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Quelle est la capitale de la France ?"}'
Réponse attendue :

json
{"answer": "La capitale de la France est Paris."}
Endpoint GET /
Vérifier que le service fonctionne :

bash
curl http://127.0.0.1:8001/
Résumé des commandes importantes
Commande	Description
ollama serve	Démarre le serveur Ollama (http://127.0.0.1:11434)
ollama pull llama3:latest	Télécharge le modèle llama3
uvicorn main:app --reload --port 8001	Lance le serveur FastAPI sur le port 8001
curl http://127.0.0.1:11434/	Teste la connexion à Ollama
curl http://127.0.0.1:8001/	Teste la connexion à FastAPI
Ordre de lancement
D'abord : ollama serve (dans un terminal)

Ensuite : uvicorn main:app --reload --port 8001 (dans un autre terminal)

Enfin : Faites vos requêtes à l'API sur http://127.0.0.1:8001

Structure du projet
text
ai-service/
├── main.py          # Code principal FastAPI
├── README.md        # Ce fichier
└── .gitignore       # Fichiers à ignorer par Git
Dépannage
Erreur "Connection refused" pour Ollama
Vérifiez qu'Ollama est bien lancé avec ollama serve

Vérifiez que http://127.0.0.1:11434 est accessible

Erreur "Model not found"
Lancez ollama pull llama3:latest pour télécharger le modèle

Port 8001 déjà utilisé
Changez le port : uvicorn main:app --reload --port 8002

text

Les modifications principales :
- ✅ Toutes les URLs FastAPI sont maintenant sur le **port 8001**
- ✅ La commande de lancement inclut `--port 8001`
- ✅ Le tableau récapitulatif est mis à jour
- ✅ L'ordre de lancement mentionne le bon port

Vous pouvez maintenant copier ce contenu dans votre README.md !
