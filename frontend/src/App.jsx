import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

let mermaidRenderCounter = 0;

function MermaidDiagram({ chart }) {
  const containerRef = useRef(null);
  const [renderError, setRenderError] = useState("");
  const [svgMarkup, setSvgMarkup] = useState("");

  useEffect(() => {
    let cancelled = false;

    const renderDiagram = async () => {
      if (!containerRef.current || !chart) return;

      setRenderError("");
      setSvgMarkup("");
      containerRef.current.innerHTML = "";

      // The backend may return plain Mermaid or a fenced ```mermaid block.
      const source = chart
        .replace(/^\s*```mermaid\s*/i, "")
        .replace(/\s*```\s*$/i, "")
        .trim();

      try {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "default",
          flowchart: {
            useMaxWidth: true,
            htmlLabels: true,
            curve: "basis",
          },
        });

        const renderId = `codelens-mermaid-${++mermaidRenderCounter}`;
        const { svg, bindFunctions } = await mermaid.render(renderId, source);

        if (cancelled || !containerRef.current) return;

        containerRef.current.innerHTML = svg;
        setSvgMarkup(svg);
        bindFunctions?.(containerRef.current);
      } catch (error) {
        if (cancelled) return;
        console.error("Mermaid render failed:", error);
        setRenderError(error?.message || "Unable to render Mermaid diagram.");
      }
    };

    renderDiagram();

    return () => {
      cancelled = true;
    };
  }, [chart]);

  const downloadSvg = () => {
    if (!svgMarkup) return;
    const blob = new Blob([svgMarkup], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "architecture-diagram.svg";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="mermaid-section">
      <div className="documentation-preview mermaid-card">
        <div className="mermaid-header-row">
          <div>
            <h3>Architecture Flow Diagram</h3>
            <p>Generated from the project's detected file relationships as a scalable SVG.</p>
          </div>
          <button
            className="browse-btn mermaid-download-btn"
            onClick={downloadSvg}
            disabled={!svgMarkup}
            title="Download the rendered Mermaid graph as an SVG file"
          >
            ↓ Download SVG
          </button>
        </div>
        {renderError ? (
          <div className="error-banner" style={{ marginTop: "12px" }}>
            Mermaid renderer error: {renderError}
          </div>
        ) : (
          <div className="mermaid-svg-viewport">
            <div ref={containerRef} className="mermaid-renderer" aria-label="Architecture flow diagram" />
          </div>
        )}
      </div>
    </div>
  );
}

// Renders the structured render/import tree returned by /generate-diagram.
// Plain JSX (React escapes all text), so untrusted file names cannot inject markup.
function TreeNode({ node }) {
  return (
    <li>
      <span className="tree-path">{node.path}</span>
      {node.via && <span className="tree-via">{node.via}</span>}
      {node.repeat && <span className="tree-via">see above</span>}
      {node.children && node.children.length > 0 && (
        <ul className="tree-list">
          {node.children.map((child, idx) => (
            <TreeNode key={`${child.path}-${idx}`} node={child} />
          ))}
        </ul>
      )}
    </li>
  );
}

function RelationList({ title, items, onSelect }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="insight-card">
      <h4>{title}</h4>
      <ul className="relation-list">
        {items.map((item, idx) => (
          <li key={`${item.path}-${idx}`}>
            <button type="button" className="link-btn" onClick={() => onSelect(item.path)}>
              {item.path}
            </button>
            <span className="tree-via">{item.relation}</span>
            {item.confidence === "inferred" && <span className="badge badge-warn">inferred</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function App() {
  const fileInputRef = useRef(null);
  // Tracks the project the UI is currently showing, so responses that arrive
  // after the user switched projects are discarded instead of shown.
  const activeProjectRef = useRef(null);

  const [activePage, setActivePage] = useState("Dashboard");
  const [selectedFile, setSelectedFile] = useState(null);
  const [githubUrl, setGithubUrl] = useState("");
  const [projectId, setProjectId] = useState(null);
  const [projectData, setProjectData] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  // Code Analysis State
  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [explainLevel, setExplainLevel] = useState("developer");
  const [explanationResult, setExplanationResult] = useState(null);
  const [explaining, setExplaining] = useState(false);

  // Docs State
  const [docKind, setDocKind] = useState("readme");
  const [docContent, setDocContent] = useState("");
  const [generatingDocs, setGeneratingDocs] = useState(false);

  // Diagram State
  const [diagramMermaid, setDiagramMermaid] = useState("");
  const [generatingDiagram, setGeneratingDiagram] = useState(false);

  // Ask Q&A State
  const [question, setQuestion] = useState("");
  const [qaAnswer, setQaAnswer] = useState(null);
  const [asking, setAsking] = useState(false);

  // History State
  const [overview, setOverview] = useState(null);
  const [diagramData, setDiagramData] = useState(null);

  // Change Impact + Safe Refactor
  const [impactResult, setImpactResult] = useState(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [refactorDescription, setRefactorDescription] = useState("");
  const [refactorResult, setRefactorResult] = useState(null);
  const [refactorLoading, setRefactorLoading] = useState(false);

  const [historyList, setHistoryList] = useState([]);
  // Starts true: the first history fetch is triggered by the effect below.
  const [loadingHistory, setLoadingHistory] = useState(true);

  const menuItems = [
    { name: "Dashboard", icon: "⌂" },
    { name: "Upload Code", icon: "↑" },
    { name: "Code Analysis", icon: "⌘" },
    { name: "Documentation", icon: "▤" },
    { name: "Architecture", icon: "◇" },
    { name: "Ask Codebase", icon: "✦" },
    { name: "Change Impact", icon: "⚡" },
    { name: "Safe Refactor", icon: "🛡" },
    { name: "History", icon: "◷" },
  ];

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/history`);
      if (res.ok) {
        const data = await res.json();
        setHistoryList(data.projects || []);
      }
    } catch (err) {
      console.error("Failed to fetch history:", err);
    } finally {
      setLoadingHistory(false);
    }
  };

  // Refresh history whenever the active page changes (History and Dashboard show it).
  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/history`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) setHistoryList(data.projects || []);
      })
      .catch((err) => console.error("Failed to fetch history:", err))
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activePage]);

  // Clears everything that belongs to the previously shown project.
  const resetProjectState = () => {
    setExplanationResult(null);
    setDocContent("");
    setDiagramMermaid("");
    setDiagramData(null);
    setQaAnswer(null);
    setImpactResult(null);
    setRefactorResult(null);
    setRefactorDescription("");
    setOverview(null);
    setProjectData(null);
    setSelectedFilePath("");
    setQuestion("");
  };

  const pollProjectStatus = async (pId) => {
    setStatusMessage("Parsing code and extracting symbols...");
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 800));
      try {
        const res = await fetch(`${API_BASE}/upload/${pId}/status`);
        if (!res.ok) continue;
        const data = await res.json();
        if (data.status === "ready") {
          return true;
        }
        if (data.status === "failed") {
          throw new Error("Backend parsing failed for this project.");
        }
      } catch (err) {
        console.error("Status poll error:", err);
      }
    }
    throw new Error("Project indexing timed out. Please try again.");
  };

  const loadProjectStructure = async (pId) => {
    try {
      const [structRes, overviewRes] = await Promise.all([
        fetch(`${API_BASE}/projects/${pId}/structure`),
        fetch(`${API_BASE}/projects/${pId}/overview`),
      ]);
      if (activeProjectRef.current !== pId) return;
      if (structRes.ok) {
        const data = await structRes.json();
        if (activeProjectRef.current !== pId) return;
        setProjectData(data);
        if (data.files && data.files.length > 0) {
          setSelectedFilePath(data.files[0].path);
        }
      }
      if (overviewRes.ok) {
        const ov = await overviewRes.json();
        if (activeProjectRef.current === pId) setOverview(ov);
      }
    } catch (err) {
      console.error("Failed to load structure:", err);
    }
  };

  const handleBrowse = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (file) {
      setSelectedFile(file);
      setGithubUrl("");
      setErrorMessage("");
      setActivePage("Upload Code");
    }
  };

  const handleAnalyze = async () => {
    if (!selectedFile && !githubUrl.trim()) {
      alert("Please choose a file or enter a GitHub repository URL!");
      setActivePage("Upload Code");
      return;
    }

    setAnalyzing(true);
    setErrorMessage("");
    setStatusMessage("Uploading project to CodeLens AI...");

    try {
      let res;
      if (selectedFile) {
        const formData = new FormData();
        formData.append("file", selectedFile);
        res = await fetch(`${API_BASE}/upload`, {
          method: "POST",
          body: formData,
        });
      } else {
        const formData = new FormData();
        formData.append("github_url", githubUrl.trim());
        res = await fetch(`${API_BASE}/upload`, {
          method: "POST",
          body: formData,
        });
      }

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(errData.detail || "Upload failed");
      }

      const uploadData = await res.json();
      const pId = uploadData.project_id;
      activeProjectRef.current = pId;
      resetProjectState(); // never show the previous project's results for the new one
      setProjectId(pId);

      await pollProjectStatus(pId);
      await loadProjectStructure(pId);

      setStatusMessage("Analysis ready!");
      setActivePage("Code Analysis");
      fetchHistory();
    } catch (err) {
      console.error("Analysis failed:", err);
      setErrorMessage(err.message || "Failed to analyze code");
    } finally {
      setAnalyzing(false);
      setStatusMessage("");
    }
  };

  const handleExplain = async (level = explainLevel, file = selectedFilePath) => {
    if (!projectId) return;
    setExplaining(true);
    setErrorMessage("");
    try {
      const res = await fetch(`${API_BASE}/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          file_path: file || undefined,
          level: level,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Explain failed");
      }
      const data = await res.json();
      if (activeProjectRef.current !== data.project_id) return;
      setExplanationResult(data);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setExplaining(false);
    }
  };

  const handleGenerateDocs = async (kind = docKind, force = false) => {
    if (!projectId) return;
    const requestedProject = projectId;
    setGeneratingDocs(true);
    setErrorMessage("");
    try {
      const res = await fetch(`${API_BASE}/generate-docs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          kind: kind,
          force_regenerate: force,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Doc generation failed");
      }
      const data = await res.json();
      if (activeProjectRef.current !== requestedProject) return;
      setDocContent(data.content);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setGeneratingDocs(false);
    }
  };

  const handleGenerateDiagram = async (force = false) => {
    if (!projectId) return;
    const requestedProject = projectId;
    setGeneratingDiagram(true);
    setErrorMessage("");
    try {
      const res = await fetch(`${API_BASE}/generate-diagram`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          force_regenerate: force,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Diagram generation failed");
      }
      const data = await res.json();
      if (activeProjectRef.current !== requestedProject) return;
      setDiagramMermaid(data.mermaid);
      setDiagramData(data);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setGeneratingDiagram(false);
    }
  };

  const handleImpact = async (file = selectedFilePath, questionText = "") => {
    if (!projectId || !file) return;
    const requestedProject = projectId;
    setImpactLoading(true);
    setErrorMessage("");
    try {
      // Return the deterministic graph analysis immediately. Gemini enhancement
      // is requested separately so a slow model/API call never blocks the UI.
      const res = await fetch(`${API_BASE}/tools/impact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, file_path: file, question: questionText }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Impact analysis failed");
      if (activeProjectRef.current !== requestedProject) return;
      setImpactResult(data);

      // Enhance in the background. The static result is already visible.
      fetch(`${API_BASE}/tools/impact?include_ai=true`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, file_path: file, question: questionText }),
      })
        .then((aiRes) => aiRes.json())
        .then((aiData) => {
          if (activeProjectRef.current !== requestedProject || !aiData.ai_explanation) return;
          setImpactResult((current) => current ? { ...current, ai_explanation: aiData.ai_explanation, source: aiData.source, ai_pending: false } : current);
        })
        .catch(() => {
          // Static analysis remains valid if Gemini is slow/unavailable.
        });
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setImpactLoading(false);
    }
  };

  const handleSafeRefactor = async () => {
    if (!projectId || !selectedFilePath || !refactorDescription.trim()) return;
    const requestedProject = projectId;
    setRefactorLoading(true);
    setErrorMessage("");
    try {
      // Build the evidence-backed checklist locally first so the result is immediate.
      const payload = {
        project_id: projectId,
        file_path: selectedFilePath,
        proposed_change: refactorDescription.trim(),
      };
      const res = await fetch(`${API_BASE}/tools/safe-refactor`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Safe refactor planning failed");
      if (activeProjectRef.current !== requestedProject) return;
      setRefactorResult(data);

      // Ask Gemini in the background. The verified checklist does not wait for it.
      fetch(`${API_BASE}/tools/safe-refactor?include_ai=true`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((aiRes) => aiRes.json())
        .then((aiData) => {
          if (activeProjectRef.current !== requestedProject || !aiData.ai_plan) return;
          setRefactorResult((current) => current ? { ...current, ai_plan: aiData.ai_plan, source: aiData.source, ai_pending: false } : current);
        })
        .catch(() => {
          // Static refactor plan remains available if Gemini is slow/unavailable.
        });
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setRefactorLoading(false);
    }
  };

  const handleAsk = async (e, presetQuestion) => {
    e?.preventDefault();
    const asked = (presetQuestion ?? question).trim();
    if (!projectId || !asked) return;
    const requestedProject = projectId;
    setAsking(true);
    setErrorMessage("");
    try {
      const res = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          question: asked,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Q&A failed");
      }
      const data = await res.json();
      if (activeProjectRef.current !== requestedProject) return;
      setQaAnswer(data);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setAsking(false);
    }
  };

  const handleSelectHistoryProject = async (pId, name) => {
    activeProjectRef.current = pId;
    setProjectId(pId);
    setSelectedFile({ name: name || "Archived Project", size: 1024 });
    resetProjectState();
    await loadProjectStructure(pId);
    setActivePage("Code Analysis");
  };

  const handleMenuClick = (page) => {
    setActivePage(page);
    if (page === "Documentation" && projectId && !docContent) {
      handleGenerateDocs(docKind);
    } else if (page === "Architecture" && projectId && !diagramMermaid) {
      handleGenerateDiagram();
    } else if (page === "Code Analysis" && projectId && !explanationResult) {
      handleExplain(explainLevel, selectedFilePath);
    }
  };

  const scrollToUpload = () => {
    setActivePage("Upload Code");
    setTimeout(() => {
      document.getElementById("upload-section")?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  // Render Dashboard
  const renderDashboard = () => (
    <>
      <section className="hero-banner">
        <div className="hero-content">
          <span className="ai-badge">✦ POWERED BY AI</span>
          <h2>
            Understand your code.
            <br />
            <span>Build smarter.</span>
          </h2>
          <p>
            Upload your source code or zip archive and let CodeLens AI analyze your project,
            explain complex logic, generate documentation, visualize architecture, and answer codebase questions.
          </p>
          <div className="hero-actions">
            <button className="hero-btn" onClick={scrollToUpload}>
              Start Analyzing →
            </button>
            <button className="secondary-btn" onClick={scrollToUpload}>
              Upload Code
            </button>
          </div>
        </div>

        <div className="hero-visual">
          <div className="orbit orbit1"></div>
          <div className="orbit orbit2"></div>
          <div className="orbit orbit3"></div>
          <div className="ai-circle">AI</div>
          <div className="floating-card card1">
            <strong>⌘ Code Analysis</strong>
            <span>{projectId ? "Ready ✓" : "Static & AI"}</span>
          </div>
          <div className="floating-card card2">
            <strong>▤ Documentation</strong>
            <span>{docContent ? "Generated ✓" : "Automated"}</span>
          </div>
          <div className="floating-card card3">
            <strong>◇ Architecture</strong>
            <span>Flowcharts</span>
          </div>
        </div>
      </section>

      {/* STATS */}
      <section className="stats">
        <div className="stat-card">
          <div className="stat-icon">📁</div>
          <div>
            <p>Projects</p>
            <h2>{historyList.length || (projectId ? 1 : 0)}</h2>
            <span>Projects in database</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">📄</div>
          <div>
            <p>Files Analyzed</p>
            <h2>{projectData?.file_count || (projectId ? 1 : 0)}</h2>
            <span>Source files indexed</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">🧠</div>
          <div>
            <p>Languages</p>
            <h2>
              {projectData?.languages
                ? Object.keys(projectData.languages).length
                : projectId
                ? 1
                : 0}
            </h2>
            <span>Supported languages</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">📝</div>
          <div>
            <p>Analysis Engine</p>
            <h2>Active</h2>
            <span>FastAPI + Parser</span>
          </div>
        </div>
      </section>

      {/* UPLOAD + ACTIVITY */}
      <section className="dashboard-grid" id="upload-section">
        <div className="upload-section">
          <div className="section-title">
            <span className="section-label">GET STARTED</span>
            <h2>Start a New Analysis</h2>
            <p>Upload a source code file, zip archive, or GitHub repository URL.</p>
          </div>

          {errorMessage && <div className="error-banner">{errorMessage}</div>}

          <div className="upload-box">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".py,.java,.js,.jsx,.ts,.tsx,.cpp,.c,.cs,.go,.rs,.php,.html,.css,.scss,.sql,.yaml,.yml,.toml,.md,.json,.zip"
              hidden
            />

            <div className="upload-icon">
              {analyzing ? <span className="spinner" /> : selectedFile ? "✓" : "↑"}
            </div>

            {selectedFile ? (
              <>
                <h3>{selectedFile.name}</h3>
                <p>
                  {(selectedFile.size / 1024).toFixed(2)} KB · Ready for AI analysis
                </p>
                <div className="upload-actions">
                  <button className="browse-btn" onClick={handleBrowse} disabled={analyzing}>
                    Change File
                  </button>
                  <button
                    className="analyze-btn"
                    onClick={handleAnalyze}
                    disabled={analyzing}
                  >
                    {analyzing ? (statusMessage || "Analyzing...") : "Analyze Now →"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3>Drop your code or ZIP here</h3>
                <p>Supports .zip repositories, Python, JS, TS, Java, C++, Go, Rust, and more</p>
                <button className="browse-btn" onClick={handleBrowse} disabled={analyzing}>
                  Browse Files / ZIP
                </button>
                <span className="file-info">
                  Or paste a public Git repo URL below
                </span>
                <input
                  type="text"
                  placeholder="https://github.com/user/repo"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  style={{
                    marginTop: "12px",
                    width: "80%",
                    maxWidth: "340px",
                    padding: "8px 12px",
                    borderRadius: "8px",
                    border: "1px solid #cbd5e1",
                    fontSize: "12px",
                  }}
                />
                {githubUrl.trim() && (
                  <button
                    className="analyze-btn"
                    style={{ marginTop: "10px" }}
                    onClick={handleAnalyze}
                    disabled={analyzing}
                  >
                    {analyzing ? (statusMessage || "Analyzing...") : "Clone & Analyze →"}
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        {/* RECENT ACTIVITY */}
        <div className="activity-section">
          <div className="section-title">
            <span className="section-label">ACTIVITY</span>
            <h2>Recent Projects</h2>
            <p>Your latest AI analyses and saved projects.</p>
          </div>

          {historyList.length > 0 ? (
            <div className="activity-list">
              {historyList.slice(0, 4).map((item) => (
                <div
                  key={item.project_id}
                  className="activity-item"
                  style={{ cursor: "pointer" }}
                  onClick={() => handleSelectHistoryProject(item.project_id, item.name)}
                >
                  <div className="activity-icon">📁</div>
                  <div>
                    <h4>{item.name}</h4>
                    <p>
                      {item.file_count} files · {item.source}
                    </p>
                    <span>Status: {item.status}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-activity">
              <div className="empty-icon">◷</div>
              <h3>No activity yet</h3>
              <p>Your uploaded files and AI analyses will appear here.</p>
              <button onClick={scrollToUpload}>Analyze Code →</button>
            </div>
          )}
        </div>
      </section>

      {/* FEATURES */}
      <section className="features-section">
        <div className="section-title">
          <span className="section-label">CAPABILITIES</span>
          <h2>What can CodeLens AI do?</h2>
          <p>AI-powered tools designed to help developers understand, document, and navigate their code.</p>
        </div>

        <div className="features-grid">
          <div className="feature-card" onClick={() => handleMenuClick("Code Analysis")}>
            <div className="feature-icon">🧠</div>
            <h3>Explain Code</h3>
            <p>Get instant explanations tailored to Beginner, Developer, or Technical levels.</p>
            <span>Explore →</span>
          </div>

          <div className="feature-card" onClick={() => handleMenuClick("Documentation")}>
            <div className="feature-icon">📚</div>
            <h3>Generate Documentation</h3>
            <p>Automatically generate structured README and API reference documentation.</p>
            <span>Explore →</span>
          </div>

          <div className="feature-card" onClick={() => handleMenuClick("Architecture")}>
            <div className="feature-icon">🔗</div>
            <h3>Visualize Architecture</h3>
            <p>Generate Mermaid module dependency graphs and visualize system structure.</p>
            <span>Explore →</span>
          </div>
        </div>
      </section>
    </>
  );

  const renderPageContent = () => {
    if (activePage === "Dashboard") {
      return renderDashboard();
    }

    if (activePage === "Upload Code") {
      return (
        <section className="page-content">
          <div className="page-heading">
            <span className="section-label">UPLOAD</span>
            <h1>Upload Your Code</h1>
            <p>Select a source file, zip archive, or GitHub URL to begin AI-powered analysis.</p>
          </div>

          {errorMessage && <div className="error-banner">{errorMessage}</div>}

          <div className="upload-box large-upload">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".py,.java,.js,.jsx,.ts,.tsx,.cpp,.c,.cs,.go,.rs,.php,.html,.css,.scss,.sql,.yaml,.yml,.toml,.md,.json,.zip"
              hidden
            />

            <div className="upload-icon">
              {analyzing ? <span className="spinner" /> : selectedFile ? "✓" : "↑"}
            </div>

            <h3>{selectedFile ? selectedFile.name : "Choose a source code file or .zip"}</h3>

            <p>
              {selectedFile
                ? "File is selected and ready for analysis"
                : "Upload code to parse symbols, build dependency graphs, and generate docs."}
            </p>

            <button className="browse-btn" onClick={handleBrowse} disabled={analyzing}>
              {selectedFile ? "Change File" : "Browse Files"}
            </button>

            {selectedFile && (
              <button className="analyze-btn" onClick={handleAnalyze} disabled={analyzing}>
                {analyzing ? (statusMessage || "Analyzing...") : "Analyze Now →"}
              </button>
            )}
          </div>
        </section>
      );
    }

    if (activePage === "Code Analysis") {
      return (
        <section className="page-content">
          <div className="page-heading">
            <span className="section-label">AI ANALYSIS</span>
            <h1>Code Analysis & Explanations</h1>
            <p>Multi-level AI-powered understanding of your project functions and architecture.</p>
          </div>

          {errorMessage && <div className="error-banner">{errorMessage}</div>}

          <div className="result-card">
            {projectId ? (
              <>
                <div className="result-status">✓ Project Indexed ({selectedFile?.name || "Active"})</div>

                {overview && (
                  <div className="overview-panel">
                    <h3>{overview.name}</h3>
                    <p className="overview-type">{overview.project_type}</p>
                    <p className="overview-summary">{overview.summary}</p>
                    {overview.purpose && (
                      <p className="overview-purpose">
                        “{overview.purpose}” <span className="tree-via">{overview.purpose_source}</span>
                      </p>
                    )}
                    <div className="insight-grid">
                      <div className="insight-card">
                        <h4>Technology stack</h4>
                        <div className="sources-tags">
                          {overview.technologies.map((t) => (
                            <span key={t.name} className="source-tag" title={t.category}>
                              {t.name}
                            </span>
                          ))}
                          {overview.tooling.map((t) => (
                            <span key={t.name} className="source-tag tag-muted" title={`${t.category} (dev)`}>
                              {t.name}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="insight-card">
                        <h4>Entry points</h4>
                        <ul className="relation-list">
                          {overview.entry_points.map((e) => (
                            <li key={e.path}>
                              <button
                                type="button"
                                className="link-btn"
                                onClick={() => {
                                  setSelectedFilePath(e.path);
                                  handleExplain(explainLevel, e.path);
                                }}
                              >
                                {e.path}
                              </button>
                              <span className="tree-via">{e.reason}</span>
                            </li>
                          ))}
                          {overview.entry_points.length === 0 && <li>None detected</li>}
                        </ul>
                      </div>
                      <div className="insight-card">
                        <h4>Architecture</h4>
                        <p className="insight-text">{overview.architecture.style}</p>
                        {overview.architecture.layer_links.map((l) => (
                          <p key={l} className="insight-text">{l}</p>
                        ))}
                      </div>
                      <div className="insight-card">
                        <h4>Subsystems</h4>
                        <ul className="relation-list">
                          {overview.subsystems.slice(0, 8).map((sub) => (
                            <li key={sub.path}>
                              <strong>{sub.label}</strong> <span className="tree-via">{sub.path}/ · {sub.files} files</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                    {overview.limitations && overview.limitations.length > 0 && (
                      <p className="insight-note">Analysis notes: {overview.limitations.join(" ")}</p>
                    )}
                  </div>
                )}

                <div className="controls-row">
                  <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                    <label style={{ fontSize: "13px", fontWeight: "600", color: "#475569" }}>
                      File:
                    </label>
                    <select
                      className="file-select-dropdown"
                      value={selectedFilePath}
                      onChange={(e) => {
                        setSelectedFilePath(e.target.value);
                        handleExplain(explainLevel, e.target.value);
                      }}
                    >
                      <option value="">All Project Files</option>
                      {projectData?.files?.map((f) => (
                        <option key={f.path} value={f.path}>
                          {f.path} ({f.language})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="level-selector">
                    {["beginner", "developer", "technical"].map((lvl) => (
                      <button
                        key={lvl}
                        className={`tab-btn ${explainLevel === lvl ? "active" : ""}`}
                        onClick={() => {
                          setExplainLevel(lvl);
                          handleExplain(lvl, selectedFilePath);
                        }}
                      >
                        {lvl.charAt(0).toUpperCase() + lvl.slice(1)}
                      </button>
                    ))}
                  </div>

                  <button
                    className="browse-btn"
                    style={{ margin: 0, padding: "8px 16px", fontSize: "13px" }}
                    onClick={() => handleExplain(explainLevel, selectedFilePath)}
                    disabled={explaining}
                  >
                    {explaining ? "Explaining..." : "↻ Refresh"}
                  </button>
                </div>

                {explaining ? (
                  <div style={{ padding: "40px 0" }}>
                    <span className="spinner" style={{ borderColor: "#6b5cff", borderTopColor: "transparent" }} />
                    <p style={{ marginTop: "12px", color: "#64748b" }}>Generating AI explanation...</p>
                  </div>
                ) : explanationResult ? (
                  <div className="markdown-box">
                    {explanationResult.explanation ? (
                      <div>
                        <strong style={{ color: "#4338ca" }}>
                          [{explanationResult.level.toUpperCase()}] {explanationResult.file_path}:
                        </strong>
                        <p style={{ marginTop: "8px" }}>{explanationResult.explanation}</p>
                      </div>
                    ) : explanationResult.explanations ? (
                      <div>
                        {explanationResult.explanations.map((item, idx) => (
                          <div key={idx} style={{ marginBottom: "16px", borderBottom: "1px solid #e2e8f0", paddingBottom: "12px" }}>
                            <strong style={{ color: "#4338ca" }}>📄 {item.file_path}</strong>
                            <p style={{ marginTop: "6px" }}>{item.explanation}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      "No explanation generated."
                    )}
                  </div>
                ) : (
                  <button
                    className="browse-btn"
                    onClick={() => handleExplain(explainLevel, selectedFilePath)}
                  >
                    Generate Explanation
                  </button>
                )}

                {!explaining && explanationResult?.analysis && (
                  <div className="file-role-panel">
                    <div className="badge-row">
                      <span className="badge">{explanationResult.analysis.role}</span>
                      {explanationResult.analysis.subsystem && (
                        <span className="badge badge-soft">{explanationResult.analysis.subsystem}</span>
                      )}
                      {explanationResult.analysis.entry && <span className="badge badge-warn">entry point</span>}
                      <span className="badge badge-soft">
                        analysis confidence: {explanationResult.analysis.confidence}
                      </span>
                      <span className="badge badge-soft">source: {explanationResult.source}</span>
                    </div>
                    <div className="insight-grid">
                      <RelationList
                        title="Dependencies"
                        items={explanationResult.analysis.depends_on}
                        onSelect={(path) => {
                          setSelectedFilePath(path);
                          handleExplain(explainLevel, path);
                        }}
                      />
                      <RelationList
                        title="Used by"
                        items={explanationResult.analysis.used_by}
                        onSelect={(path) => {
                          setSelectedFilePath(path);
                          handleExplain(explainLevel, path);
                        }}
                      />
                    </div>
                    {explanationResult.analysis.related_files.length > 0 && (
                      <div className="insight-card">
                        <h4>Related files</h4>
                        <div className="sources-tags">
                          {explanationResult.analysis.related_files.map((path) => (
                            <button
                              key={path}
                              type="button"
                              className="source-tag source-tag-btn"
                              onClick={() => {
                                setSelectedFilePath(path);
                                handleExplain(explainLevel, path);
                              }}
                            >
                              {path}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {explanationResult.analysis.warnings.length > 0 && (
                      <p className="insight-note">{explanationResult.analysis.warnings.join(" ")}</p>
                    )}
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="empty-icon">🧠</div>
                <h2>No project loaded</h2>
                <p>Upload a code file or choose a project from History.</p>
                <button className="browse-btn" onClick={scrollToUpload}>
                  Upload Code
                </button>
              </>
            )}
          </div>
        </section>
      );
    }

    if (activePage === "Documentation") {
      return (
        <section className="page-content">
          <div className="page-heading">
            <span className="section-label">DOCUMENTATION</span>
            <h1>Generated Documentation</h1>
            <p>Automated README and API Reference generated directly from extracted symbols.</p>
          </div>

          {errorMessage && <div className="error-banner">{errorMessage}</div>}

          <div className="result-card">
            {projectId ? (
              <>
                <div className="controls-row">
                  <div className="tabs-selector">
                    <button
                      className={`tab-btn ${docKind === "readme" ? "active" : ""}`}
                      onClick={() => {
                        setDocKind("readme");
                        handleGenerateDocs("readme");
                      }}
                    >
                      README.md
                    </button>
                    <button
                      className={`tab-btn ${docKind === "api_docs" ? "active" : ""}`}
                      onClick={() => {
                        setDocKind("api_docs");
                        handleGenerateDocs("api_docs");
                      }}
                    >
                      API Reference
                    </button>
                  </div>

                  <div style={{ display: "flex", gap: "8px" }}>
                    <button
                      className="tab-btn"
                      style={{ background: "#e2e8f0" }}
                      onClick={() => {
                        if (docContent) {
                          navigator.clipboard.writeText(docContent);
                          alert("Markdown copied to clipboard!");
                        }
                      }}
                    >
                      📋 Copy
                    </button>
                    <button
                      className="browse-btn"
                      style={{ margin: 0, padding: "8px 16px", fontSize: "13px" }}
                      onClick={() => handleGenerateDocs(docKind, true)}
                      disabled={generatingDocs}
                    >
                      {generatingDocs ? "Regenerating..." : "↻ Force Regenerate"}
                    </button>
                  </div>
                </div>

                {generatingDocs ? (
                  <div style={{ padding: "40px 0" }}>
                    <span className="spinner" style={{ borderColor: "#6b5cff", borderTopColor: "transparent" }} />
                    <p style={{ marginTop: "12px", color: "#64748b" }}>Generating documentation...</p>
                  </div>
                ) : docContent ? (
                  <div className="markdown-box">{docContent}</div>
                ) : (
                  <button className="browse-btn" onClick={() => handleGenerateDocs(docKind)}>
                    Generate Documentation
                  </button>
                )}
              </>
            ) : (
              <>
                <div className="empty-icon">📚</div>
                <h2>No project loaded</h2>
                <p>Upload your code to generate documentation.</p>
                <button className="browse-btn" onClick={scrollToUpload}>
                  Upload Code
                </button>
              </>
            )}
          </div>
        </section>
      );
    }

    if (activePage === "Architecture") {
      return (
        <section className="page-content">
          <div className="page-heading">
            <span className="section-label">ARCHITECTURE</span>
            <h1>Architecture Visualization</h1>
            <p>How the project starts and how its files render, mount, call and import each other.</p>
          </div>

          {errorMessage && <div className="error-banner">{errorMessage}</div>}

          <div className="result-card">
            {projectId ? (
              <>
                <div className="controls-row">
                  <div className="result-status">✓ Relationship Graph Ready</div>
                  <button
                    className="browse-btn"
                    style={{ margin: 0, padding: "8px 16px", fontSize: "13px" }}
                    onClick={() => handleGenerateDiagram(true)}
                    disabled={generatingDiagram}
                  >
                    {generatingDiagram ? "Generating..." : "↻ Regenerate Diagram"}
                  </button>
                </div>

                {generatingDiagram ? (
                  <div style={{ padding: "40px 0" }}>
                    <span className="spinner" style={{ borderColor: "#6b5cff", borderTopColor: "transparent" }} />
                    <p style={{ marginTop: "12px", color: "#64748b" }}>Analyzing dependencies...</p>
                  </div>
                ) : diagramMermaid ? (
                  <div>
                    {overview && (
                      <div className="overview-panel">
                        <p className="overview-type">{overview.project_type}</p>
                        <p className="insight-text">{overview.architecture.style}</p>
                        {overview.architecture.startup_chains.map((chain) => (
                          <p key={chain.join(">")} className="insight-text">
                            <strong>Startup path:</strong> {chain.join(" → ")}
                          </p>
                        ))}
                        {overview.architecture.flows.map((f) => (
                          <p key={f} className="insight-text">{f}</p>
                        ))}
                      </div>
                    )}
                    {diagramData?.stats && (
                      <div className="badge-row" style={{ marginTop: "14px" }}>
                        <span className="badge badge-soft">{diagramData.stats.files} files</span>
                        <span className="badge badge-soft">{diagramData.stats.edges} relationships</span>
                        <span className="badge badge-soft">{diagramData.stats.endpoints} endpoints</span>
                        <span className="badge badge-soft">{diagramData.stats.entry_points} entry points</span>
                      </div>
                    )}
                    {diagramData?.tree && diagramData.tree.length > 0 && (
                      <div className="documentation-preview" style={{ margin: "15px auto", textAlign: "left" }}>
                        <h3>Structure from entry points</h3>
                        <p>Each file is shown under the file that renders, mounts, loads, calls or imports it.</p>
                        <ul className="tree-list tree-root">
                          {diagramData.tree.map((node, idx) => (
                            <TreeNode key={`${node.path}-${idx}`} node={node} />
                          ))}
                        </ul>
                      </div>
                    )}
                    <MermaidDiagram chart={diagramMermaid} />
                    <details className="documentation-preview mermaid-source" style={{ margin: "15px auto" }}>
                      <summary><strong>Mermaid Flowchart Syntax</strong></summary>
                      <p>Raw Mermaid generated by CodeLens-AI.</p>
                      <pre className="code-pre">{diagramMermaid}</pre>
                    </details>
                  </div>
                ) : (
                  <button className="browse-btn" onClick={() => handleGenerateDiagram()}>
                    Generate Architecture Diagram
                  </button>
                )}
              </>
            ) : (
              <>
                <div className="empty-icon">◇</div>
                <h2>Architecture not available</h2>
                <p>Upload a project to visualize module relationships.</p>
                <button className="browse-btn" onClick={scrollToUpload}>
                  Upload Code
                </button>
              </>
            )}
          </div>
        </section>
      );
    }

    if (activePage === "Ask Codebase") {
      return (
        <section className="page-content">
          <div className="page-heading">
            <span className="section-label">SEMANTIC SEARCH & Q&A</span>
            <h1>Ask Your Codebase</h1>
            <p>Ask about your codebase. Answers are built from the project's files, structure and relationships.</p>
          </div>

          {errorMessage && <div className="error-banner">{errorMessage}</div>}

          <div className="result-card">
            {projectId ? (
              <div className="qa-box">
                <form onSubmit={handleAsk} className="qa-input-row">
                  <input
                    type="text"
                    className="qa-input"
                    placeholder="e.g. What does the auth service do? How are files parsed?"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                  />
                  <button type="submit" className="qa-btn" disabled={asking || !question.trim()}>
                    {asking ? "Searching..." : "Ask AI →"}
                  </button>
                </form>

                <div className="sources-tags" style={{ marginTop: "10px" }}>
                  {[
                    "How does the application start?",
                    "Which files are responsible for the main feature?",
                    "What technologies does this project use?",
                    "What API endpoints exist?",
                  ].map((q) => (
                    <button
                      key={q}
                      type="button"
                      className="source-tag source-tag-btn"
                      disabled={asking}
                      onClick={() => {
                        setQuestion(q);
                        handleAsk(null, q);
                      }}
                    >
                      {q}
                    </button>
                  ))}
                </div>

                {asking && (
                  <div style={{ textAlign: "center", padding: "30px 0" }}>
                    <span className="spinner" style={{ borderColor: "#6b5cff", borderTopColor: "transparent" }} />
                    <p style={{ marginTop: "12px", color: "#64748b" }}>Searching files and relationships...</p>
                  </div>
                )}

                {qaAnswer && (
                  <div className="qa-answer-card">
                    <h4>
                      ✦ Answer
                      {qaAnswer.intent && <span className="badge badge-soft" style={{ marginLeft: "8px" }}>{qaAnswer.intent}</span>}
                    </h4>
                    <p>{qaAnswer.answer}</p>
                    {qaAnswer.sources && qaAnswer.sources.length > 0 && (
                      <div className="sources-tags">
                        <span style={{ fontSize: "11px", color: "#64748b", alignSelf: "center" }}>
                          Citations:
                        </span>
                        {qaAnswer.sources.map((src, idx) => (
                          <span key={idx} className="source-tag" title={src.reason || ""}>
                            📄 {src.file_path} ({Math.round(src.score * 100)}%)
                            {src.reason ? <em className="source-reason"> — {src.reason}</em> : null}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <>
                <div className="empty-icon">✦</div>
                <h2>No project loaded</h2>
                <p>Upload code to enable semantic codebase Q&A.</p>
                <button className="browse-btn" onClick={scrollToUpload}>
                  Upload Code
                </button>
              </>
            )}
          </div>
        </section>
      );
    }

    if (activePage === "Change Impact") {
      return (
        <section className="page-content">
          <div className="page-heading">
            <span className="section-label">ENGINEERING INTELLIGENCE</span>
            <h1>Change Impact Analyzer</h1>
            <p>See what could be affected before you change a file. CodeLens uses the verified project relationship graph first, then Gemini explains the impact.</p>
          </div>
          {errorMessage && <div className="error-banner">{errorMessage}</div>}
          <div className="result-card">
            {projectId ? (
              <>
                <div className="controls-row">
                  <div style={{ flex: 1, minWidth: "260px" }}>
                    <label className="control-label">File to change</label>
                    <select className="file-select" value={selectedFilePath} onChange={(e) => { setSelectedFilePath(e.target.value); setImpactResult(null); }}>
                      {(projectData?.files || []).map((f) => <option key={f.path} value={f.path}>{f.path}</option>)}
                    </select>
                  </div>
                  <button className="browse-btn" onClick={() => handleImpact()} disabled={impactLoading || !selectedFilePath}>
                    {impactLoading ? "Analyzing..." : "⚡ Analyze Impact"}
                  </button>
                </div>
                {impactResult && (
                  <>
                    <div className="impact-summary-grid">
                      <div className="impact-score-card"><span>Impact</span><strong>{impactResult.impact_level}</strong><small>{impactResult.impact_score}/100</small></div>
                      <div className="impact-metric"><span>Direct dependents</span><strong>{impactResult.counts.direct_dependents}</strong></div>
                      <div className="impact-metric"><span>Indirect dependents</span><strong>{impactResult.counts.indirect_dependents}</strong></div>
                      <div className="impact-metric"><span>Total impacted</span><strong>{impactResult.counts.total_impacted}</strong></div>
                      <div className="impact-metric"><span>Entry path</span><strong>{impactResult.entry_point_involvement ? "YES" : "NO"}</strong></div>
                    </div>
                    <div className="insight-grid">
                      <div className="insight-card">
                        <h4>Directly affected</h4>
                        {impactResult.direct_dependents.length ? <ul className="relation-list">{impactResult.direct_dependents.map((x) => <li key={x.path}><span className="tree-path">{x.path}</span><span className="tree-via">{x.relation}</span></li>)}</ul> : <p className="insight-note">No direct dependents detected.</p>}
                      </div>
                      <div className="insight-card">
                        <h4>Dependency context</h4>
                        {impactResult.dependencies.length ? <ul className="relation-list">{impactResult.dependencies.map((x) => <li key={x.path}><span className="tree-path">{x.path}</span><span className="tree-via">{x.relation}</span></li>)}</ul> : <p className="insight-note">No outgoing dependencies detected.</p>}
                      </div>
                    </div>
                    {impactResult.ai_explanation ? <div className="ai-insight-box"><strong>✦ Gemini impact explanation</strong><p>{impactResult.ai_explanation}</p></div> : impactResult.ai_pending ? <div className="ai-insight-box"><strong>✦ Gemini enhancement</strong><p>Static impact analysis is ready. Gemini is generating the explanation in the background.</p></div> : null}
                    <div className="insight-card" style={{ marginTop: "14px" }}>
                      <h4>Blast radius</h4>
                      <div className="sources-tags">{impactResult.impacted_files.map((x) => <button key={x.path} className="source-tag source-tag-btn" onClick={() => { setSelectedFilePath(x.path); handleImpact(x.path); }}>{x.path} · {x.distance} hop</button>)}</div>
                    </div>
                  </>
                )}
              </>
            ) : <><div className="empty-icon">⚡</div><h2>No project loaded</h2><p>Upload a project before analyzing change impact.</p><button className="browse-btn" onClick={scrollToUpload}>Upload Code</button></>}
          </div>
        </section>
      );
    }

    if (activePage === "Safe Refactor") {
      return (
        <section className="page-content">
          <div className="page-heading">
            <span className="section-label">ENGINEERING SAFETY</span>
            <h1>Safe Refactor Planner</h1>
            <p>Describe a proposed change. CodeLens builds an evidence-backed refactor checklist from the project's dependency graph.</p>
          </div>
          {errorMessage && <div className="error-banner">{errorMessage}</div>}
          <div className="result-card">
            {projectId ? (
              <>
                <div className="controls-row">
                  <div style={{ flex: 1, minWidth: "260px" }}>
                    <label className="control-label">File to refactor</label>
                    <select className="file-select" value={selectedFilePath} onChange={(e) => { setSelectedFilePath(e.target.value); setRefactorResult(null); }}>
                      {(projectData?.files || []).map((f) => <option key={f.path} value={f.path}>{f.path}</option>)}
                    </select>
                  </div>
                </div>
                <textarea className="refactor-input" rows="4" value={refactorDescription} onChange={(e) => setRefactorDescription(e.target.value)} placeholder="Example: Rename this component and split its API calls into a separate service." />
                <button className="browse-btn" onClick={handleSafeRefactor} disabled={refactorLoading || !refactorDescription.trim()}>
                  {refactorLoading ? "Building plan..." : "🛡 Generate Safe Refactor Plan"}
                </button>
                {refactorResult && (
                  <div style={{ marginTop: "18px" }}>
                    <div className="ai-insight-box"><strong>✦ Refactor plan</strong><p>{refactorResult.ai_plan || refactorResult.plan.join("\n")}</p>{refactorResult.ai_pending && <small>Gemini enhancement is running in the background.</small>}</div>
                    <div className="insight-card" style={{ marginTop: "14px", textAlign: "left" }}>
                      <h4>Verified checklist</h4>
                      <ol className="refactor-checklist">{refactorResult.plan.map((step, i) => <li key={i}>{step}</li>)}</ol>
                    </div>
                    <div className="badge-row"><span className="badge badge-soft">Impact: {refactorResult.impact.impact_level}</span><span className="badge badge-soft">{refactorResult.impact.counts.total_impacted} impacted files</span><span className="badge badge-soft">Source: {refactorResult.source}</span></div>
                  </div>
                )}
              </>
            ) : <><div className="empty-icon">🛡</div><h2>No project loaded</h2><p>Upload a project before creating a refactor plan.</p><button className="browse-btn" onClick={scrollToUpload}>Upload Code</button></>}
          </div>
        </section>
      );
    }

    if (activePage === "History") {
      return (
        <section className="page-content">
          <div className="page-heading">
            <span className="section-label">HISTORY</span>
            <h1>Analysis History</h1>
            <p>View all stored projects and click to inspect any previously analyzed codebase.</p>
          </div>

          <div className="result-card">
            {loadingHistory ? (
              <div style={{ padding: "40px 0" }}>
                <span className="spinner" style={{ borderColor: "#6b5cff", borderTopColor: "transparent" }} />
                <p style={{ marginTop: "12px", color: "#64748b" }}>Loading history...</p>
              </div>
            ) : historyList.length > 0 ? (
              <div className="activity-list">
                {historyList.map((item) => (
                  <div
                    key={item.project_id}
                    className="history-item"
                    style={{ cursor: "pointer" }}
                    onClick={() => handleSelectHistoryProject(item.project_id, item.name)}
                  >
                    <div className="activity-icon">📄</div>
                    <div style={{ textAlign: "left", flex: 1 }}>
                      <h3>{item.name}</h3>
                      <p>
                        {item.file_count} files · {item.explanation_count} explanations ·{" "}
                        {item.artifact_count} artifacts
                      </p>
                      <span>
                        Source: {item.source} · {new Date(item.created_at).toLocaleString()}
                      </span>
                    </div>
                    <button className="tab-btn" style={{ background: "#ede9fe", color: "#6b21a8" }}>
                      Open →
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <>
                <div className="empty-icon">◷</div>
                <h2>No history yet</h2>
                <p>Your previous code analyses will appear here once created.</p>
                <button className="browse-btn" onClick={scrollToUpload}>
                  Upload Code
                </button>
              </>
            )}
          </div>
        </section>
      );
    }
  };

  return (
    <div className="app">
      {/* SIDEBAR */}
      <aside className="sidebar">
        <div>
          <div className="brand">
            <div className="brand-icon">⌘</div>
            <h2>
              CodeLens <span>AI</span>
            </h2>
          </div>

          <div className="version">AI-POWERED DEVELOPER TOOL</div>

          <nav className="menu">
            {menuItems.map((item) => (
              <div
                key={item.name}
                className={`menu-item ${activePage === item.name ? "active" : ""}`}
                onClick={() => handleMenuClick(item.name)}
              >
                <span className="menu-icon">{item.icon}</span>
                <span>{item.name}</span>
              </div>
            ))}
          </nav>
        </div>

        <div className="sidebar-bottom">
          <div className="user-avatar">K</div>
          <div>
            <p className="user-name">Developer</p>
            <p className="user-status">● Online</p>
          </div>
        </div>
      </aside>

      {/* MAIN */}
      <main className="main">
        <header className="topbar">
          <div>
            <p className="welcome-small">
              {activePage === "Dashboard" ? "WELCOME BACK 👋" : activePage.toUpperCase()}
            </p>
            <h1>
              {activePage === "Dashboard" ? "Code Intelligence Dashboard" : activePage}
            </h1>
          </div>

          <button className="new-project-btn" onClick={scrollToUpload}>
            + New Analysis
          </button>
        </header>

        {renderPageContent()}
      </main>
    </div>
  );
}

export default App;
