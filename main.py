from fastapi import FastAPI
from pydantic import BaseModel
import requests
import json

app = FastAPI(title="AI Chatbot Service")

class Question(BaseModel):
    prompt: str
    role: str = "client"

@app.post("/ask")
def ask_ai(question: Question):
    try:
        response = requests.post(
            "http://127.0.0.1:11434/api/generate",
            json={
                "model": "llama3:latest",
                "prompt": question.prompt,
                "stream": False  # 🔥 Désactive le streaming pour une réponse unique
            }
        )
        
        # Vérifier si la requête a réussi
        response.raise_for_status()
        
        # Analyser la réponse JSON
        data = response.json()
        
        # Ollama renvoie la réponse dans le champ "response"
        if "response" in data:
            return {"answer": data["response"]}
        else:
            return {"answer": "Pas de réponse disponible"}
    
    except requests.exceptions.RequestException as e:
        return {"answer": f"Erreur de connexion à Ollama: {str(e)}"}
    except json.JSONDecodeError as e:
        return {"answer": f"Erreur de décodage JSON: {str(e)}"}

@app.get("/")
def home():
    return {"message": "AI service is running!"}