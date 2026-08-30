import { useEffect, useRef, useState } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

function App() {
  const fileInputRef = useRef(null);

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
  const [historyList, setHistoryList] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const menuItems = [
    { name: "Dashboard", icon: "⌂" },
    { name: "Upload Code", icon: "↑" },
    { name: "Code Analysis", icon: "⌘" },
    { name: "Documentation", icon: "▤" },
    { name: "Architecture", icon: "◇" },
    { name: "Ask Codebase", icon: "✦" },
    { name: "History", icon: "◷" },
  ];

  // Fetch history whenever activePage is switched to History or Dashboard
  useEffect(() => {
    fetchHistory();
  }, [activePage]);

  const fetchHistory = async () => {
    try {
      setLoadingHistory(true);
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
      const res = await fetch(`${API_BASE}/projects/${pId}/structure`);
      if (res.ok) {
        const data = await res.json();
        setProjectData(data);
        if (data.files && data.files.length > 0) {
          setSelectedFilePath(data.files[0].path);
        }
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
      setExplanationResult(data);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setExplaining(false);
    }
  };

  const handleGenerateDocs = async (kind = docKind, force = false) => {
    if (!projectId) return;
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
      setDocContent(data.content);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setGeneratingDocs(false);
    }
  };

  const handleGenerateDiagram = async (force = false) => {
    if (!projectId) return;
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
      setDiagramMermaid(data.mermaid);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setGeneratingDiagram(false);
    }
  };

  const handleAsk = async (e) => {
    e?.preventDefault();
    if (!projectId || !question.trim()) return;
    setAsking(true);
    setErrorMessage("");
    try {
      const res = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          question: question.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Q&A failed");
      }
      const data = await res.json();
      setQaAnswer(data);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setAsking(false);
    }
  };

  const handleSelectHistoryProject = async (pId, name) => {
    setProjectId(pId);
    setSelectedFile({ name: name || "Archived Project", size: 1024 });
    setExplanationResult(null);
    setDocContent("");
    setDiagramMermaid("");
    setQaAnswer(null);
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
            <p>AI Engine</p>
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
              accept=".py,.java,.js,.jsx,.ts,.tsx,.cpp,.c,.cs,.go,.rs,.php,.html,.css,.json,.zip"
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
              accept=".py,.java,.js,.jsx,.ts,.tsx,.cpp,.c,.cs,.go,.rs,.php,.html,.css,.json,.zip"
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
            <p>Module dependency graph extracted from static code imports.</p>
          </div>

          {errorMessage && <div className="error-banner">{errorMessage}</div>}

          <div className="result-card">
            {projectId ? (
              <>
                <div className="controls-row">
                  <div className="result-status">✓ Dependency Graph Ready</div>
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
                    <div className="documentation-preview" style={{ margin: "15px auto" }}>
                      <h3>Mermaid Flowchart Syntax</h3>
                      <p>
                        This flowchart models the extracted internal import links between modules:
                      </p>
                    </div>
                    <pre className="code-pre">{diagramMermaid}</pre>
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
            <p>Ask natural language questions about your codebase with semantic chunk retrieval.</p>
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

                {asking && (
                  <div style={{ textAlign: "center", padding: "30px 0" }}>
                    <span className="spinner" style={{ borderColor: "#6b5cff", borderTopColor: "transparent" }} />
                    <p style={{ marginTop: "12px", color: "#64748b" }}>Retrieving code chunks & synthesizing answer...</p>
                  </div>
                )}

                {qaAnswer && (
                  <div className="qa-answer-card">
                    <h4>✦ AI Response:</h4>
                    <p>{qaAnswer.answer}</p>
                    {qaAnswer.sources && qaAnswer.sources.length > 0 && (
                      <div className="sources-tags">
                        <span style={{ fontSize: "11px", color: "#64748b", alignSelf: "center" }}>
                          Citations:
                        </span>
                        {qaAnswer.sources.map((src, idx) => (
                          <span key={idx} className="source-tag">
                            📄 {src.file_path} ({Math.round(src.score * 100)}%)
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