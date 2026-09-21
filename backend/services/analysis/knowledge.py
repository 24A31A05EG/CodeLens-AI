"""
Generic knowledge tables used to interpret static facts.

These tables describe *conventions of the software ecosystem* (what the npm
package ``three`` is, what a directory called ``routers`` usually holds). They
contain nothing specific to any one uploaded project. Every statement the
analyzer makes about a project is still derived from that project's files;
these tables only translate raw identifiers into readable labels.
"""

import re
from typing import Dict, Optional, Tuple

# package name -> (display label, category)
# categories: framework, ui, 3d, animation, state, routing, build, lint, test,
#             http, backend, orm, database, validation, ai, data, styling, util, language
NPM_TECH: Dict[str, Tuple[str, str]] = {
    "react": ("React", "framework"),
    "react-dom": ("React DOM", "framework"),
    "vue": ("Vue", "framework"),
    "svelte": ("Svelte", "framework"),
    "next": ("Next.js", "framework"),
    "nuxt": ("Nuxt", "framework"),
    "@angular/core": ("Angular", "framework"),
    "solid-js": ("SolidJS", "framework"),
    "preact": ("Preact", "framework"),
    "vite": ("Vite", "build"),
    "webpack": ("Webpack", "build"),
    "parcel": ("Parcel", "build"),
    "esbuild": ("esbuild", "build"),
    "rollup": ("Rollup", "build"),
    "@vitejs/plugin-react": ("Vite React plugin", "build"),
    "@vitejs/plugin-react-swc": ("Vite React (SWC) plugin", "build"),
    "typescript": ("TypeScript", "language"),
    "three": ("Three.js", "3d"),
    "@react-three/fiber": ("React Three Fiber", "3d"),
    "@react-three/drei": ("Drei", "3d"),
    "@react-three/postprocessing": ("React Three Postprocessing", "3d"),
    "@react-three/rapier": ("React Three Rapier", "3d"),
    "postprocessing": ("postprocessing", "3d"),
    "leva": ("Leva", "3d"),
    "gsap": ("GSAP", "animation"),
    "framer-motion": ("Framer Motion", "animation"),
    "motion": ("Motion", "animation"),
    "@react-spring/web": ("React Spring", "animation"),
    "lottie-web": ("Lottie", "animation"),
    "react-router": ("React Router", "routing"),
    "react-router-dom": ("React Router", "routing"),
    "redux": ("Redux", "state"),
    "@reduxjs/toolkit": ("Redux Toolkit", "state"),
    "zustand": ("Zustand", "state"),
    "jotai": ("Jotai", "state"),
    "mobx": ("MobX", "state"),
    "@tanstack/react-query": ("TanStack Query", "state"),
    "swr": ("SWR", "state"),
    "axios": ("Axios", "http"),
    "express": ("Express", "backend"),
    "koa": ("Koa", "backend"),
    "fastify": ("Fastify", "backend"),
    "@nestjs/core": ("NestJS", "backend"),
    "mongoose": ("Mongoose", "orm"),
    "prisma": ("Prisma", "orm"),
    "@prisma/client": ("Prisma", "orm"),
    "sequelize": ("Sequelize", "orm"),
    "tailwindcss": ("Tailwind CSS", "styling"),
    "styled-components": ("styled-components", "styling"),
    "@emotion/react": ("Emotion", "styling"),
    "sass": ("Sass", "styling"),
    "eslint": ("ESLint", "lint"),
    "prettier": ("Prettier", "lint"),
    "vitest": ("Vitest", "test"),
    "jest": ("Jest", "test"),
    "@testing-library/react": ("React Testing Library", "test"),
    "cypress": ("Cypress", "test"),
    "playwright": ("Playwright", "test"),
    "@playwright/test": ("Playwright", "test"),
    "d3": ("D3", "data"),
    "chart.js": ("Chart.js", "data"),
    "recharts": ("Recharts", "data"),
    "mermaid": ("Mermaid", "data"),
    "zod": ("Zod", "validation"),
    "openai": ("OpenAI SDK", "ai"),
    "@anthropic-ai/sdk": ("Anthropic SDK", "ai"),
    "langchain": ("LangChain", "ai"),
    "socket.io": ("Socket.IO", "backend"),
    "socket.io-client": ("Socket.IO client", "http"),
}

# python distribution / import name (lower-case) -> (label, category)
PY_TECH: Dict[str, Tuple[str, str]] = {
    "fastapi": ("FastAPI", "backend"),
    "flask": ("Flask", "backend"),
    "django": ("Django", "backend"),
    "starlette": ("Starlette", "backend"),
    "tornado": ("Tornado", "backend"),
    "aiohttp": ("aiohttp", "http"),
    "uvicorn": ("Uvicorn", "backend"),
    "gunicorn": ("Gunicorn", "backend"),
    "sqlalchemy": ("SQLAlchemy", "orm"),
    "alembic": ("Alembic", "orm"),
    "psycopg2": ("psycopg2 (PostgreSQL)", "database"),
    "psycopg2-binary": ("psycopg2 (PostgreSQL)", "database"),
    "pymongo": ("PyMongo", "database"),
    "redis": ("Redis client", "database"),
    "pgvector": ("pgvector", "database"),
    "pydantic": ("Pydantic", "validation"),
    "requests": ("Requests", "http"),
    "httpx": ("HTTPX", "http"),
    "celery": ("Celery", "backend"),
    "numpy": ("NumPy", "data"),
    "pandas": ("pandas", "data"),
    "scikit-learn": ("scikit-learn", "ai"),
    "sklearn": ("scikit-learn", "ai"),
    "torch": ("PyTorch", "ai"),
    "tensorflow": ("TensorFlow", "ai"),
    "transformers": ("Hugging Face Transformers", "ai"),
    "openai": ("OpenAI SDK", "ai"),
    "anthropic": ("Anthropic SDK", "ai"),
    "langchain": ("LangChain", "ai"),
    "ibm-watsonx-ai": ("IBM watsonx.ai", "ai"),
    "ibm_watsonx_ai": ("IBM watsonx.ai", "ai"),
    "pytest": ("pytest", "test"),
    "python-dotenv": ("python-dotenv", "util"),
    "dotenv": ("python-dotenv", "util"),
    "python-multipart": ("python-multipart", "util"),
    "beautifulsoup4": ("Beautiful Soup", "data"),
}

# Directory-name conventions -> (subsystem label, layer key)
DIR_CONVENTIONS: Dict[str, Tuple[str, str]] = {
    "src": ("Application source", "source"),
    "app": ("Application source", "source"),
    "components": ("UI components", "ui"),
    "component": ("UI components", "ui"),
    "ui": ("UI components", "ui"),
    "pages": ("Pages / screens", "ui"),
    "views": ("Pages / screens", "ui"),
    "screens": ("Pages / screens", "ui"),
    "layouts": ("Layouts", "ui"),
    "hooks": ("Custom hooks", "logic"),
    "context": ("Shared state / context", "logic"),
    "contexts": ("Shared state / context", "logic"),
    "store": ("State management", "logic"),
    "stores": ("State management", "logic"),
    "state": ("State management", "logic"),
    "redux": ("State management", "logic"),
    "utils": ("Utilities", "util"),
    "util": ("Utilities", "util"),
    "helpers": ("Utilities", "util"),
    "lib": ("Shared library code", "util"),
    "shared": ("Shared library code", "util"),
    "common": ("Shared library code", "util"),
    "3d": ("3D visualization", "3d"),
    "three": ("3D visualization", "3d"),
    "webgl": ("3D visualization", "3d"),
    "canvas": ("Canvas / graphics", "3d"),
    "shaders": ("Shaders", "3d"),
    "scenes": ("3D visualization", "3d"),
    "animations": ("Animation", "ui"),
    "animation": ("Animation", "ui"),
    "styles": ("Styling", "style"),
    "css": ("Styling", "style"),
    "assets": ("Static assets", "assets"),
    "public": ("Static assets", "assets"),
    "static": ("Static assets", "assets"),
    "images": ("Static assets", "assets"),
    "services": ("Service layer", "service"),
    "service": ("Service layer", "service"),
    "api": ("API layer", "api"),
    "routers": ("API routes", "api"),
    "router": ("API routes", "api"),
    "routes": ("API routes", "api"),
    "controllers": ("API controllers", "api"),
    "handlers": ("API handlers", "api"),
    "endpoints": ("API routes", "api"),
    "models": ("Data models", "data"),
    "model": ("Data models", "data"),
    "schemas": ("Data schemas", "data"),
    "entities": ("Data models", "data"),
    "db": ("Database layer", "data"),
    "database": ("Database layer", "data"),
    "migrations": ("Database migrations", "data"),
    "repositories": ("Database layer", "data"),
    "ai": ("AI layer", "ai"),
    "ml": ("AI layer", "ai"),
    "llm": ("AI layer", "ai"),
    "middleware": ("Middleware", "service"),
    "config": ("Configuration", "config"),
    "configs": ("Configuration", "config"),
    "tests": ("Tests", "test"),
    "test": ("Tests", "test"),
    "__tests__": ("Tests", "test"),
    "spec": ("Tests", "test"),
    "docs": ("Documentation", "docs"),
    "doc": ("Documentation", "docs"),
    "scripts": ("Scripts", "script"),
    "bin": ("Scripts", "script"),
    "frontend": ("Frontend application", "frontend"),
    "client": ("Frontend application", "frontend"),
    "web": ("Frontend application", "frontend"),
    "backend": ("Backend application", "backend"),
    "server": ("Backend application", "backend"),
}

# Config file basename patterns -> purpose sentence.
CONFIG_PURPOSES = [
    (r"^vite\.config\.[cm]?[jt]s$", "Vite build tool / dev-server configuration"),
    (r"^webpack\.config\.[cm]?[jt]s$", "Webpack bundler configuration"),
    (r"^rollup\.config\.[cm]?[jt]s$", "Rollup bundler configuration"),
    (r"^(eslint\.config\.[cm]?[jt]s|\.eslintrc(\.[cm]?[jt]s|\.json)?)$", "ESLint linting rules"),
    (r"^tsconfig(\..+)?\.json$", "TypeScript compiler configuration"),
    (r"^jsconfig\.json$", "JavaScript project / editor configuration"),
    (r"^(jest|vitest)\.config\.[cm]?[jt]s$", "Test runner configuration"),
    (r"^tailwind\.config\.[cm]?[jt]s$", "Tailwind CSS configuration"),
    (r"^postcss\.config\.[cm]?[jt]s$", "PostCSS configuration"),
    (r"^babel\.config\.[cm]?[jt]s$", "Babel transpiler configuration"),
    (r"^next\.config\.[cm]?[jt]s$", "Next.js configuration"),
    (r"^prettier(rc|\.config\.[cm]?[jt]s)?(\.json)?$", "Prettier formatting rules"),
    (r"^pyproject\.toml$", "Python project metadata and tool configuration"),
    (r"^(setup\.py|setup\.cfg)$", "Python packaging configuration"),
    (r"^docker-compose(\..+)?\.ya?ml$", "Docker Compose multi-container definition"),
    (r"^dockerfile(\..+)?$", "Container image build instructions"),
    (r"^requirements.*\.txt$", "Python dependency list (pip)"),
    (r"^vercel\.json$", "Vercel deployment configuration"),
    (r"^netlify\.toml$", "Netlify deployment configuration"),
    (r"^manifest\.json$", "Web app manifest"),
]


def config_purpose(basename: str) -> Optional[str]:
    base = basename.lower()
    for pattern, purpose in CONFIG_PURPOSES:
        if re.match(pattern, base):
            return purpose
    return None


# three.js / react-three-fiber JSX intrinsic element recognition.
def is_three_intrinsic(tag: str) -> bool:
    if tag in {
        "mesh", "group", "points", "line", "lineSegments", "sprite", "primitive",
        "scene", "object3D", "instancedMesh", "skinnedMesh", "lod", "bone",
        "perspectiveCamera", "orthographicCamera", "color", "fog", "fogExp2",
        "axesHelper", "gridHelper", "arrowHelper", "boxHelper",
    }:
        return True
    return bool(re.search(r"(Geometry|Material|Light|Helper|Texture)$", tag))


REACT_HOOK_MEANING = {
    "useState": "holds local component state",
    "useReducer": "manages state through a reducer",
    "useEffect": "runs side effects / lifecycle logic",
    "useLayoutEffect": "runs layout-synchronous side effects",
    "useRef": "keeps mutable references (e.g. to DOM or 3D objects)",
    "useMemo": "memoizes expensive calculations",
    "useCallback": "memoizes callback functions",
    "useContext": "reads shared context values",
    "useFrame": "runs logic on every rendered frame (React Three Fiber animation loop)",
    "useThree": "accesses the renderer, camera and scene (React Three Fiber)",
    "useGSAP": "drives GSAP animations tied to the component lifecycle",
    "useTexture": "loads textures (Drei)",
    "useGLTF": "loads glTF 3D models (Drei)",
    "useNavigate": "performs client-side navigation",
    "useParams": "reads route parameters",
    "useQuery": "fetches and caches remote data",
}


def package_root_name(spec: str) -> str:
    """'@scope/pkg/sub' -> '@scope/pkg'; 'lodash/fp' -> 'lodash'."""
    parts = spec.split("/")
    if spec.startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def humanize_identifier(name: str) -> str:
    """'EnergyCore' -> 'energy core'; 'use_parser' -> 'use parser'."""
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def tokenize(text: str):
    """Split text/identifiers into lower-case word tokens (camelCase, snake_case, paths)."""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    return [t for t in re.split(r"[^A-Za-z0-9]+", text.lower()) if t]


# kind id -> (short label, plain-language phrase for beginners)
KIND_LABELS = {
    "component": ("UI component", "a building block of the user interface"),
    "hook": ("custom hook", "a reusable piece of logic shared between components"),
    "api_router": ("API route module", "a file that answers requests sent to the server"),
    "app_setup": ("application setup module", "the file that creates and wires up the application"),
    "data_model": ("data model module", "a file that describes how data is stored"),
    "schema": ("data schema module", "a file that describes the shape of data"),
    "database": ("database setup module", "a file that connects the program to its database"),
    "service": ("service module", "a file holding business logic that other parts call on"),
    "utility": ("utility module", "a toolbox of small helper functions"),
    "state_store": ("state module", "a file that keeps shared data the app reads and updates"),
    "api_client": ("API client module", "a file that talks to a server over the network"),
    "module": ("module", "a code file"),
    "package_init": ("package marker", "a small file that marks a folder as a Python package"),
    "script": ("script", "a runnable helper program"),
    "test": ("test file", "a file that automatically checks that other code works"),
    "code_config": ("configuration module", "a code file that holds settings"),
    "package_manifest": ("package manifest", "the project's list of dependencies and commands"),
    "build_config": ("build configuration", "a settings file for the tool that builds the project"),
    "lint_config": ("lint configuration", "a settings file for the code style checker"),
    "compiler_config": ("compiler configuration", "a settings file for the language compiler"),
    "test_config": ("test configuration", "a settings file for the test runner"),
    "config": ("configuration file", "a settings file"),
    "dependency_list": ("dependency list", "a list of the outside packages the project needs"),
    "container": ("container definition", "instructions for packaging the app into a container"),
    "compose": ("container orchestration file", "a file describing several containers that run together"),
    "ci_workflow": ("CI workflow", "an automation recipe that runs on every code change"),
    "documentation": ("documentation", "a written guide for people"),
    "stylesheet": ("stylesheet", "a file that controls how the page looks"),
    "markup": ("HTML document", "the page skeleton the browser loads first"),
    "data": ("data file", "a file of structured data"),
    "sql": ("SQL script", "database instructions"),
    "lockfile": ("lock file", "an auto-generated record of exact package versions"),
}
