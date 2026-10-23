"""Quick demo check. Usage: python smoke_test.py [base_url] [sample_image] [sample_form.pdf]"""
import sys, requests
base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
img = sys.argv[2] if len(sys.argv) > 2 else None
pdf = sys.argv[3] if len(sys.argv) > 3 else None

print("health:", requests.get(f"{base}/api/health", timeout=30).json())
print("checklist:", requests.post(f"{base}/api/checklist",
      json={"service": "PAN card application", "language": "en"}, timeout=90).json()["service"])
if img:
    r = requests.post(f"{base}/api/preprocess", files={"file": open(img, "rb")},
                      data={"min_kb": 50, "max_kb": 300}, timeout=90).json()
    print("preprocess:", {k: r[k] for k in ("rotated_degrees_clockwise", "original_kb", "final_kb", "warning")})
if pdf:
    r = requests.post(f"{base}/api/analyze-form", files={"file": open(pdf, "rb")},
                      data={"language": "en"}, timeout=120).json()
    sid = r["session_id"]; print("form:", r["analysis"]["form_title"])
    print("chat:", requests.post(f"{base}/api/chat", json={"session_id": sid,
          "message": "What do I need for address proof?"}, timeout=90).json()["reply"][:200])
