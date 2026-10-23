"""
Government Form & Document Guide - FastAPI backend.
Endpoints: /api/analyze-form, /api/chat, /api/checklist, /api/preprocess, /api/validate
Run: uvicorn main:app --reload --port 8000
"""
import base64, io, json, os, uuid
from typing import List, Optional

import cv2, fitz  # fitz = PyMuPDF
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from PIL import Image, ImageOps
from pydantic import BaseModel

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY missing. Copy .env.example to .env and set it.")
client = genai.Client(api_key=API_KEY)

app = FastAPI(title="Gov Form Guide API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"], allow_headers=["*"],
)

MAX_UPLOAD_MB = 15
LANGS = {"en": "English", "hi": "Hindi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu",
         "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada", "pa": "Punjabi", "ur": "Urdu"}

# In-memory session store (hackathon only; use Redis/DB in production).
SESSIONS: dict = {}


# ---------- Schemas (also used as Gemini response_schema) ----------
class FormField(BaseModel):
    label: str
    explanation: str          # plain-language help
    required: bool

class RequiredDoc(BaseModel):
    name: str
    purpose: str
    accepted_examples: List[str]

class FormAnalysis(BaseModel):
    form_title: str
    summary: str
    eligibility: List[str]
    fields: List[FormField]
    required_documents: List[RequiredDoc]
    common_rejection_reasons: List[str]

class ChecklistStep(BaseModel):
    title: str
    detail: str
    documents: List[str]

class Checklist(BaseModel):
    service: str
    steps: List[ChecklistStep]

class RotationResult(BaseModel):
    clockwise_degrees: int    # 0, 90, 180 or 270 needed to make text upright

class ValidationResult(BaseModel):
    document_type_detected: str
    matches_expected: bool
    readable: bool
    fields_found: List[str]
    fields_missing: List[str]
    issues: List[str]
    advice: str

class ChatIn(BaseModel):
    session_id: str
    message: str
    language: str = "en"
    history: List[dict] = []  # [{"role": "user"|"model", "text": "..."}]

class ChecklistIn(BaseModel):
    session_id: Optional[str] = None
    service: Optional[str] = None
    language: str = "en"


# ---------- Helpers ----------
def lang_name(code: str) -> str:
    return LANGS.get(code, "English")

async def read_upload(file: UploadFile, allowed: tuple) -> tuple:
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB}MB")
    mime = file.content_type or ""
    if mime not in allowed:
        raise HTTPException(415, f"Unsupported type {mime}. Allowed: {', '.join(allowed)}")
    return data, mime

def gemini_json(contents, schema, system: str):
    """Call Gemini with structured JSON output; returns parsed dict."""
    try:
        resp = client.models.generate_content(
            model=MODEL, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system, response_mime_type="application/json",
                response_schema=schema, temperature=0.2))
        return json.loads(resp.text)
    except Exception as e:
        raise HTTPException(502, f"AI service error: {e}")

def pdf_text_preview(data: bytes) -> str:
    """Extract embedded text with PyMuPDF (empty for scanned PDFs; Gemini still reads visually)."""
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(p.get_text() for p in doc)[:20000]
    except Exception:
        return ""


# ---------- 1. Form analysis ----------
@app.post("/api/analyze-form")
async def analyze_form(file: UploadFile = File(...), language: str = Form("en")):
    data, mime = await read_upload(file, ("application/pdf", "image/jpeg", "image/png", "image/webp"))
    system = (f"You are an expert on Indian government procedures. Analyse the form. Write ALL "
              f"explanations in simple {lang_name(language)} a first-time citizen can follow. "
              "List every field, eligibility rule, and the supporting documents needed. Do not invent info "
              "not implied by the form; if unsure, say so.")
    part = types.Part.from_bytes(data=data, mime_type=mime)
    analysis = gemini_json([part, "Analyse this government form."], FormAnalysis, system)
    sid = uuid.uuid4().hex
    SESSIONS[sid] = {"bytes": data, "mime": mime, "analysis": analysis,
                     "text": pdf_text_preview(data) if mime == "application/pdf" else ""}
    return {"session_id": sid, "analysis": analysis}


# ---------- 2. Chatbot grounded in the uploaded form ----------
@app.post("/api/chat")
async def chat(body: ChatIn):
    s = SESSIONS.get(body.session_id)
    if not s:
        raise HTTPException(404, "Session expired. Please re-upload the form.")
    system = (f"You are a friendly government-form assistant. Answer ONLY using the attached form and "
              f"its analysis; if the answer is not there, say so and suggest the issuing office. "
              f"Reply in simple {lang_name(body.language)}, short and step-by-step. "
              f"Analysis JSON: {json.dumps(s['analysis'], ensure_ascii=False)[:12000]}")
    contents = [types.Content(role="user", parts=[types.Part.from_bytes(data=s["bytes"], mime_type=s["mime"])])]
    for h in body.history[-10:]:
        role = "user" if h.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=str(h.get("text", "")))]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=body.message)]))
    try:
        resp = client.models.generate_content(
            model=MODEL, contents=contents,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.3))
        return {"reply": resp.text}
    except Exception as e:
        raise HTTPException(502, f"AI service error: {e}")


# ---------- 3. Checklist (from uploaded form OR a named service) ----------
@app.post("/api/checklist")
async def checklist(body: ChecklistIn):
    if body.session_id and body.session_id in SESSIONS:
        ctx = "Form analysis: " + json.dumps(SESSIONS[body.session_id]["analysis"], ensure_ascii=False)[:12000]
    elif body.service:
        ctx = f"Government service: {body.service} (India). Use your general knowledge; flag that rules may vary by state."
    else:
        raise HTTPException(400, "Provide session_id or service")
    system = (f"Create an ordered, practical step-by-step checklist (6-10 steps) to complete this procedure, "
              f"including document prep (size/format limits if known), submission and tracking. "
              f"Write in simple {lang_name(body.language)}.")
    return gemini_json([ctx], Checklist, system)


# ---------- 4. Smart pre-processor: auto-rotate + compress ----------
def detect_rotation(img: Image.Image) -> int:
    """Ask Gemini Vision how far to rotate clockwise to make text upright. Falls back to 0."""
    thumb = img.copy(); thumb.thumbnail((768, 768))
    buf = io.BytesIO(); thumb.convert("RGB").save(buf, "JPEG", quality=70)
    try:
        r = gemini_json(
            [types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
             "How many degrees CLOCKWISE (0, 90, 180 or 270) must this document image be rotated "
             "so the text reads upright and left-to-right?"],
            RotationResult, "You are a document orientation detector. Answer only with the JSON.")
        deg = int(r["clockwise_degrees"]) % 360
        return deg if deg in (0, 90, 180, 270) else 0
    except HTTPException:
        return 0

def jpeg_bytes(img: Image.Image, q: int) -> bytes:
    b = io.BytesIO(); img.save(b, "JPEG", quality=q, optimize=True, progressive=True); return b.getvalue()

def compress_to_target(img: Image.Image, max_kb: int, min_kb: int):
    """Find the highest JPEG quality (binary search) under max_kb; shrink dimensions if even q=25 is too big."""
    img = img.convert("RGB")
    scale = 1.0
    while True:
        work = img if scale == 1.0 else img.resize(
            (int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        lo, hi, best = 25, 95, None
        while lo <= hi:
            mid = (lo + hi) // 2
            data = jpeg_bytes(work, mid)
            if len(data) <= max_kb * 1024:
                best, lo = (data, mid), mid + 1
            else:
                hi = mid - 1
        if best:
            return best[0], best[1], work.size
        scale *= 0.85
        if scale < 0.2:
            raise HTTPException(422, f"Cannot reach {max_kb}KB without destroying legibility")

@app.post("/api/preprocess")
async def preprocess(file: UploadFile = File(...), min_kb: int = Form(50), max_kb: int = Form(300),
                     auto_rotate: bool = Form(True)):
    if not (1 <= min_kb < max_kb <= 5000):
        raise HTTPException(400, "Invalid size range")
    data, _ = await read_upload(file, ("image/jpeg", "image/png", "image/webp"))
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))  # fix camera EXIF orientation first
    except Exception:
        raise HTTPException(400, "Corrupt or unreadable image")
    deg = detect_rotation(img) if auto_rotate else 0
    if deg:
        img = img.rotate(-deg, expand=True)  # PIL rotates counter-clockwise, so negate
    out, quality, size = compress_to_target(img, max_kb, min_kb)
    kb = round(len(out) / 1024, 1)
    note = None if kb >= min_kb else f"File is {kb}KB, below the {min_kb}KB minimum; try a higher-resolution photo."
    return {"image_base64": base64.b64encode(out).decode(), "mime": "image/jpeg",
            "rotated_degrees_clockwise": deg, "original_kb": round(len(data) / 1024, 1),
            "final_kb": kb, "quality": quality, "width": size[0], "height": size[1], "warning": note}


# ---------- 5. Validation: OpenCV blur check + Gemini OCR check ----------
def blur_score(data: bytes) -> float:
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if arr is None:
        raise HTTPException(400, "Unreadable image")
    return float(cv2.Laplacian(arr, cv2.CV_64F).var())  # <100 is typically blurry

EXPECTED = {
    "aadhaar": ["name", "date of birth/year of birth", "gender", "12-digit Aadhaar number", "photo"],
    "pan": ["name", "father's name", "date of birth", "10-character PAN", "photo", "signature"],
    "photo": ["clear frontal face", "plain background", "no heavy shadows"],
}

@app.post("/api/validate")
async def validate(file: UploadFile = File(...), doc_type: str = Form("aadhaar"), language: str = Form("en")):
    if doc_type not in EXPECTED:
        raise HTTPException(400, f"doc_type must be one of {list(EXPECTED)}")
    data, mime = await read_upload(file, ("image/jpeg", "image/png", "image/webp"))
    score = blur_score(data)
    system = (f"You check whether an uploaded {doc_type} image is acceptable for a government portal. "
              f"Expected elements: {EXPECTED[doc_type]}. Judge only legibility/completeness (glare, cropping, "
              f"blur, cut corners). Do NOT repeat personal numbers in your output. Write issues/advice in "
              f"simple {lang_name(language)}.")
    result = gemini_json([types.Part.from_bytes(data=data, mime_type=mime), "Validate this document."],
                         ValidationResult, system)
    result["blur_score"] = round(score, 1)
    result["sharp_enough"] = score >= 100
    result["pass"] = bool(result["readable"] and result["matches_expected"] and result["sharp_enough"])
    return result  # image is never stored

@app.get("/api/health")
def health():
    return {"ok": True, "model": MODEL}
