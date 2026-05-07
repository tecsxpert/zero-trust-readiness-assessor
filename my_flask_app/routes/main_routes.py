from flask import Blueprint, request, jsonify
from services.ai_service import process_data
import threading

main = Blueprint('main', __name__)

# Dummy database (temporary)
database = []

@main.route('/create', methods=['POST'])
def create():
def home():
    return "Flask App Running!"


# 🔹 Async AI function
def generate_ai_result_async(data):
    try:
        result = process_data(data)

        if result and "response" in result:
            data["ai_result"] = result["response"]
        else:
            data["ai_result"] = "No AI result"

    except Exception:
        data["ai_result"] = "AI failed"


# 🔹 CREATE API (Day 5 task)
@main.route('/create', methods=['POST'])
def create():
    data = request.json

    # Save initial data
    database.append(data)

    # Run AI in background
    thread = threading.Thread(target=generate_ai_result_async, args=(data,))
    thread.start()

    return jsonify({
        "message": "Created successfully",
        "data": data
    })

