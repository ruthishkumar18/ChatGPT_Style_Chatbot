from flask import Flask, request, jsonify, send_file, render_template, redirect, session
from flask_cors import CORS
from fpdf import FPDF
import os
import json
import datetime
import uuid
import requests

app = Flask(__name__)
CORS(app)
app.secret_key = "super-secret-key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")
HISTORY_DIR = os.path.join(BASE_DIR, "chat_histories")
OLLAMA_API = "http://localhost:11434/api/chat"

if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({"admin": "admin123"}, f)

if not os.path.exists(HISTORY_DIR):
    os.makedirs(HISTORY_DIR)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    with open(USERS_FILE, "r") as f:
        users = json.load(f)

    if username in users:
        return jsonify({"error": "User already exists"}), 400

    users[username] = password
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

    return jsonify({"success": True})

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    with open(USERS_FILE, "r") as f:
        users = json.load(f)

    if username in users and users[username] == password:
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == "admin" and password == "admin123":
            session["admin_logged_in"] = True
            return redirect("/admin-dashboard")
        return render_template("admin_login.html", error="Invalid credentials")
    return render_template("admin_login.html")

@app.route("/admin-dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect("/admin-login")

    users = {}
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            users = json.load(f)

    user_history = {}
    if os.path.exists(HISTORY_DIR):
        for file in os.listdir(HISTORY_DIR):
            if file.endswith(".json") and "__" in file:
                username, filename = file.split("__", 1)
                user_history.setdefault(username, []).append(filename)

    return render_template("admin.html", users=users, user_history=user_history)

@app.route("/admin-logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin-login")

@app.route("/download-history")
def download_history():
    file = request.args.get("file")
    path = os.path.join(HISTORY_DIR, file)
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "File not found", 404

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user = data.get("user")
    message = data.get("message")

    if not message or not user:
        return jsonify({"response": "(Missing user or message)"}), 400

    temp_history_path = os.path.join(HISTORY_DIR, f"{user}_temp.json")

    if os.path.exists(temp_history_path):
        with open(temp_history_path, "r", encoding="utf-8") as f:
            chat_history = json.load(f)
    else:
        chat_history = []

    chat_history.append({"role": "user", "content": message})

    try:
        # Chat API call
        res = requests.post(OLLAMA_API, json={
            "model": "llama3",
            "messages": chat_history
        })

        lines = res.text.strip().splitlines()
        bot_reply = ""
        for line in lines:
            try:
                msg = json.loads(line)
                if "message" in msg and "content" in msg["message"]:
                    bot_reply += msg["message"]["content"]
            except:
                continue

        chat_history.append({"role": "assistant", "content": bot_reply})

        # Title prompt to AI
        title_prompt = {
            "role": "user",
            "content": "Suggest a short 3-5 word title for this chat. Avoid punctuation."
        }

        title_res = requests.post(OLLAMA_API, json={
            "model": "llama3",
            "messages": chat_history + [title_prompt]
        })

        ai_title = ""
        for line in title_res.text.strip().splitlines():
            try:
                msg = json.loads(line)
                if "message" in msg and "content" in msg["message"]:
                    ai_title += msg["message"]["content"]
            except:
                continue

        title = ai_title.strip().replace(" ", "_")[:40] or "chat"

        with open(temp_history_path, "w", encoding="utf-8") as f:
            json.dump(chat_history, f, indent=2)

        return jsonify({"response": bot_reply, "title": title, "session": chat_history})

    except Exception as e:
        return jsonify({"response": f"⚠ Error: {str(e)}"}), 500

@app.route("/export-pdf", methods=["POST"])
def export_pdf():
    data = request.get_json()
    session_data = data.get("session", [])
    title = data.get("title", f"chat_{uuid.uuid4().hex[:6]}")
    user = request.headers.get("user") or "guest"
    filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{title}.json"

    filepath = os.path.join(HISTORY_DIR, f"{user}__{filename}")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"title": title, "chat": session_data}, f, indent=2)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.multi_cell(0, 10, f"Chat Title: {title}\n")
    pdf.ln(5)
    pdf.set_font("Arial", size=12)

    for msg in session_data:
        role = msg.get("role", "").capitalize()
        content = msg.get("content", "")
        pdf.multi_cell(0, 10, f"{role}: {content}\n")

    pdf_file = os.path.join(BASE_DIR, f"Chat_{title}.pdf")
    pdf.output(pdf_file)

    return send_file(pdf_file, as_attachment=True)

@app.route("/history", methods=["POST"])
def history():
    data = request.get_json()
    user = data.get("user")
    if not user:
        return jsonify({"error": "User not provided"}), 400

    files = os.listdir(HISTORY_DIR)
    user_files = [f for f in files if f.startswith(f"{user}__") and f.endswith(".json")]

    history_list = []
    for f in user_files:
        try:
            with open(os.path.join(HISTORY_DIR, f), "r", encoding="utf-8") as file:
                file_data = json.load(file)
                history_list.append({
                    "filename": f,
                    "title": file_data.get("title", f.split("__")[-1].replace(".json", ""))
                })
        except:
            continue

    return jsonify(history_list)

@app.route("/load-history", methods=["POST"])
def load_history():
    data = request.get_json()
    filename = data.get("filename")
    full_path = os.path.join(HISTORY_DIR, filename)

    if not os.path.exists(full_path):
        return jsonify({"error": "Chat file not found"}), 404

    with open(full_path, "r", encoding="utf-8") as f:
        chat_data = json.load(f)

    return jsonify(chat_data)

@app.route("/download-text", methods=["POST"])
def download_text():
    data = request.get_json()
    filename = data.get("filename")
    full_path = os.path.join(HISTORY_DIR, filename)

    if not os.path.exists(full_path):
        return jsonify({"error": "Chat file not found"}), 404

    with open(full_path, "r", encoding="utf-8") as f:
        chat_data = json.load(f)

    title = chat_data.get("title", "chat_session")
    chat = chat_data.get("chat", [])

    text_content = f"Chat Title: {title}\n\n"
    for msg in chat:
        text_content += f"{msg['role'].capitalize()}: {msg['content']}\n\n"

    txt_filename = os.path.join(BASE_DIR, f"{title}.txt")
    with open(txt_filename, "w", encoding="utf-8") as txt_file:
        txt_file.write(text_content)

    return send_file(txt_filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
