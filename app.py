from pydoc import text
import re
import sqlite3
import os
from reportlab.lib import styles
from reportlab.lib import styles
import requests
from flask import Flask, render_template, request, redirect, session
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from openai import OpenAI
from flask import jsonify
from flask import send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer,Image
from reportlab.platypus import HRFlowable
from reportlab.platypus import Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.pagesizes import A4
from io import BytesIO
from reportlab.platypus import Preformatted
import PyPDF2
import math
import re
import pytesseract
import pdfplumber
from pdf2image import convert_from_path
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
pdfmetrics.registerFont(TTFont('HindiFont', 'static/fonts/NotoSansDevanagari-Regular.ttf'))
pdfmetrics.registerFont(TTFont('TeluguFont', 'static/fonts/NotoSansTelugu-Regular.ttf'))
def extract_text_from_pdf(pdf_path):
    text = ""

    # Try normal text extraction first
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
    except:
        pass

    # If little text found → run OCR
    if len(text.strip()) < 50:
        print("Scanned PDF detected → Running OCR")
        images = convert_from_path(pdf_path)

        for img in images:
            text += pytesseract.image_to_string(img)

    return text
# ---------------- RISK SCORE ENGINE ----------------

def calculate_risk_score(text):
    score = 0

    critical_keywords = [
        "critical", "very high", "very low",
        "severe", "danger", "heart attack",
        "stroke", "renal failure"
    ]

    moderate_keywords = [
        "elevated", "borderline", "mild",
        "abnormal"
    ]

    for word in critical_keywords:
        if word in text.lower():
            score += 30

    for word in moderate_keywords:
        if word in text.lower():
            score += 10

    if score >= 70:
        level = "HIGH"
    elif score >= 40:
        level = "MODERATE"
    else:
        level = "LOW"

    return score, level
FOURSQUARE_API_KEY = os.environ.get("FOURSQUARE_API_KEY")
headers = {
    "Authorization": FOURSQUARE_API_KEY
}
client = OpenAI(
    API_KEY = os.getenv("API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

app = Flask(__name__)

app.secret_key = "supersecretkey123"

@app.context_processor
def inject_active_page():
    return dict(active_page=request.endpoint)

# -------- DATABASE --------
def init_db():
    conn = sqlite3.connect("database.db")
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'user'
        )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        report_text TEXT,
        ai_analysis TEXT,
        risk_score INTEGER,
        severity TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        hospital_name TEXT,
        status TEXT DEFAULT 'PENDING',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    try:
        c.execute("ALTER TABLE users ADD COLUMN phone NUMERIC")
        c.execute("ALTER TABLE users ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN profile_image TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

init_db()

# -------- DISTANCE CALCULATOR (Haversine Formula) --------
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in KM

    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)

    a = (math.sin(dLat/2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dLon/2) ** 2)

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# -------- HOME --------
@app.route("/")
def home():
    return render_template("welcome.html")

@app.route("/auth")
def auth():
    return render_template("index.html")

# -------- REGISTER --------
@app.route("/register", methods=["POST"])
def register():

    first_name = request.form["first_name"]
    last_name = request.form["last_name"]
    email = request.form["email"]
    password = generate_password_hash(request.form["password"])

    username = first_name + " " + last_name

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    try:
        cursor.execute("""
        INSERT INTO users (username,email,password,role)
        VALUES (?,?,?,?)
        """, (username,email,password,"user"))

        conn.commit()

        user_id = cursor.lastrowid

        conn.close()

        # create session
        session["user"] = username
        session["user_id"] = user_id
        session["role"] = "user"
        session["language"] = "en"

        return redirect("/dashboard")

    except sqlite3.IntegrityError:

        conn.close()

        return render_template(
            "index.html",
            error="Email already exists"
        )
    

# -------- LOGIN --------
@app.route("/login", methods=["POST"])
def login():

    email = request.form["email"]
    password = request.form["password"]

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE email=?",
        (email,)
    )

    user = cursor.fetchone()

    conn.close()

    if user and check_password_hash(user["password"], password):

        session["user"] = user["username"]
        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["language"] = "en"

        return redirect("/dashboard")

    return render_template(
        "index.html",
        error="Invalid email or password"
    )

@app.route("/edit-profile")
def edit_profile():

    if "user_id" not in session:
        return redirect("/")

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username, email, phone, profile_image
        FROM users
        WHERE id=?
    """, (session["user_id"],))

    user = cursor.fetchone()
    conn.close()

    return render_template(
        "edit_profile.html",
        user=user,
        active_page="profile"
    )

@app.route("/save-profile", methods=["POST"])
def save_profile():

    if "user_id" not in session:
        return jsonify({"status": "error"})

    name = request.form.get("name")
    email = request.form.get("email")
    phone = request.form.get("phone")

    image = request.files.get("profile_image")

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    # -------- PROFILE IMAGE --------

    filename = None

    if image and image.filename != "":

        filename = f"user_{session['user_id']}.png"

        os.makedirs("static/profile_images", exist_ok=True)

        image_path = os.path.join("static/profile_images", filename)

        image.save(image_path)

        cursor.execute("""
            UPDATE users
            SET username=?, email=?, phone=?, profile_image=?
            WHERE id=?
        """, (name, email, phone, filename, session["user_id"]))

    else:

        cursor.execute("""
            UPDATE users
            SET username=?, email=?, phone=?
            WHERE id=?
        """, (name, email, phone, session["user_id"]))

    conn.commit()
    conn.close()

    # update session
    session["user"] = name

    return jsonify({"status": "success"})

@app.route("/change-password", methods=["POST"])
def change_password():

    if "user_id" not in session:
        return jsonify({"status": "error"})

    current_password = request.form.get("current_password")
    new_password = request.form.get("new_password")

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT password FROM users WHERE id=?",
        (session["user_id"],)
    )

    user = cursor.fetchone()

    if not check_password_hash(user["password"], current_password):

        return jsonify({
            "status": "error",
            "message": "Current password incorrect"
        })

    new_hash = generate_password_hash(new_password)

    cursor.execute(
        "UPDATE users SET password=? WHERE id=?",
        (new_hash, session["user_id"])
    )

    conn.commit()
    conn.close()

    return jsonify({"status": "success"})

# -------- USER DASHBOARD --------
@app.route("/dashboard")
def dashboard():
    if session.get("role") == "user":
        return render_template("dashboard.html", username=session["user"],active_page="dashboard")
    return redirect("/")

@app.route("/set_language", methods=["POST"])
def set_language():
    lang = request.json.get("language")
    session["language"] = lang
    return jsonify({"status": "success"})

@app.route("/get-language")
def get_language():
    return jsonify({"language": session.get("language", "en")})

@app.route("/ai-chat")
def ai_chat():
    if "user" in session:
        return render_template("chat.html", username=session["user"],active_page="ai-chat")
    return redirect("/")

# -------- CHAT -------
@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    lang = session.get("language", "en")

    if "consult_stage" not in session:
        session["consult_stage"] = "questions"
        session["question_count"] = 0
        session["chat_history"] = []

    session["chat_history"].append({"role": "user", "content": user_message})

    # ---------------- LANGUAGE ----------------
    if lang == "hi":
        language_instruction = "Respond completely in Hindi using simple language."
    elif lang == "te":
        language_instruction = "Respond completely in Telugu using simple language."
    else:
        language_instruction = "Respond completely in simple English."

    system_prompt=""

    # ---------------- STAGE 1: ASK QUESTIONS ----------------
    if session["consult_stage"] == "questions":

        if session["question_count"] < 4:

            system_prompt = f"""
You are a senior medical doctor with 15+ years of clinical experience conducting a real consultation.

You must respond ONLY in {language_instruction}.

STRICT RULES:

1. Respond ONLY to health-related questions.
2. If the question is not medical, respond EXACTLY with:
"I am a Medical AI Assistant. Please ask health-related questions only."
3. Do NOT talk about coding, movies, entertainment, politics, or general topics.
4. Stay strictly in medical context.
5. Use simple language the patient can understand.
6. Be professional.

CONSULTATION RULES:

- Ask ONE question at a time.
- Ask questions related to symptoms.
- Minimum 3 questions before analysis.
- Do NOT ask all questions at once.
- Do NOT give diagnosis.
- Do NOT give treatment yet.

NEVER SAY:
- "Ask me anything"
- "Let me know if you need anything else"

Keep the question short and natural.
"""

            session["question_count"] += 1

        else:
            session["consult_stage"] = "analysis"

            system_prompt = f"""
You are a senior medical doctor with 15+ years of clinical experience.

You must respond ONLY in {language_instruction}.

STRICT RULES:

1. Respond ONLY to health-related topics.
2. Do NOT add extra explanations.
3. Do NOT change the report format.
4. Do NOT add introduction or conclusion text.
5. Return ONLY the medical report.
6. Use short professional sentences.

----------------------------------------
CLINICAL REPORT FORMAT (STRICT)
----------------------------------------

Return response in this EXACT structured format.

=============================
🏥 MEDICAL ASSESSMENT REPORT
=============================

🔴 URGENCY LEVEL: (Low / Moderate / High / Emergency)

📊 RISK SCORE: (0–10)

----------------------------------------
🩺 1. Symptom Summary

- Clear short explanation of what patient reported.

----------------------------------------
🧠 2. Clinical Interpretation

- What the symptoms suggest.

- Brief reasoning in simple words.

----------------------------------------
🔍 3. Most Likely Conditions

List 2–4 possibilities:

1. Condition name

- Why this fits

2. Condition name

- Why this fits

3. Condition name

- Why this fits

----------------------------------------
💊 4. Recommended Action Plan

Immediate Steps:

- Bullet points

Home Care Advice:

- Bullet points

Medical Evaluation Needed If:

- Bullet points

----------------------------------------
🚨 5. Emergency Warning Signs

If any of these occur, seek immediate care:

- Bullet points

----------------------------------------
📅 6. Monitoring Advice

- What to track

- When to reassess

----------------------------------------
⚠️ Medical Disclaimer

This is not a confirmed diagnosis.

Consult a licensed doctor for proper evaluation.
"""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                *session["chat_history"]
            ],
            temperature=0.2,
            max_tokens=600
        )

        ai_reply = response.choices[0].message.content

        # Save final report only in analysis stage
        if session["consult_stage"] == "analysis":
            session["final_report"] = ai_reply

        session["chat_history"].append(
            {"role": "assistant", "content": ai_reply}
        )

        session.modified = True
        return jsonify({"reply": ai_reply})

    except Exception as e:
        print("AI ERROR:", e)
    return jsonify({"reply": "AI service unavailable."})

@app.route("/download-report")
def download_report():
    report_id = request.args.get("report_id")

    if report_id:
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM reports WHERE id=?", (report_id,))
        report = cursor.fetchone()
        conn.close()

        if not report:
            return "Report not found"

        session["final_report"] = report["ai_analysis"]
        session["risk_score"] = report["risk_score"]
        session["severity"] = report["severity"]

    if "final_report" not in session:
        return "No report available"

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)

    elements = []
    styles = getSampleStyleSheet()
    lang = session.get("language", "en")
    if lang == "hi":
        labels = {
            "title": "मेडिकल एआई रिपोर्ट विश्लेषण",
            "risk": "जोखिम स्कोर",
            "severity": "गंभीरता स्तर"
        }
    elif lang == "te":
        labels = {
            "title": "మెడికల్ AI రిపోర్ట్ విశ్లేషణ",
            "risk": "రిస్క్ స్కోర్",
            "severity": "తీవ్రత స్థాయి"
        }
    else:
        labels = {
            "title": "Medical AI Report Analysis",
            "risk": "Risk Score",
            "severity": "Severity Level"
        }

    if lang == "hi":
        selected_font = "HindiFont"
    elif lang == "te":
        selected_font = "TeluguFont"
    else:
        selected_font = "Helvetica"

    custom_style = ParagraphStyle(
    name='CustomStyle',
    parent=styles["Normal"],
    fontName=selected_font,
    fontSize=11
    )

    # 🔹 LOGO (Top Left)
    logo_path = os.path.join(app.root_path, "static", "logo.png")
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=1.5*inch, height=1*inch)
    else:
        logo = Paragraph("Medical AI", styles["Heading2"])

    # 🔹 TITLE (Top Right)
    title = Paragraph(
        f"<b>{labels['title']}</b>",
        styles["Heading2"]
    )

    header_table = Table([[logo, title]], colWidths=[2*inch, 4*inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    elements.append(header_table)
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(HRFlowable(width="100%", thickness=1))
    elements.append(Spacer(1, 0.3 * inch))

    # 🔹 RISK SCORE BOX
    risk_score = session.get("risk_score", "N/A")
    severity = session.get("severity", "N/A")

    risk_text = f"""
    <b>{labels['risk']}:</b> {risk_score}/100<br/>
    <b>{labels['severity']}:</b> {severity}
    """

    risk_paragraph = Paragraph(risk_text, custom_style)
    elements.append(risk_paragraph)
    elements.append(Spacer(1, 0.3 * inch))

    # 🔹 ANALYSIS CONTENT
    report_text = session["final_report"]

    formatted_report = report_text.replace("\n", "<br/>")

    report_paragraph = Paragraph(formatted_report, custom_style)
    elements.append(report_paragraph)

    def add_watermark(canvas, doc):
        canvas.saveState()
        canvas.setFont(selected_font, 60)
        canvas.setFillColorRGB(0.9, 0.9, 0.9)
        canvas.drawCentredString(300, 400, "Medical AI")
        canvas.restoreState()

    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)

    buffer.seek(0)

    download = request.args.get("download")

    return send_file(
    buffer,
    as_attachment=(download == "true"),
    download_name="Medical_AI_Report.pdf",
    mimetype="application/pdf"
)


@app.route("/patient-details")
def patient_details():

    if "final_report" not in session:
        return redirect("/medical-report")

    return render_template("patient_details.html")

@app.route("/generate-pdf", methods=["POST"])
def generate_pdf():

    if "final_report" not in session:
        return redirect("/medical-report")

    patient_name = request.form["patient_name"]
    age = request.form["age"]
    gender = request.form["gender"]
    date = request.form["date"]
    doctor = request.form["doctor"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)

    elements = []
    styles = getSampleStyleSheet()
    lang = session.get("language", "en")
    if lang == "hi":
        labels = {
            "title": "मेडिकल एआई डायग्नोस्टिक रिपोर्ट",
            "risk": "जोखिम स्कोर",
            "severity": "गंभीरता"
        }
    elif lang == "te":
        labels = {
            "title": "మెడికల్ AI నిర్ధారణ నివేదిక",
            "risk": "రిస్క్ స్కోర్",
            "severity": "తీవ్రత"
        }
    else:
        labels = {
            "title": "Medical AI Diagnostic Report",
            "risk": "Risk Score",
            "severity": "Severity"
        }

    if lang == "hi":
        selected_font = "HindiFont"
    elif lang == "te":
        selected_font = "TeluguFont"
    else:
        selected_font = "Helvetica"

    custom_style = ParagraphStyle(
        name='CustomStyle',
        parent=styles["Normal"],
        fontName=selected_font,
        fontSize=11
    )
    logo_path = os.path.join(app.root_path, "static", "logo.png")

    if os.path.exists(logo_path):
        logo = Image(logo_path, width=120, height=60)
        elements.append(logo)
        elements.append(Spacer(1, 20))
    # 🔹 HEADER
    elements.append(Paragraph(f"<b>{labels['title']}</b>", styles["Title"]))
    elements.append(Spacer(1, 0.3 * inch))

    # 🔹 PATIENT DETAILS BLOCK
    details_data = [
        ["Patient Name:", patient_name],
        ["Age / Gender:", f"{age} / {gender}"],
        ["Date:", date],
        ["Referred By:", doctor if doctor else "Self"]
    ]

    table = Table(details_data, colWidths=[2*inch, 3*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
        ('BOX', (0,0), (-1,-1), 1, colors.grey),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.4 * inch))

    # 🔹 RISK INFO
    risk_score = session.get("risk_score","N/A")
    severity = session.get("severity","N/A")

    elements.append(Paragraph(
        f"<b>{labels['risk']}:</b> {risk_score}/100<br/><b>{labels['severity']}:</b> {severity}",
        custom_style
    ))

    elements.append(Spacer(1, 0.4 * inch))

    # 🔹 REPORT CONTENT
    report_text = session["final_report"]
    formatted = report_text.replace("\n", "<br/>")

    elements.append(Paragraph(formatted, custom_style))

    doc.build(elements)

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Medical_AI_Report.pdf",
        mimetype="application/pdf"
    )

@app.route("/medical-report")
def medical_report():
    return render_template("medical_report.html", active_page="medical-report")

@app.route("/analyze-report", methods=["POST"])
def analyze_report():

    if "user_id" not in session:
        return redirect("/")

    file = request.files["report_file"]

    if not file:
        return render_template("medical_report.html", analysis="No file uploaded.")

    content = ""

    if file.filename.endswith(".pdf"):
        temp_path = "temp_uploaded.pdf"
        file.save(temp_path)

        content = convert_from_path(temp_path)

        os.remove(temp_path)

    elif file.filename.endswith(".txt"):
        content = file.read().decode("utf-8")

    else:
        return render_template("medical_report.html", analysis="Unsupported file type.")

    content = ""

    if file.filename.endswith(".txt"):
        content = file.read().decode("utf-8")

    elif file.filename.endswith(".pdf"):
        pdf_reader = PyPDF2.PdfReader(file)
        for page in pdf_reader.pages:
            content += page.extract_text() or ""

    else:
        return render_template("medical_report.html", analysis="Unsupported file type.")

    system_prompt = """
You are a senior hospital consultant physician with 15+ years of clinical experience.

You are analyzing a patient's medical laboratory report.

Your task is to interpret the report and provide professional clinical guidance.

IMPORTANT STRICT RULES:

1. Respond ONLY with the structured analysis.
2. Follow the section order EXACTLY.
3. Do NOT add any sections.
4. Do NOT remove any sections.
5. Do NOT add introductions or explanations outside the format.
6. Use professional hospital tone.
7. Use short clear medical sentences.
8. Highlight abnormal values clearly.
9. If dangerous or life-threatening values appear, classify as HIGH RISK.
10. Do NOT use Markdown formatting.
11. Do NOT use ** or * or ###.
12. Use plain text only.
13. Use bullet points and spacing for clarity.
14. Do NOT write long paragraphs.

--------------------------------------------------

YOUR OUTPUT MUST FOLLOW THIS EXACT STRUCTURE

--------------------------------------------------

1️⃣ Report Summary

- Brief explanation of the overall report.
- Mention the main systems involved.

--------------------------------------------------

2️⃣ Abnormal Findings

List abnormal values clearly:

- Test name : value (Normal range)
- Test name : value (Normal range)

Only include abnormal findings.

--------------------------------------------------

3️⃣ Risk Assessment

Risk Score (0-100):

Severity Level:
Low
Moderate
High

--------------------------------------------------

4️⃣ Possible Medical Conditions

List possible medical conditions based on abnormal findings.

- Condition name
- Condition name
- Condition name

--------------------------------------------------

5️⃣ Immediate Medical Recommendations

- Medical tests required
- Doctor consultation advice
- Any urgent follow-up needed

--------------------------------------------------

6️⃣ Lifestyle Modifications

- Diet changes
- Exercise advice
- Sleep / stress management

--------------------------------------------------

7️⃣ Emergency Warning Signs

If any of the following symptoms appear, seek immediate medical attention:

- Warning symptom
- Warning symptom

If no emergency signs are present, clearly state:
"No immediate emergency signs detected."

--------------------------------------------------

8️⃣ Final Disclaimer

This analysis is generated by an AI system and is not a confirmed medical diagnosis.

Consult a licensed healthcare professional for proper medical evaluation.
"""
    response = client.chat.completions.create(
        model="openai/gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ],
        temperature=0.3,
        max_tokens=600
    )
    

    analysis = response.choices[0].message.content


    # -------- APPLY RISK ENGINE --------
    score, level = calculate_risk_score(analysis)
    session["risk_score"] = score
    session["severity"] = level
    session["final_report"] = analysis

    analysis += f"\n\n-----------------------------"
    analysis += f"\n📊 RISK SCORE: {score}/100"
    analysis += f"\n🔴 SEVERITY LEVEL: {level}"
    analysis += f"\n-----------------------------"
        # Remove markdown symbols
    analysis = re.sub(r"\*\*(.*?)\*\*", r"\1", analysis)
    analysis = re.sub(r"\*(.*?)\*", r"\1", analysis)
    analysis = re.sub(r"#+ ", "", analysis)
    analysis = re.sub(r"---+", "", analysis)
    analysis = re.sub(r"\n{3,}", "\n\n", analysis)
    analysis = analysis.replace("\n", "<br/>")

    if level == "HIGH":
        analysis = "🚨 EMERGENCY ALERT 🚨\n\n" + analysis

    # -------- SAVE TO DATABASE --------
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO reports (user_id, report_text, ai_analysis, risk_score, severity)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        content,
        analysis,
        score,
        level
    ))

    conn.commit()
    conn.close()

    return render_template(
        "medical_report.html",
        analysis=analysis,
        score=score,
        severity=level
    )

@app.route("/report-history")
def report_history():

    if "user_id" not in session:
        return redirect("/")

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM reports
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (session["user_id"],))

    reports = cursor.fetchall()
    conn.close()

    return render_template("report_history.html", reports=reports,active_page="report-history")

@app.route("/find-hospitals-fsq", methods=["POST"])
def find_hospitals_fsq():

    data = request.json
    lat = data.get("lat")
    lon = data.get("lon")

    if not lat or not lon:
        return jsonify({"hospitals": []})

    url = "https://api.foursquare.com/v3/places/search"

    headers = {
        "Accept": "application/json",
        "Authorization": FOURSQUARE_API_KEY
    }

    params = {
        "query": "hospital",
        "ll": f"{lat},{lon}",
        "radius": 8000,
        "limit": 20
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    hospitals = []

    for place in data.get("results", []):

        hospitals.append({
            "name": place.get("name"),
            "address": place.get("location", {}).get("formatted_address"),
            "lat": place.get("geocodes", {}).get("main", {}).get("latitude"),
            "lng": place.get("geocodes", {}).get("main", {}).get("longitude"),
            "categories": [c["name"] for c in place.get("categories", [])]
        })

    return jsonify({"hospitals": hospitals})

@app.route("/appointments")
def appointments():
    return render_template("appointments.html",active_page="appointments")


# -------- FIND HOSPITALS USING OVERPASS API --------

@app.route("/find-hospitals", methods=["POST"])
def find_hospitals():

    data = request.json
    location = data.get("location")

    if not location:
        return jsonify({"hospitals": []})

    # 1️⃣ Get coordinates using Nominatim
    geo_url = "https://nominatim.openstreetmap.org/search"
    geo_params = {
        "q": location,
        "format": "json",
        "limit": 1
    }

    geo_response = requests.get(geo_url, params=geo_params, headers={
        "User-Agent": "medical-ai-app"
    })

    geo_data = geo_response.json()

    if not geo_data:
        return jsonify({"hospitals": []})

    lat = float(geo_data[0]["lat"])
    lon = float(geo_data[0]["lon"])

    # 2️⃣ Search hospitals within 8km radius
    overpass_query = f"""
    [out:json];
    (
      node["amenity"="hospital"](around:8000,{lat},{lon});
      way["amenity"="hospital"](around:8000,{lat},{lon});
      relation["amenity"="hospital"](around:8000,{lat},{lon});
    );
    out center;
    """

    overpass_url = "https://overpass-api.de/api/interpreter"

    response = requests.post(
        overpass_url,
        data={"data": overpass_query}
    )

    try:
        data = response.json()
    except:
        return jsonify({"hospitals": []})

    hospitals = []

    for element in data["elements"]:

        tags = element.get("tags", {})

        name = tags.get("name", "Unnamed Hospital")

        # 👇 ADD DETAILS HERE
        phone = tags.get("phone") or tags.get("contact:phone") or "Not Available"
        website = tags.get("website") or tags.get("contact:website") or ""
        opening_hours = tags.get("opening_hours", "Not Available")
        emergency = tags.get("emergency", "Unknown")
        healthcare = tags.get("healthcare", tags.get("amenity", "General"))

        if "lat" in element:
            h_lat = element["lat"]
            h_lon = element["lon"]
        else:
            h_lat = element["center"]["lat"]
            h_lon = element["center"]["lon"]

        distance = round(calculate_distance(lat, lon, h_lat, h_lon), 2)
        hospitals.append({
        "name": name,
        "lat": h_lat,
        "lon": h_lon,
        "distance": distance,
        "phone": phone,
        "website": website,
        "opening_hours": opening_hours,
        "emergency": emergency,
        "healthcare": healthcare
    })

    # Sort by nearest
    hospitals.sort(key=lambda x: x["distance"])

    return jsonify({"hospitals": hospitals}) 

@app.route("/profile")
def profile():

    if "user_id" not in session:
        return redirect("/")

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username, email, phone, profile_image
        FROM users
        WHERE id=?
    """, (session["user_id"],))

    user = cursor.fetchone()

    # ---------- STATS ----------

    cursor.execute("SELECT COUNT(*) FROM reports WHERE user_id=?",
                   (session["user_id"],))
    total_reports = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM appointments WHERE user_id=?",
                   (session["user_id"],))
    total_appointments = cursor.fetchone()[0]

    total_chats = len(session.get("chat_history", []))

    conn.close()

    return render_template(
        "profile.html",
        username=user["username"],
        email=user["email"],
        created_at="Jan 2026",   # you can store this later
        total_reports=total_reports,
        total_appointments=total_appointments,
        total_chats=total_chats
    )

# -------- ADMIN PANEL --------
@app.route("/admin")
def admin():
    if session.get("role") == "admin":
        return render_template("dashboard.html", username=session["user"])
    return redirect("/")

# -------- LOGOUT --------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)