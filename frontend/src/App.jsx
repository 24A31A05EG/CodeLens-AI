import { useRef, useState } from "react";
import "./App.css";

function App() {
  const fileInputRef = useRef(null);

  const [activePage, setActivePage] = useState("Dashboard");
  const [selectedFile, setSelectedFile] = useState(null);
  const [analyzed, setAnalyzed] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  const menuItems = [
    { name: "Dashboard", icon: "⌂" },
    { name: "Upload Code", icon: "↑" },
    { name: "Code Analysis", icon: "⌘" },
    { name: "Documentation", icon: "▤" },
    { name: "Architecture", icon: "◇" },
    { name: "History", icon: "◷" },
  ];

  const handleBrowse = () => {
    fileInputRef.current.click();
  };

  const handleFileChange = (event) => {
    const file = event.target.files[0];

    if (file) {
      setSelectedFile(file);
      setAnalyzed(false);
      setActivePage("Upload Code");
    }
  };

  const handleAnalyze = () => {
    if (!selectedFile) {
      alert("Please upload a code file first!");
      setActivePage("Upload Code");
      return;
    }

    setAnalyzing(true);

    setTimeout(() => {
      setAnalyzing(false);
      setAnalyzed(true);
      setActivePage("Code Analysis");
    }, 1500);
  };

  const handleMenuClick = (page) => {
    setActivePage(page);
  };

  const scrollToUpload = () => {
    setActivePage("Upload Code");

    setTimeout(() => {
      document
        .getElementById("upload-section")
        ?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  const renderDashboard = () => (
    <>
      {/* HERO */}
      <section className="hero-banner">
        <div className="hero-content">
          <span className="ai-badge">✦ POWERED BY AI</span>

          <h2>
            Understand your code.
            <br />
            <span>Build smarter.</span>
          </h2>

          <p>
            Upload your source code and let CodeLens AI analyze your project,
            explain complex logic, generate documentation and visualize your
            architecture.
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
            <span>Completed ✓</span>
          </div>

          <div className="floating-card card2">
            <strong>▤ Documentation</strong>
            <span>Generated</span>
          </div>

          <div className="floating-card card3">
            <strong>◇ Architecture</strong>
            <span>Visualized</span>
          </div>
        </div>
      </section>

      {/* STATS */}
      <section className="stats">
        <div className="stat-card">
          <div className="stat-icon">📁</div>
          <div>
            <p>Projects</p>
            <h2>{selectedFile ? "1" : "0"}</h2>
            <span>Projects analyzed</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">📄</div>
          <div>
            <p>Files Analyzed</p>
            <h2>{analyzed ? "1" : "0"}</h2>
            <span>Source files processed</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">🧠</div>
          <div>
            <p>AI Insights</p>
            <h2>{analyzed ? "5" : "0"}</h2>
            <span>Smart insights generated</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">📝</div>
          <div>
            <p>Docs Generated</p>
            <h2>{analyzed ? "1" : "0"}</h2>
            <span>Documentation created</span>
          </div>
        </div>
      </section>

      {/* UPLOAD + ACTIVITY */}
      <section className="dashboard-grid" id="upload-section">
        <div className="upload-section">
          <div className="section-title">
            <span className="section-label">GET STARTED</span>
            <h2>Start a New Analysis</h2>
            <p>Upload your source code and unlock AI-powered insights.</p>
          </div>

          <div className="upload-box">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".py,.java,.js,.jsx,.ts,.tsx,.cpp,.c"
              hidden
            />

            <div className="upload-icon">
              {selectedFile ? "✓" : "↑"}
            </div>

            {selectedFile ? (
              <>
                <h3>{selectedFile.name}</h3>
                <p>
                  {(selectedFile.size / 1024).toFixed(2)} KB · Ready for
                  AI-powered analysis
                </p>

                <div className="upload-actions">
                  <button
                    className="browse-btn"
                    onClick={handleBrowse}
                  >
                    Change File
                  </button>

                  <button
                    className="analyze-btn"
                    onClick={handleAnalyze}
                    disabled={analyzing}
                  >
                    {analyzing ? "Analyzing..." : "Analyze Now →"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3>Drop your code here</h3>

                <p>
                  Upload Python, Java, JavaScript, C++, C or TypeScript files
                </p>

                <button
                  className="browse-btn"
                  onClick={handleBrowse}
                >
                  Browse Files
                </button>

                <span className="file-info">
                  Supported: .py · .java · .js · .jsx · .ts · .cpp · .c
                </span>
              </>
            )}
          </div>
        </div>

        {/* RECENT ACTIVITY */}
        <div className="activity-section">
          <div className="section-title">
            <span className="section-label">ACTIVITY</span>
            <h2>Recent Activity</h2>
            <p>Your latest AI analyses and generated insights.</p>
          </div>

          {selectedFile ? (
            <div className="activity-list">
              {analyzed && (
                <div className="activity-item">
                  <div className="activity-icon">✦</div>

                  <div>
                    <h4>AI analysis completed</h4>
                    <p>{selectedFile.name}</p>
                    <span>Just now</span>
                  </div>
                </div>
              )}

              <div className="activity-item">
                <div className="activity-icon">↑</div>

                <div>
                  <h4>File uploaded successfully</h4>
                  <p>{selectedFile.name}</p>
                  <span>Just now</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="empty-activity">
              <div className="empty-icon">◷</div>

              <h3>No activity yet</h3>

              <p>
                Your uploaded files and AI analyses will appear here.
              </p>

              <button onClick={scrollToUpload}>
                Analyze Code →
              </button>
            </div>
          )}
        </div>
      </section>

      {/* FEATURES */}
      <section className="features-section">
        <div className="section-title">
          <span className="section-label">CAPABILITIES</span>
          <h2>What can CodeLens AI do?</h2>
          <p>
            AI-powered tools designed to help developers understand and improve
            their code.
          </p>
        </div>

        <div className="features-grid">
          <div
            className="feature-card"
            onClick={() => setActivePage("Code Analysis")}
          >
            <div className="feature-icon">🧠</div>
            <h3>Explain Code</h3>

            <p>
              Get simple and clear AI-powered explanations for complex
              functions and application logic.
            </p>

            <span>Explore →</span>
          </div>

          <div
            className="feature-card"
            onClick={() => setActivePage("Documentation")}
          >
            <div className="feature-icon">📚</div>
            <h3>Generate Documentation</h3>

            <p>
              Automatically generate structured and useful documentation for
              your source code.
            </p>

            <span>Explore →</span>
          </div>

          <div
            className="feature-card"
            onClick={() => setActivePage("Architecture")}
          >
            <div className="feature-icon">🔗</div>
            <h3>Visualize Architecture</h3>

            <p>
              Understand file relationships, components and your overall
              project structure visually.
            </p>

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
            <p>Select a source code file to begin AI-powered analysis.</p>
          </div>

          <div className="upload-box large-upload">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".py,.java,.js,.jsx,.ts,.tsx,.cpp,.c"
              hidden
            />

            <div className="upload-icon">
              {selectedFile ? "✓" : "↑"}
            </div>

            <h3>
              {selectedFile
                ? selectedFile.name
                : "Choose a source code file"}
            </h3>

            <p>
              {selectedFile
                ? "File is ready for analysis"
                : "Upload your code and let AI understand it."}
            </p>

            <button className="browse-btn" onClick={handleBrowse}>
              {selectedFile ? "Change File" : "Browse Files"}
            </button>

            {selectedFile && (
              <button className="analyze-btn" onClick={handleAnalyze}>
                {analyzing ? "Analyzing..." : "Analyze Now →"}
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
            <h1>Code Analysis</h1>
            <p>AI-powered understanding of your source code.</p>
          </div>

          <div className="result-card">
            {analyzed ? (
              <>
                <div className="result-status">✓ Analysis Complete</div>

                <h2>{selectedFile?.name}</h2>

                <p>
                  Your source code has been successfully processed. The AI
                  engine can now generate explanations, documentation and
                  architecture insights.
                </p>

                <div className="insight-grid">
                  <div>
                    <strong>5</strong>
                    <span>Insights</span>
                  </div>

                  <div>
                    <strong>1</strong>
                    <span>File Processed</span>
                  </div>

                  <div>
                    <strong>Ready</strong>
                    <span>Documentation</span>
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="empty-icon">🧠</div>
                <h2>No analysis yet</h2>
                <p>Upload a code file and start AI analysis.</p>
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
            <p>AI-generated documentation for your project.</p>
          </div>

          <div className="result-card">
            {analyzed ? (
              <>
                <div className="result-status">✓ Documentation Ready</div>
                <h2>{selectedFile?.name} Documentation</h2>

                <div className="documentation-preview">
                  <h3>Project Overview</h3>
                  <p>
                    This documentation will describe the uploaded source code,
                    its structure, functions and key logic.
                  </p>

                  <h3>Key Components</h3>
                  <p>
                    AI-generated component descriptions will appear here after
                    backend integration.
                  </p>
                </div>
              </>
            ) : (
              <>
                <div className="empty-icon">📚</div>
                <h2>No documentation yet</h2>
                <p>Analyze your code to generate documentation.</p>
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
            <p>Understand your project's components and relationships.</p>
          </div>

          <div className="result-card">
            {analyzed ? (
              <div className="architecture-demo">
                <div className="arch-box">Source Code</div>
                <div className="arch-arrow">↓</div>
                <div className="arch-box active-box">AI Analysis Engine</div>
                <div className="arch-arrow">↓</div>

                <div className="arch-row">
                  <div className="arch-box">Explanation</div>
                  <div className="arch-box">Documentation</div>
                  <div className="arch-box">Architecture</div>
                </div>
              </div>
            ) : (
              <>
                <div className="empty-icon">◇</div>
                <h2>Architecture not available</h2>
                <p>Analyze your project to visualize its architecture.</p>
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
            <p>View your recent uploads and AI analyses.</p>
          </div>

          <div className="result-card">
            {selectedFile ? (
              <div className="history-item">
                <div className="activity-icon">📄</div>

                <div>
                  <h3>{selectedFile.name}</h3>
                  <p>
                    {analyzed
                      ? "Analysis completed successfully"
                      : "File uploaded — waiting for analysis"}
                  </p>
                  <span>Today · Just now</span>
                </div>
              </div>
            ) : (
              <>
                <div className="empty-icon">◷</div>
                <h2>No history yet</h2>
                <p>Your previous code analyses will appear here.</p>
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
                className={`menu-item ${
                  activePage === item.name ? "active" : ""
                }`}
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
              {activePage === "Dashboard"
                ? "WELCOME BACK 👋"
                : activePage.toUpperCase()}
            </p>

            <h1>
              {activePage === "Dashboard"
                ? "Code Intelligence Dashboard"
                : activePage}
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