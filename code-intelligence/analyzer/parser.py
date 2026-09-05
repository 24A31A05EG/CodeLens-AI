import ast


def parse_python_file(file_path: str):
    with open(file_path, "r", encoding="utf-8") as file:
        source = file.read()

    tree = ast.parse(source)

    functions = []
    classes = []
    imports = []

    for node in ast.walk(tree):

        if isinstance(node, ast.FunctionDef):
            functions.append({
                "name": node.name,
                "line": node.lineno
            })

        elif isinstance(node, ast.AsyncFunctionDef):
            functions.append({
                "name": node.name,
                "line": node.lineno
            })

        elif isinstance(node, ast.ClassDef):
            classes.append({
                "name": node.name,
                "line": node.lineno
            })

        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return {
        "file": file_path,
        "language": "Python",
        "functions": functions,
        "classes": classes,
        "imports": imports
    }