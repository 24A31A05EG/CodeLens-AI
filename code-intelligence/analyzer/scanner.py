from pathlib import Path
SUPPORTED_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".go": "Go",
}


def scan_project(project_path: str):
    project = Path(project_path)

    if not project.exists():
        raise FileNotFoundError(f"Project not found: {project_path}")

    files = []

    for file_path in project.rglob("*"):
        if file_path.is_file():
            language = SUPPORTED_EXTENSIONS.get(file_path.suffix.lower())

            if language:
                files.append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "extension": file_path.suffix.lower(),
                    "language": language
                })

    return files