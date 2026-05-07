from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
import time
import redis
import hashlib
import json
import chromadb

from werkzeug.serving import WSGIRequestHandler

WSGIRequestHandler.server_version = ""
WSGIRequestHandler.sys_version = ""

load_dotenv(override=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024

# =========================
# CHROMADB SETUP
# =========================
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="security_knowledge")

documents = [
    "Zero Trust means never trust, always verify.",
    "Multi-factor authentication improves login security.",
    "Regular patching prevents vulnerabilities.",
    "Use HTTPS to encrypt communication.",
    "Firewalls block unauthorized access.",
    "Least privilege reduces attack surface.",
    "Monitor logs for suspicious activity.",
    "Endpoint protection prevents malware.",
    "Strong passwords reduce hacking risk.",
    "Network segmentation improves security."
]

# Add documents safely (avoid duplicate crash)
existing = collection.get()["ids"]
for i, doc in enumerate(documents):
    if str(i) not in existing:
        collection.add(
            ids=[str(i)],
            documents=[doc]
        )

def get_context(query):
    results = collection.query(
        query_texts=[query],
        n_results=2
    )
    return " ".join(results["documents"][0])

# =========================
# API KEY
# =========================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY missing in .env")

# =========================
# REDIS CACHE
# =========================
try:
    redis_client = redis.Redis(host='redis', port=6379, db=0)
    redis_client.ping()
    CACHE_ENABLED = True
except:
    redis_client = None
    CACHE_ENABLED = False

CACHE_TTL = 900

# =========================
# METRICS
# =========================
start_time = time.time()
request_times = []

@app.before_request
def before_request():
    request.start_time = time.time()

@app.after_request
def after_request(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self';"
    )

    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
    response.headers.pop("Server", None)

    elapsed = time.time() - request.start_time
    request_times.append(elapsed)

    if len(request_times) > 100:
        request_times.pop(0)

    return response

# =========================
# ROUTES
# =========================
@app.route('/')
def home():
    return jsonify({"message": "Zero Trust API running"})

@app.route('/health')
def health():
    uptime = time.time() - start_time
    avg_response = sum(request_times) / len(request_times) if request_times else 0

    return jsonify({
        "status": "ok",
        "uptime": round(uptime, 2),
        "avg_response_time": round(avg_response, 4),
        "requests_tracked": len(request_times),
        "cache_enabled": CACHE_ENABLED
    })

@app.route('/robots.txt')
def robots():
    return "User-agent: *\nDisallow:", 200, {"Content-Type": "text/plain"}

# =========================
# CACHE KEY
# =========================
def make_cache_key(data):
    versioned = {"v": "2", "data": data}
    return hashlib.sha256(
        json.dumps(versioned, sort_keys=True).encode()
    ).hexdigest()

# =========================
# MAIN API
# =========================
@app.route('/recommend', methods=['POST'])
def recommend():
    data = request.get_json(silent=True) or {}
    user_input = data.get("input", "")

    if not isinstance(user_input, str) or len(user_input) > 1000:
        return jsonify({"error": "Invalid input"}), 400

    cache_key = make_cache_key(data)

    if CACHE_ENABLED:
        cached = redis_client.get(cache_key)
        if cached:
            return jsonify({
                "result": json.loads(cached),
                "cached": True
            })

    context = get_context(user_input)

    final_prompt = f"""
Context:
{context}

User Input:
{user_input}

You MUST respond ONLY in valid JSON.

Format:
{{
  "risk_level": "Low/Medium/High",
  "recommendations": [
    "short point 1",
    "short point 2",
    "short point 3"
  ]
}}
"""

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": "You are a Zero Trust security expert."},
            {"role": "user", "content": final_prompt}
        ]
    }

    fallback = {
        "risk_level": "Medium",
        "recommendations": ["Enable basic security controls"]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response_json = response.json()
        ai_text = response_json["choices"][0]["message"]["content"]

        try:
            parsed = json.loads(ai_text)
        except:
            parsed = fallback

        ai_message = parsed

    except:
        ai_message = fallback

    result = {
        "context_used": context,
        "output": ai_message
    }

    if CACHE_ENABLED:
        redis_client.setex(cache_key, CACHE_TTL, json.dumps(result))

    return jsonify({
        "result": result,
        "cached": False
    })

# =========================
# RUN
# =========================
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)