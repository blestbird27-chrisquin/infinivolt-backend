import os
import uuid
import tempfile
import subprocess
import requests
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Initialize FastAPI Application
app = FastAPI(title="InfiniVolt Hubtel USSD, Voice AI & Payment Gateway Core")

# ================= CORS MIDDLEWARE CONFIGURATION =================
# Allows frontend applications (React, Vite, Next.js, Flutter Web, etc.) 
# to make cross-origin HTTP requests to this backend without browser blocking.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust to specific domains in production (e.g., ["http://localhost:3000"])
    allow_credentials=True,
    allow_methods=["*"],  # Allows GET, POST, OPTIONS, etc.
    allow_headers=["*"],  # Allows all headers
)

# ================= CONFIGURATION & CREDENTIALS =================
PAYSTACK_SECRET_KEY = os.getenv(
    "PAYSTACK_SECRET_KEY", 
    "sk_test_5e570189614030c5d08de245ef58d3600cdaacbc"
)
PAYSTACK_PUBLIC_KEY = os.getenv(
    "PAYSTACK_PUBLIC_KEY", 
    "pk_test_ee7a676e0de6a5f00870d2e7f9a328d3986b1307"
)

HUBTEL_CLIENT_ID = os.getenv("HUBTEL_CLIENT_ID", "YOUR_HUBTEL_CLIENT_ID")
HUBTEL_CLIENT_SECRET = os.getenv("HUBTEL_CLIENT_SECRET", "YOUR_HUBTEL_CLIENT_SECRET")
HUBTEL_MERCHANT_ACCOUNT = os.getenv("HUBTEL_MERCHANT_ACCOUNT", "YOUR_POS_SALES_ACCOUNT_NUMBER")

# Khaya AI Configuration
KHAYA_API_KEY = os.getenv("KHAYA_API_KEY", "YOUR_KHAYA_SUBSCRIPTION_KEY")
KHAYA_ASR_URL = os.getenv("KHAYA_ASR_URL", "https://translation.ghananlp.org/v2/transcribe")

# In-Memory Session & Task Store
user_sessions: Dict[str, Dict[str, Any]] = {}
voice_tasks: Dict[str, Dict[str, Any]] = {}

# Catalog Directories
DIRECTORY_CATALOG = {
    "banks": [
        "GCB Bank", "Ecobank Ghana", "Stanbic Bank", "ABSA Bank Ghana", "Fidelity Bank",
        "CalBank", "Zenith Bank", "Access Bank", "Consolidated Bank Ghana (CBG)",
        "Guaranty Trust Bank (GTBank)", "United Bank for Africa (UBA)"
    ],
    "senior_high_schools": [
        "Achimota School", "Prempeh College", "Opoku Ware School", "Wesley Girls' High School",
        "Holy Child School", "Mfantsipim School", "St. Augustine's College", "Aburi Girls' SHS",
        "Presbyterian Boys' SHS (PRESEC Legon)", "Tamale Senior High School", "Adisadel College"
    ],
    "nursing_colleges": [
        "Korle Bu Nursing & Midwifery College", "Pantang Nursing Training College",
        "Kumasi Nursing Training College", "Tamale Nurses' Training College"
    ],
    "teacher_training_colleges": [
        "Accra College of Education", "Tamale College of Education",
        "Wesley College of Education (Kumasi)", "OLA College of Education"
    ],
    "universities": [
        "University of Ghana (Legon)", "Kwame Nkrumah Univ. of Science & Tech (KNUST)",
        "University of Cape Coast (UCC)", "University for Development Studies (UDS)",
        "University of Energy and Natural Resources (UENR)", "Tamale Technical University (TaTU)",
        "Ho Technical University (HTU)", "Bolgatanga Technical University (BTU)",
        "Sunyani Technical University (STU)", "Kumasi Technical University (KsTU)"
    ]
}

# ----------------------------------------------------
# HELPER FUNCTIONS & INTEGRATIONS
# ----------------------------------------------------
def detect_momo_provider(phone_number: str) -> str:
    """Helper to detect Ghanaian Telecom Provider based on prefix."""
    cleaned = phone_number.replace("+233", "0").replace(" ", "").replace("-", "")
    if len(cleaned) >= 3:
        prefix = cleaned[:3]
        if prefix in ["024", "054", "055", "059", "025"]:
            return "mtn"
        elif prefix in ["020", "050"]:
            return "vodafone"  # Telecel Cash
        elif prefix in ["026", "056", "027", "057"]:
            return "tigo"      # AirtelTigo Money
    return "mtn"  # Fallback default

def trigger_paystack_direct_charge(phone_number: str, amount_ghs: float, description: str) -> bool:
    """Dispatches a Mobile Money Debit Prompt directly to the target device via Paystack."""
    url = "https://api.paystack.co/charge"
    amount_in_pesewas = int(round(amount_ghs * 100))
    provider = detect_momo_provider(phone_number)
    
    payload = {
        "amount": amount_in_pesewas,
        "email": "billing@infinivolt.com",
        "currency": "GHS",
        "mobile_money": {
            "phone": phone_number,
            "provider": provider
        },
        "metadata": {
            "description": description
        }
    }
    
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        res_data = response.json()
        return response.status_code in [200, 201] and res_data.get("status") is True
    except Exception as e:
        print(f"[Paystack Exception]: {e}")
        return False

def convert_audio_to_16k_wav(input_bytes: bytes, file_ext: str) -> Optional[bytes]:
    """Converts audio buffer to 16kHz Mono WAV using FFmpeg binary."""
    try:
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as in_file:
            in_file.write(input_bytes)
            in_file_path = in_file.name

        out_file_path = in_file_path + "_converted.wav"

        command = [
            "ffmpeg", "-y",
            "-i", in_file_path,
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            out_file_path
        ]
        
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        with open(out_file_path, "rb") as converted_f:
            wav_bytes = converted_f.read()

        if os.path.exists(in_file_path): os.remove(in_file_path)
        if os.path.exists(out_file_path): os.remove(out_file_path)

        return wav_bytes
    except Exception as e:
        print(f"[FFmpeg Conversion Error]: {e}")
        return None

def query_khaya_asr(wav_bytes: bytes, language: str = "tw") -> Optional[str]:
    """Calls Khaya AI Speech Recognition API safely from backend server."""
    headers = {
        "Ocp-Apim-Subscription-Key": KHAYA_API_KEY
    }
    files = {
        "file": ("audio.wav", wav_bytes, "audio/wav")
    }
    data = {
        "language": language
    }

    try:
        response = requests.post(KHAYA_ASR_URL, headers=headers, files=files, data=data, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            return res_json.get("text") or res_json.get("transcript") or str(res_json)
        else:
            print(f"[Khaya API Error {response.status_code}]: {response.text}")
            return None
    except Exception as e:
        print(f"[Khaya API Exception]: {e}")
        return None

def process_voice_order_background(task_id: str, raw_audio: bytes, file_ext: str, momo_number: str, language: str):
    """Executes heavy audio conversion, Khaya ASR transcription, and MoMo trigger asynchronously."""
    voice_tasks[task_id]["status"] = "converting_audio"

    wav_audio = convert_audio_to_16k_wav(raw_audio, file_ext)
    if not wav_audio:
        voice_tasks[task_id].update({
            "status": "failed",
            "error": "Audio conversion failed. Ensure FFmpeg is installed on your server."
        })
        return

    voice_tasks[task_id]["status"] = "transcribing"
    transcript = query_khaya_asr(wav_audio, language)
    
    if not transcript:
        voice_tasks[task_id].update({
            "status": "failed",
            "error": "Khaya AI failed to transcribe audio. Verify API key or audio clarity."
        })
        return

    voice_tasks[task_id]["transcript"] = transcript
    voice_tasks[task_id]["status"] = "dispatching_payment"

    payment_success = trigger_paystack_direct_charge(
        phone_number=momo_number,
        amount_ghs=10.00,
        description=f"Voice Purchase Order: {transcript[:50]}"
    )

    if payment_success:
        voice_tasks[task_id].update({
            "status": "completed",
            "momo_prompt_sent": True,
            "message": f"Transcribed: '{transcript}'. Payment prompt sent to {momo_number}."
        })
    else:
        voice_tasks[task_id].update({
            "status": "failed",
            "momo_prompt_sent": False,
            "error": "Transcription succeeded, but failed to trigger Paystack MoMo prompt."
        })

def format_ussd_response(session_id: str, type_str: str, message: str) -> Dict[str, Any]:
    """Helper matching Hubtel USSD engine JSON contract."""
    return {
        "SessionId": session_id,
        "Type": type_str,
        "Message": message,
        "ClientState": type_str
    }

def get_main_menu_text(mobile: str) -> str:
    masked = f"{mobile[:3]}**{mobile[-3:]}" if len(mobile) >= 7 else mobile
    return (
        f"1. Airtime\n"
        f"2. Data\n"
        f"3. Prepaid\n"
        f"4. Utility Bill\n"
        f"5. Institutional Fees\n"
        f"6. Toggle Active MoMo ({masked})"
    )

def build_numbered_menu(title: str, items: list) -> str:
    menu_lines = [f"[{title}]\nSelect Option:"]
    for idx, item in enumerate(items, start=1):
        menu_lines.append(f"{idx}. {item}")
    menu_lines.append("\n0. Back")
    return "\n".join(menu_lines)

# ----------------------------------------------------
# PYDANTIC REQUEST SCHEMAS
# ----------------------------------------------------
class AirtimePurchaseRequest(BaseModel):
    recipient_number: str
    network: Optional[str] = "MTN"
    amount: float
    momo_number: str

class DataPurchaseRequest(BaseModel):
    recipient_number: str
    network: Optional[str] = "MTN"
    package_name: str
    amount: float
    momo_number: str

class PrepaidPurchaseRequest(BaseModel):
    meter_number: str
    amount: float
    momo_number: str

class UtilityPaymentRequest(BaseModel):
    provider: str
    account_id: str
    amount: float
    momo_number: str

class InstitutionalFeesRequest(BaseModel):
    category: str
    institution_name: str
    student_id: str
    amount: float
    momo_number: str

# ----------------------------------------------------
# SYSTEM ENDPOINTS
# ----------------------------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return {
        "status": "online",
        "service": "InfiniVolt Hubtel USSD, Khaya Voice AI & Payment Core",
        "version": "2.2.0"
    }

# ================= VOICE-TO-TEXT ASYNC ENDPOINTS =================
@app.post("/api/voice/process", status_code=202)
async def process_voice_purchase(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    momo_number: str = Form(...),
    language: str = Form("tw")
):
    """
    Accepts voice audio from App Dashboard, proxies it to Khaya AI asynchronously, 
    and triggers Push USSD payment without blocking connection or timing out.
    """
    contents = await file.read()
    file_ext = os.path.splitext(file.filename)[1] or ".webm"

    task_id = str(uuid.uuid4())
    voice_tasks[task_id] = {
        "task_id": task_id,
        "status": "queued",
        "momo_number": momo_number,
        "language": language,
        "transcript": None
    }

    background_tasks.add_task(
        process_voice_order_background,
        task_id=task_id,
        raw_audio=contents,
        file_ext=file_ext,
        momo_number=momo_number,
        language=language
    )

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Voice processing started. Use task_id to poll status."
    }

@app.get("/api/voice/status/{task_id}")
def get_voice_task_status(task_id: str):
    """Polling endpoint for Dashboard to check transcription and MoMo prompt state."""
    task = voice_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task ID not found")
    return task

# ================= HUBTEL USSD WEBHOOK (*2007# ENGINE) =================
@app.post("/api/hubtel/ussd")
async def hubtel_ussd_webhook(request: Request):
    body = await request.json()
    session_id = body.get("SessionId", "")
    mobile = body.get("Mobile") or body.get("Msisdn") or "0247575763"
    request_type = body.get("Type", "")
    message = (body.get("Message") or "").strip()

    if session_id not in user_sessions or request_type == "Initiation":
        user_sessions[session_id] = {
            "step": "MAIN_MENU",
            "momo": mobile,
            "data": {}
        }
        return format_ussd_response(session_id, "Response", get_main_menu_text(mobile))

    session = user_sessions[session_id]
    current_step = session["step"]

    if current_step == "MAIN_MENU":
        if message == "1":
            session["data"]["service"] = "Airtime"
            session["step"] = "SELECT_FINANCIAL_SERVICE"
            return format_ussd_response(
                session_id, "Response",
                "[Airtime] Select Financial Service:\n1. MTN MoMo\n2. Telecel Cash\n3. AirtelTigo Money\n4. Bank Account Transfer\n\n0. Back"
            )
        elif message == "5":
            session["step"] = "SELECT_FEE_CATEGORY"
            return format_ussd_response(
                session_id, "Response",
                "[Fees Portal]\nSelect Category:\n1. Senior High Schools\n2. Nursing & Midwifery Colleges\n3. Teacher Training Colleges\n4. Universities & Technical Univs\n\n0. Back"
            )
        elif message == "6":
            return format_ussd_response(session_id, "Release", f"Active MoMo toggled to {mobile}.")
        else:
            return format_ussd_response(session_id, "Response", f"⚠️ Invalid Choice!\n{get_main_menu_text(mobile)}")

    elif current_step == "SELECT_FEE_CATEGORY":
        if message == "0":
            session["step"] = "MAIN_MENU"
            return format_ussd_response(session_id, "Response", get_main_menu_text(mobile))

        category_map = {
            "1": ("Senior High School", DIRECTORY_CATALOG["senior_high_schools"]),
            "2": ("Nursing & Midwifery College", DIRECTORY_CATALOG["nursing_colleges"]),
            "3": ("Teacher Training College", DIRECTORY_CATALOG["teacher_training_colleges"]),
            "4": ("University / Technical Univ", DIRECTORY_CATALOG["universities"])
        }

        if message in category_map:
            cat_name, cat_list = category_map[message]
            session["data"]["category"] = cat_name
            session["data"]["institution_list"] = cat_list
            session["step"] = "SELECT_INSTITUTION"
            return format_ussd_response(session_id, "Response", build_numbered_menu(cat_name, cat_list))
        else:
            return format_ussd_response(session_id, "Response", "⚠️ Invalid Category!\nSelect 1, 2, 3, or 4.\n\n0. Back")

    elif current_step == "SELECT_INSTITUTION":
        if message == "0":
            session["step"] = "SELECT_FEE_CATEGORY"
            return format_ussd_response(
                session_id, "Response",
                "[Fees Portal]\nSelect Category:\n1. Senior High Schools\n2. Nursing & Midwifery Colleges\n3. Teacher Training Colleges\n4. Universities & Technical Univs\n\n0. Back"
            )

        cat_list = session["data"].get("institution_list", [])
        if message.isdigit():
            idx = int(message) - 1
            if 0 <= idx < len(cat_list):
                selected_inst = cat_list[idx]
                session["data"]["selected_institution"] = selected_inst
                session["step"] = "ENTER_STUDENT_ID"
                return format_ussd_response(
                    session_id, "Response",
                    f"[{selected_inst}]\nEnter Student Reference/ID Number:\n\n0. Back"
                )
        return format_ussd_response(session_id, "Response", f"⚠️ Invalid Choice!\n{build_numbered_menu(session['data']['category'], cat_list)}")

    elif current_step == "ENTER_STUDENT_ID":
        if message == "0":
            session["step"] = "SELECT_INSTITUTION"
            return format_ussd_response(session_id, "Response", build_numbered_menu(session["data"]["category"], session["data"]["institution_list"]))

        if not message:
            return format_ussd_response(session_id, "Response", "⚠️ ID cannot be empty. Enter Student ID:\n\n0. Back")

        session["data"]["student_id"] = message
        inst = session["data"]["selected_institution"]
        session["step"] = "ENTER_TUITION_AMOUNT"
        return format_ussd_response(session_id, "Response", f"[{inst} - ID: {message}]\nEnter Tuition Amount to Remit (GHS):\n\n0. Back")

    elif current_step == "ENTER_TUITION_AMOUNT":
        if message == "0":
            inst = session["data"]["selected_institution"]
            session["step"] = "ENTER_STUDENT_ID"
            return format_ussd_response(session_id, "Response", f"[{inst}]\nEnter Student Reference/ID Number:\n\n0. Back")

        try:
            amount = float(message)
            if amount <= 0:
                raise ValueError()
        except ValueError:
            return format_ussd_response(session_id, "Response", "⚠️ Invalid Amount. Enter positive numeric figure:\n\n0. Back")

        inst = session["data"]["selected_institution"]
        student_id = session["data"]["student_id"]
        
        success = trigger_paystack_direct_charge(
            phone_number=mobile,
            amount_ghs=amount,
            description=f"Tuition Remittance to {inst} (Student ID: {student_id})"
        )

        del user_sessions[session_id]

        if success:
            return format_ussd_response(
                session_id, "Release",
                f"✅ Payment Prompt Dispatched!\nCheck target phone ({mobile}) and authorize GHS {amount:.2f} to complete tuition payment for {inst}."
            )
        else:
            return format_ussd_response(
                session_id, "Release",
                f"❌ Gateway Error: Failed to trigger MoMo charge prompt. Please try again."
            )

    if session_id in user_sessions:
        del user_sessions[session_id]
    return format_ussd_response(session_id, "Release", "Session Ended.")

# ----------------------------------------------------
# RESTFUL APIS (For direct App / Web Client calls)
# ----------------------------------------------------
@app.post("/api/buy-airtime")
def buy_airtime(payload: AirtimePurchaseRequest):
    success = trigger_paystack_direct_charge(
        phone_number=payload.momo_number,
        amount_ghs=payload.amount,
        description=f"Airtime topup for {payload.recipient_number} ({payload.network})"
    )
    if success:
        return {
            "status": "success",
            "message": f"Prompt sent to {payload.momo_number}. Enter MoMo PIN to complete GHS {payload.amount:.2f} Airtime top-up for {payload.recipient_number}."
        }
    return {"status": "error", "message": "Failed to initiate payment authorization prompt."}

@app.post("/api/buy-data")
def buy_data(payload: DataPurchaseRequest):
    success = trigger_paystack_direct_charge(
        phone_number=payload.momo_number,
        amount_ghs=payload.amount,
        description=f"{payload.package_name} Data bundle for {payload.recipient_number}"
    )
    if success:
        return {
            "status": "success",
            "message": f"Prompt sent to {payload.momo_number}. Enter MoMo PIN to activate {payload.package_name} Data bundle."
        }
    return {"status": "error", "message": "Failed to initiate payment authorization prompt."}

@app.post("/api/buy-prepaid")
def buy_prepaid(payload: PrepaidPurchaseRequest):
    success = trigger_paystack_direct_charge(
        phone_number=payload.momo_number,
        amount_ghs=payload.amount,
        description=f"Solar power token for Meter #{payload.meter_number}"
    )
    if success:
        return {
            "status": "success",
            "message": f"Prompt sent to {payload.momo_number}. Enter MoMo PIN to dispatch GHS {payload.amount:.2f} token to Meter #{payload.meter_number}."
        }
    return {"status": "error", "message": "Failed to initiate payment authorization prompt."}

@app.post("/api/pay-utility")
def pay_utility(payload: UtilityPaymentRequest):
    success = trigger_paystack_direct_charge(
        phone_number=payload.momo_number,
        amount_ghs=payload.amount,
        description=f"{payload.provider} Bill Payment for Account #{payload.account_id}"
    )
    if success:
        return {
            "status": "success",
            "message": f"Prompt sent to {payload.momo_number}. Enter MoMo PIN to clear GHS {payload.amount:.2f} {payload.provider} bill."
        }
    return {"status": "error", "message": "Failed to initiate payment authorization prompt."}

@app.post("/api/pay-fees")
def pay_fees(payload: InstitutionalFeesRequest):
    success = trigger_paystack_direct_charge(
        phone_number=payload.momo_number,
        amount_ghs=payload.amount,
        description=f"Tuition Remittance to {payload.institution_name} (Student ID: {payload.student_id})"
    )
    if success:
        return {
            "status": "success",
            "message": f"Prompt sent to {payload.momo_number}. Enter MoMo PIN to remit GHS {payload.amount:.2f} tuition to {payload.institution_name}."
        }
    return {"status": "error", "message": "Failed to initiate payment authorization prompt."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)