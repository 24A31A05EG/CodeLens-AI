from fastapi import FastAPI
from analyzer.scanner import scan_project
from analyzer.parser import parse_python_file

app = FastAPI(title="CodeLens AI - Code Intelligence Engine")


@app.get("/")
def health_check():
    return {
        "service": "Code Intelligence Engine",
        "status": "running"
    }


@app.post("/analyze")
def analyze_project(project_path: str):

    files = scan_project(project_path)

    return {
        "total_files": len(files),
        "files": files
    }