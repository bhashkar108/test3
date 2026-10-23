// Single-file React UI (Vite + Tailwind). Components: Upload, Checklist, Chat, ImageFix, Validate.
import { useState, useRef } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
const LANGS = { en: ["English", "en-IN"], hi: ["हिन्दी", "hi-IN"], bn: ["বাংলা", "bn-IN"], ta: ["தமிழ்", "ta-IN"],
  te: ["తెలుగు", "te-IN"], mr: ["मराठी", "mr-IN"], gu: ["ગુજરાતી", "gu-IN"], kn: ["ಕನ್ನಡ", "kn-IN"] };

// fetch wrapper with error surfacing
async function api(path, opts) {
  const r = await fetch(API + path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `Request failed (${r.status})`);
  return j;
}
const form = (obj) => { const f = new FormData(); Object.entries(obj).forEach(([k, v]) => f.append(k, v)); return f; };
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// Browser text-to-speech (free, works offline for installed voices)
const speak = (text, lang) => {
  if (!("speechSynthesis" in window)) return alert("Speech not supported in this browser");
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text); u.lang = LANGS[lang][1]; speechSynthesis.speak(u);
};

const Btn = ({ children, ...p }) => (
  <button {...p} className={"rounded-lg bg-indigo-600 px-4 py-2 text-white font-medium disabled:opacity-50 hover:bg-indigo-700 " + (p.className || "")}>{children}</button>
);
const Card = ({ title, children }) => (
  <section className="rounded-xl bg-white p-4 shadow-sm border">{title && <h3 className="font-semibold mb-2">{title}</h3>}{children}</section>
);
const Err = ({ msg }) => msg ? <p className="text-red-600 text-sm mt-2">⚠ {msg}</p> : null;

function UploadTab({ lang, onDone }) {
  const [busy, setBusy] = useState(false), [err, setErr] = useState(""), [data, setData] = useState(null);
  const go = async (file) => {
    if (!file) return; setBusy(true); setErr("");
    try { const r = await api("/api/analyze-form", { method: "POST", body: form({ file, language: lang }) });
      setData(r.analysis); onDone(r.session_id); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (<div className="space-y-4">
    <Card title="Upload your government form (PDF / image)">
      <input type="file" accept="application/pdf,image/*" onChange={(e) => go(e.target.files[0])} />
      {busy && <p className="mt-2 animate-pulse">Reading your form…</p>}<Err msg={err} />
    </Card>
    {data && <>
      <Card title={data.form_title}><p>{data.summary}</p>
        <Btn className="mt-2" onClick={() => speak(data.summary, lang)}>🔊 Listen</Btn></Card>
      <Card title="Required documents"><ul className="list-disc pl-5">{data.required_documents.map((d, i) =>
        <li key={i}><b>{d.name}</b> – {d.purpose} <i className="text-gray-500">({d.accepted_examples.join(", ")})</i></li>)}</ul></Card>
      <Card title="Eligibility"><ul className="list-disc pl-5">{data.eligibility.map((e, i) => <li key={i}>{e}</li>)}</ul></Card>
      <Card title="Fields explained"><ul className="space-y-1">{data.fields.map((f, i) =>
        <li key={i}><b>{f.label}</b>{f.required && <span className="text-red-500"> *</span>}: {f.explanation}</li>)}</ul></Card>
      <Card title="Common rejection reasons"><ul className="list-disc pl-5">{data.common_rejection_reasons.map((e, i) => <li key={i}>{e}</li>)}</ul></Card>
    </>}
  </div>);
}

function ChecklistTab({ lang, sid }) {
  const [service, setService] = useState(""), [list, setList] = useState(null), [done, setDone] = useState({}), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const gen = async (useForm) => {
    setBusy(true); setErr("");
    try { setList(await post("/api/checklist", { language: lang, ...(useForm ? { session_id: sid } : { service }) })); setDone({}); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const pct = list ? Math.round((Object.values(done).filter(Boolean).length / list.steps.length) * 100) : 0;
  return (<div className="space-y-4">
    <Card title="Generate checklist">
      <div className="flex gap-2 flex-wrap">
        <input className="border rounded px-3 py-2 flex-1 min-w-[200px]" placeholder="e.g. Passport renewal, Ration card" value={service} onChange={(e) => setService(e.target.value)} />
        <Btn disabled={!service || busy} onClick={() => gen(false)}>From service</Btn>
        <Btn disabled={!sid || busy} onClick={() => gen(true)}>From uploaded form</Btn>
      </div>{busy && <p className="mt-2 animate-pulse">Building…</p>}<Err msg={err} />
    </Card>
    {list && <Card title={list.service}>
      <div className="h-2 bg-gray-200 rounded mb-3"><div className="h-2 bg-green-500 rounded transition-all" style={{ width: pct + "%" }} /></div>
      <ol className="space-y-3">{list.steps.map((s, i) => (
        <li key={i} className="flex gap-3"><input type="checkbox" className="mt-1 h-5 w-5" checked={!!done[i]} onChange={() => setDone({ ...done, [i]: !done[i] })} />
          <div className={done[i] ? "opacity-50 line-through" : ""}><b>{i + 1}. {s.title}</b><p>{s.detail}</p>
            {s.documents.length > 0 && <p className="text-sm text-indigo-700">📎 {s.documents.join(", ")}</p>}</div></li>))}</ol>
    </Card>}
  </div>);
}

function ChatTab({ lang, sid }) {
  const [msgs, setMsgs] = useState([]), [q, setQ] = useState(""), [busy, setBusy] = useState(false);
  const send = async () => {
    if (!q.trim()) return; const history = msgs.map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { role: "user", text: q }]); setQ(""); setBusy(true);
    try { const r = await post("/api/chat", { session_id: sid, message: q, language: lang, history });
      setMsgs((m) => [...m, { role: "model", text: r.reply }]); }
    catch (e) { setMsgs((m) => [...m, { role: "model", text: "⚠ " + e.message }]); } finally { setBusy(false); }
  };
  if (!sid) return <Card>Upload a form first to chat about it.</Card>;
  return (<Card title="Ask about your form">
    <div className="h-80 overflow-y-auto space-y-2 mb-3">{msgs.map((m, i) => (
      <div key={i} className={"max-w-[85%] rounded-lg px-3 py-2 whitespace-pre-wrap " + (m.role === "user" ? "ml-auto bg-indigo-600 text-white" : "bg-gray-100")}>
        {m.text}{m.role === "model" && <button className="ml-2" onClick={() => speak(m.text, lang)}>🔊</button>}</div>))}
      {busy && <p className="animate-pulse text-gray-500">Thinking…</p>}</div>
    <div className="flex gap-2"><input className="border rounded px-3 py-2 flex-1" value={q} placeholder="What document do I need for address proof?"
      onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} /><Btn onClick={send} disabled={busy}>Send</Btn></div>
  </Card>);
}

function ImageFixTab() {
  const [file, setFile] = useState(null), [min, setMin] = useState(50), [max, setMax] = useState(300), [res, setRes] = useState(null), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setErr(""); setRes(null);
    try { setRes(await api("/api/preprocess", { method: "POST", body: form({ file, min_kb: min, max_kb: max }) })); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const fixed = res && `data:${res.mime};base64,${res.image_base64}`;
  return (<Card title="Auto-rotate & resize document photo">
    <input type="file" accept="image/*" onChange={(e) => { setFile(e.target.files[0]); setRes(null); }} />
    <div className="flex gap-3 my-3 items-center">Target
      <input type="number" className="border w-20 px-2 py-1 rounded" value={min} onChange={(e) => setMin(e.target.value)} /> –
      <input type="number" className="border w-20 px-2 py-1 rounded" value={max} onChange={(e) => setMax(e.target.value)} /> KB
      <Btn disabled={!file || busy} onClick={run}>{busy ? "Fixing…" : "Auto-fix"}</Btn></div><Err msg={err} />
    {file && <div className="grid md:grid-cols-2 gap-4">
      <div><p className="text-sm font-medium">Before ({(file.size / 1024).toFixed(0)} KB)</p><img src={URL.createObjectURL(file)} className="border rounded max-h-80" /></div>
      {res && <div><p className="text-sm font-medium">After ({res.final_kb} KB, rotated {res.rotated_degrees_clockwise}°)</p>
        <img src={fixed} className="border rounded max-h-80" />
        {res.warning && <p className="text-amber-600 text-sm">{res.warning}</p>}
        <a download="fixed-document.jpg" href={fixed}><Btn className="mt-2">⬇ Download</Btn></a></div>}</div>}
  </Card>);
}

function ValidateTab({ lang }) {
  const [file, setFile] = useState(null), [type, setType] = useState("aadhaar"), [r, setR] = useState(null), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); setErr(""); setR(null);
    try { setR(await api("/api/validate", { method: "POST", body: form({ file, doc_type: type, language: lang }) })); }
    catch (e) { setErr(e.message); } finally { setBusy(false); } };
  return (<Card title="Check document clarity before submitting">
    <div className="flex gap-2 flex-wrap items-center">
      <select className="border rounded px-2 py-2" value={type} onChange={(e) => setType(e.target.value)}>
        <option value="aadhaar">Aadhaar</option><option value="pan">PAN</option><option value="photo">Passport photo</option></select>
      <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files[0])} />
      <Btn disabled={!file || busy} onClick={run}>{busy ? "Checking…" : "Validate"}</Btn></div><Err msg={err} />
    {r && <div className="mt-3 space-y-1">
      <p className={"text-lg font-semibold " + (r.pass ? "text-green-600" : "text-red-600")}>{r.pass ? "✅ Looks good to submit" : "❌ Needs fixing"}</p>
      <p>Detected: {r.document_type_detected} · Sharpness score {r.blur_score} {r.sharp_enough ? "(OK)" : "(blurry)"}</p>
      {r.fields_missing.length > 0 && <p>Missing/unreadable: {r.fields_missing.join(", ")}</p>}
      <ul className="list-disc pl-5">{r.issues.map((x, i) => <li key={i}>{x}</li>)}</ul><p className="italic">{r.advice}</p></div>}
  </Card>);
}

export default function App() {
  const [tab, setTab] = useState("upload"), [lang, setLang] = useState("en"), [sid, setSid] = useState(null);
  const tabs = { upload: "📄 Form", checklist: "✅ Checklist", chat: "💬 Chat", fix: "🖼 Image Fix", validate: "🔍 Validate" };
  return (<div className="min-h-screen bg-gray-50"><div className="max-w-3xl mx-auto p-4 space-y-4">
    <header className="flex justify-between items-center flex-wrap gap-2">
      <h1 className="text-xl font-bold">Gov Form Guide</h1>
      <select className="border rounded px-2 py-1" value={lang} onChange={(e) => setLang(e.target.value)}>
        {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v[0]}</option>)}</select></header>
    <nav className="flex gap-1 overflow-x-auto">{Object.entries(tabs).map(([k, v]) => (
      <button key={k} onClick={() => setTab(k)} className={"px-3 py-2 rounded-lg whitespace-nowrap " + (tab === k ? "bg-indigo-600 text-white" : "bg-white border")}>{v}</button>))}</nav>
    {tab === "upload" && <UploadTab lang={lang} onDone={setSid} />}
    {tab === "checklist" && <ChecklistTab lang={lang} sid={sid} />}
    {tab === "chat" && <ChatTab lang={lang} sid={sid} />}
    {tab === "fix" && <ImageFixTab />}
    {tab === "validate" && <ValidateTab lang={lang} />}
  </div></div>);
}
