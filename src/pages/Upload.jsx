import { useState, useCallback, useEffect } from "react";
import { api } from "../api/client";

const ACCEPTED = ".pdf,.docx,.doc,.xlsx,.xls,.pptx,.txt,.csv,.md";

const DOC_CATEGORIES = [
  { value: "project_resources", label: "Project Resources" },
  { value: "personal_schedule", label: "Personal Schedule" },
  { value: "academic_paper",    label: "Academic Paper" },
];

const STAGES = [
  { label: "Parsing Document",          detail: "Extracting text & layout with OCR" },
  { label: "Chunking Content",          detail: "Segmenting into semantic units" },
  { label: "Generating Embeddings",     detail: "Computing neural vector representations" },
  { label: "Storing to Knowledge Base", detail: "Persisting to vector database" },
  { label: "Clustering Projects",       detail: "Discovering project connections" },
];

// Deterministic star field — golden-angle distribution, no random() so render is stable
const STARS = Array.from({ length: 90 }, (_, i) => ({
  x: ((i * 137.508) % 100).toFixed(2),
  y: ((i * 97.312 + 15) % 100).toFixed(2),
  r: [0.5, 0.5, 0.5, 1, 1, 1.5][i % 6],
  delay: ((i * 0.41) % 3.5).toFixed(2),
  dur:   (1.8 + (i % 4) * 0.6).toFixed(1),
  op:    [0.2, 0.3, 0.5, 0.6, 0.8, 1.0][i % 6],
}));

function ProcessingOverlay({ currentFile, totalFiles, doneCount, clustering }) {
  const [animStage, setAnimStage] = useState(0);

  useEffect(() => {
    if (clustering) {
      setAnimStage(4);
      return;
    }
    // Loop stages 0→3 while uploading
    const t = setInterval(() => setAnimStage(s => (s >= 3 ? 0 : s + 1)), 2600);
    return () => clearInterval(t);
  }, [clustering]);

  const progress = totalFiles > 0 ? Math.round((doneCount / totalFiles) * 100) : 0;

  return (
    <>
      <style>{`
        @keyframes twinkle {
          0%,100% { opacity: var(--s-op, 0.4); transform: scale(1); }
          50%      { opacity: 1; transform: scale(1.6); }
        }
        @keyframes orbit {
          from { transform: rotate(0deg)   translateX(28px) rotate(0deg); }
          to   { transform: rotate(360deg) translateX(28px) rotate(-360deg); }
        }
        @keyframes orbit2 {
          from { transform: rotate(120deg)  translateX(28px) rotate(-120deg); }
          to   { transform: rotate(480deg)  translateX(28px) rotate(-480deg); }
        }
        @keyframes orbit3 {
          from { transform: rotate(240deg)  translateX(28px) rotate(-240deg); }
          to   { transform: rotate(600deg)  translateX(28px) rotate(-600deg); }
        }
        @keyframes scan-beam {
          0%   { top: -4px; opacity: 0.9; }
          100% { top: 100%; opacity: 0; }
        }
        @keyframes bar-glow {
          0%,100% { box-shadow: 0 0 6px #6366f180; }
          50%     { box-shadow: 0 0 14px #818cf8, 0 0 28px #6366f140; }
        }
        @keyframes stage-pulse {
          0%,100% { opacity: 1; box-shadow: 0 0 10px #6366f150; }
          50%     { opacity: 0.6; box-shadow: 0 0 4px #6366f120; }
        }
        @keyframes card-in {
          from { opacity: 0; transform: translateY(28px) scale(0.96); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes bg-drift {
          0%   { background-position: 0% 0%; }
          100% { background-position: 100% 100%; }
        }
      `}</style>

      {/* Full-screen backdrop */}
      <div style={{
        position: "fixed", inset: 0, zIndex: 9999,
        background: "radial-gradient(ellipse at 50% 40%, #0d1433 0%, #050810 70%)",
        display: "flex", alignItems: "center", justifyContent: "center",
        userSelect: "none",
      }}>
        {/* Star field */}
        {STARS.map((s, i) => (
          <div key={i} style={{
            position: "absolute",
            left: `${s.x}%`, top: `${s.y}%`,
            width: `${s.r * 2}px`, height: `${s.r * 2}px`,
            borderRadius: "50%",
            background: `rgba(${[180,200,160,255,220,180][i%6]},${[190,220,230,255,200,220][i%6]},255,1)`,
            animation: `twinkle ${s.dur}s ${s.delay}s ease-in-out infinite`,
            '--s-op': s.op,
          }} />
        ))}

        {/* Modal card */}
        <div style={{
          position: "relative",
          background: "linear-gradient(160deg,#0d1433 0%,#111827 60%,#0a0f1e 100%)",
          border: "1px solid #2d3748",
          borderRadius: "22px",
          padding: "44px 52px",
          width: "500px", maxWidth: "92vw",
          animation: "card-in 0.45s cubic-bezier(.22,.68,0,1.2)",
          boxShadow: "0 0 0 1px #6366f115, 0 40px 100px rgba(0,0,0,0.85), 0 0 80px #6366f112",
          overflow: "hidden",
        }}>

          {/* Scan beam */}
          <div style={{
            position: "absolute", left: 0, right: 0, height: "2px",
            background: "linear-gradient(90deg,transparent,#6366f160,#a5b4fc,#6366f160,transparent)",
            animation: "scan-beam 3.5s linear infinite",
            pointerEvents: "none",
          }} />

          {/* Orbital icon */}
          <div style={{ display: "flex", justifyContent: "center", marginBottom: "28px" }}>
            <div style={{ position: "relative", width: "72px", height: "72px" }}>
              {/* Core */}
              <div style={{
                position: "absolute", inset: "16px",
                borderRadius: "50%",
                background: "linear-gradient(135deg,#4338ca,#7c3aed)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "20px",
                boxShadow: "0 0 24px #6366f160",
              }}>🔭</div>
              {/* Orbit dots */}
              {["orbit","orbit2","orbit3"].map((anim, i) => (
                <div key={i} style={{
                  position: "absolute", inset: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <div style={{
                    width: "6px", height: "6px", borderRadius: "50%",
                    background: ["#818cf8","#c084fc","#38bdf8"][i],
                    boxShadow: `0 0 8px ${["#818cf880","#c084fc80","#38bdf880"][i]}`,
                    animation: `${anim} ${[3.2,4.5,2.8][i]}s linear infinite`,
                  }} />
                </div>
              ))}
            </div>
          </div>

          {/* Title */}
          <div style={{ textAlign: "center", marginBottom: "8px" }}>
            <div style={{ color: "#f8fafc", fontSize: "19px", fontWeight: "700", letterSpacing: "0.01em" }}>
              Processing Documents
            </div>
            <div style={{
              color: "#6366f1", fontSize: "13px", marginTop: "6px",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              maxWidth: "340px", margin: "6px auto 0",
            }}>
              {clustering ? "Re-clustering knowledge base…" : (currentFile || "Initialising…")}
            </div>
          </div>

          {/* Progress bar */}
          <div style={{ margin: "24px 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
              <span style={{ color: "#64748b", fontSize: "12px" }}>
                {clustering ? "Clustering" : `File ${Math.min(doneCount + 1, totalFiles)} of ${totalFiles}`}
              </span>
              <span style={{ color: "#818cf8", fontSize: "12px", fontWeight: "600" }}>
                {clustering ? "—" : `${progress}%`}
              </span>
            </div>
            <div style={{
              height: "7px", background: "#1a2035",
              borderRadius: "99px", overflow: "hidden",
              border: "1px solid #2d3748",
            }}>
              <div style={{
                height: "100%",
                width: clustering ? "100%" : `${progress}%`,
                background: "linear-gradient(90deg,#4338ca,#818cf8,#c084fc)",
                borderRadius: "99px",
                transition: "width 0.7s cubic-bezier(.4,0,.2,1)",
                animation: "bar-glow 2s ease-in-out infinite",
              }} />
            </div>
          </div>

          {/* Stage pipeline */}
          <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "28px" }}>
            {STAGES.map((stage, idx) => {
              const done   = idx < animStage;
              const active = idx === animStage;
              return (
                <div key={idx} style={{
                  display: "flex", alignItems: "center", gap: "12px",
                  padding: "10px 14px", borderRadius: "12px",
                  background: active ? "#151f35" : "transparent",
                  border: `1px solid ${active ? "#334155" : "transparent"}`,
                  transition: "all 0.35s ease",
                  opacity: done ? 0.45 : active ? 1 : 0.25,
                }}>
                  {/* Indicator dot */}
                  <div style={{
                    width: "28px", height: "28px", borderRadius: "50%", flexShrink: 0,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: "12px", fontWeight: "700",
                    background: done
                      ? "linear-gradient(135deg,#065f46,#059669)"
                      : active
                        ? "linear-gradient(135deg,#4338ca,#7c3aed)"
                        : "#1e293b",
                    border: active ? "1px solid #6366f180" : "1px solid #334155",
                    animation: active ? "stage-pulse 1.4s ease-in-out infinite" : "none",
                    color: done ? "#34d399" : active ? "#e0e7ff" : "#475569",
                  }}>
                    {done ? "✓" : active ? "◈" : "○"}
                  </div>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: "13px", fontWeight: active ? "600" : "400",
                      color: done ? "#34d399" : active ? "#f1f5f9" : "#475569",
                      transition: "color 0.3s",
                    }}>{stage.label}</div>
                    {active && (
                      <div style={{ color: "#818cf8", fontSize: "11px", marginTop: "3px" }}>
                        {stage.detail}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Footer warning */}
          <div style={{
            display: "flex", alignItems: "center", gap: "8px",
            background: "#0f172a", borderRadius: "10px",
            padding: "10px 14px", border: "1px solid #1e293b",
          }}>
            <span style={{ fontSize: "14px" }}>⚠</span>
            <span style={{ color: "#475569", fontSize: "12px" }}>
              Do not navigate away — processing is in progress
            </span>
          </div>
        </div>
      </div>
    </>
  );
}

export default function Upload() {
  const [files, setFiles]           = useState([]);
  const [statuses, setStatuses]     = useState({});
  const [errorMsgs, setErrorMsgs]   = useState({});
  const [categories, setCategories] = useState({});
  const [dragging, setDragging]     = useState(false);
  const [clusterStatus, setClusterStatus] = useState(null);
  const [processing, setProcessing] = useState({
    active: false, currentFile: "", total: 0, done: 0, clustering: false,
  });

  const handleFiles = (incoming) => {
    const next = Array.from(incoming);
    setFiles(f => [...f, ...next]);
    setCategories(c => {
      const upd = { ...c };
      next.forEach(f => { if (!upd[f.name]) upd[f.name] = "project_resources"; });
      return upd;
    });
  };

  const setCategory = (name, value) =>
    setCategories(c => ({ ...c, [name]: value }));

  const uploadAll = async () => {
    const pending = files.filter(f => statuses[f.name] !== "done");
    if (!pending.length) return;

    setClusterStatus(null);
    setProcessing({ active: true, currentFile: pending[0]?.name, total: pending.length, done: 0, clustering: false });

    let anySucceeded = false;
    for (let i = 0; i < pending.length; i++) {
      const file = pending[i];
      setStatuses(s => ({ ...s, [file.name]: "uploading" }));
      setProcessing(p => ({ ...p, currentFile: file.name, done: i }));
      try {
        await api.uploadFile(file, categories[file.name] || "project_resources");
        setStatuses(s => ({ ...s, [file.name]: "done" }));
        anySucceeded = true;
      } catch (e) {
        const msg = e?.detail || e?.message || "Upload failed";
        setStatuses(s => ({ ...s, [file.name]: "error" }));
        setErrorMsgs(m => ({ ...m, [file.name]: msg }));
      }
    }

    setProcessing(p => ({ ...p, done: pending.length }));

    if (anySucceeded) {
      setClusterStatus("clustering");
      setProcessing(p => ({ ...p, clustering: true }));
      try {
        await api.recluster();
        localStorage.removeItem("cached_projects");
        setClusterStatus("done");
      } catch {
        setClusterStatus("error");
      }
    }

    setProcessing({ active: false, currentFile: "", total: 0, done: 0, clustering: false });
  };

  const onDrop = useCallback(e => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }, []);

  return (
    <>
      {processing.active && (
        <ProcessingOverlay
          currentFile={processing.currentFile}
          totalFiles={processing.total}
          doneCount={processing.done}
          clustering={processing.clustering}
        />
      )}
      <div style={S.container}>
        <h2 style={S.heading}>Upload Documents</h2>
        <p style={S.sub}>Supported: PDF, DOCX, XLSX, PPTX, TXT, CSV, MD</p>

        <div
          style={{ ...S.dropzone, ...(dragging ? S.dragging : {}) }}
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => document.getElementById("fileInput").click()}
        >
          <p style={S.dropText}>📂 Drop files here or click to browse</p>
          <input id="fileInput" type="file" multiple accept={ACCEPTED}
            style={{ display: "none" }} onChange={e => handleFiles(e.target.files)} />
        </div>

        {files.length > 0 && (
          <>
            <div style={S.fileList}>
              {files.map((f, i) => (
                <div key={i} style={{ ...S.fileItem, flexWrap: "wrap" }}>
                  <span style={S.fileName}>{f.name}</span>
                  <select
                    value={categories[f.name] || "project_resources"}
                    onChange={e => setCategory(f.name, e.target.value)}
                    disabled={statuses[f.name] === "done"}
                    style={S.categorySelect}
                  >
                    {DOC_CATEGORIES.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                  <span style={{ ...S.statusLabel, color: statusColor(statuses[f.name]) }}>
                    {statusText(statuses[f.name])}
                  </span>
                  {statuses[f.name] === "error" && errorMsgs[f.name] && (
                    <span style={S.errorDetail}>{errorMsgs[f.name]}</span>
                  )}
                </div>
              ))}
            </div>

            <button
              style={{ ...S.uploadBtn, opacity: processing.active ? 0.5 : 1, cursor: processing.active ? "not-allowed" : "pointer" }}
              onClick={uploadAll}
              disabled={processing.active}
            >
              Upload All
            </button>

            {clusterStatus === "done" && (
              <p style={{ ...S.clusterMsg, color: "#4ade80" }}>
                ✓ Projects updated — switch to the Projects tab to view.
              </p>
            )}
            {clusterStatus === "error" && (
              <p style={{ ...S.clusterMsg, color: "#f87171" }}>
                Uploads done, but clustering failed. Use Re-cluster in Projects tab.
              </p>
            )}
          </>
        )}
      </div>
    </>
  );
}

function statusText(s) {
  if (!s)                return "Pending";
  if (s === "uploading") return "⏳ Uploading…";
  if (s === "done")      return "✅ Done";
  if (s === "error")     return "❌ Error";
}
function statusColor(s) {
  if (s === "done")  return "#4ade80";
  if (s === "error") return "#f87171";
  return "#94a3b8";
}

const S = {
  container:      { maxWidth: "700px" },
  heading:        { color: "#f8fafc", marginTop: 0 },
  sub:            { color: "#94a3b8", fontSize: "14px" },
  dropzone:       { border: "2px dashed #334155", borderRadius: "12px", padding: "48px", textAlign: "center", cursor: "pointer", transition: "all 0.2s" },
  dragging:       { borderColor: "#6366f1", background: "#1e293b" },
  dropText:       { color: "#94a3b8", margin: 0 },
  fileList:       { marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" },
  fileItem:       { display: "flex", alignItems: "center", gap: "12px", background: "#1e293b", padding: "12px 16px", borderRadius: "8px" },
  fileName:       { color: "#e2e8f0", fontSize: "14px", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  categorySelect: { background: "#0f172a", color: "#94a3b8", border: "1px solid #334155", borderRadius: "6px", padding: "4px 8px", fontSize: "13px", cursor: "pointer" },
  statusLabel:    { fontSize: "13px", whiteSpace: "nowrap" },
  uploadBtn:      { marginTop: "16px", padding: "12px 32px", background: "linear-gradient(135deg,#4338ca,#6366f1)", color: "white", border: "none", borderRadius: "8px", fontWeight: "bold", fontSize: "15px", boxShadow: "0 4px 16px #6366f130" },
  clusterMsg:     { marginTop: "12px", fontSize: "13px", color: "#94a3b8" },
  errorDetail:    { width: "100%", fontSize: "12px", color: "#fca5a5", paddingLeft: "4px", marginTop: "2px" },
};
