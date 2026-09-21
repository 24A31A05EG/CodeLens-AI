"""
Synthetic sample repositories used by the CodeLens test-suite.

They are written to look like real projects (a React + Vite + Three.js
front-end, and a small FastAPI service) so tests exercise the analyzer against
realistic source. Nothing in the analyzer refers to these names.

The FastAPI fixture deliberately contains secret-looking material (a ``.env``
file and a hard-coded token) to verify that secrets are never ingested or
echoed back.
"""

import io
import zipfile

REACT_THREE_APP = {
    "index.html": """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Holo Core</title>
    <link rel="stylesheet" href="/src/index.css" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
""",
    "package.json": """{
  "name": "holo-core",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "lint": "eslint .",
    "preview": "vite preview"
  },
  "dependencies": {
    "@react-three/drei": "^9.100.0",
    "@react-three/fiber": "^8.16.0",
    "gsap": "^3.12.5",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "three": "^0.165.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "eslint": "^9.0.0",
    "vite": "^5.3.0"
  }
}
""",
    "package-lock.json": '{"name": "holo-core", "lockfileVersion": 3, "packages": {}}',
    "vite.config.js": """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
})
""",
    "eslint.config.js": """import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'

export default [
  { ignores: ['dist'] },
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: { globals: globals.browser },
    plugins: { 'react-hooks': reactHooks },
    rules: { ...js.configs.recommended.rules },
  },
]
""",
    "README.md": """# Holo Core

An interactive 3D landing page with a glowing energy core.

## Setup

```bash
npm install
npm run dev
```

## Architecture

The 3D scene lives in `src/3d` and is mounted from `src/App.jsx`.
""",
    "src/main.jsx": """import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
""",
    "src/App.jsx": """import { Canvas } from '@react-three/fiber'
import Scene from './3d/Scene'
import Navbar from './components/Navbar'
import Hero from './components/Hero'
import './App.css'

function App() {
  return (
    <div className="app">
      <Navbar />
      <Hero title="Holo Core" />
      <Canvas camera={{ position: [0, 0, 6], fov: 55 }}>
        <Scene />
      </Canvas>
    </div>
  )
}

export default App
""",
    "src/App.css": """.app { position: relative; min-height: 100vh; display: flex; flex-direction: column; }
@media (max-width: 768px) { .app { padding: 0 12px; } }
""",
    "src/index.css": """:root { --bg: #05060f; --glow: #6b5cff; }
body { margin: 0; background: var(--bg); color: #fff; font-family: system-ui, sans-serif; }
@keyframes pulse { from { opacity: .6 } to { opacity: 1 } }
.glow { animation: pulse 2s ease-in-out infinite alternate; }
""",
    "src/3d/Scene.jsx": """import { OrbitControls, Environment } from '@react-three/drei'
import EnergyCore from './EnergyCore'
import HolographicRings from './HolographicRings'
import Particles from './Particles'

/**
 * Root of the 3D scene: lighting, controls and the visual elements.
 */
export default function Scene() {
  return (
    <>
      <ambientLight intensity={0.4} />
      <pointLight position={[4, 4, 4]} intensity={1.2} />
      <Environment preset="night" />
      <EnergyCore />
      <HolographicRings count={3} />
      <Particles count={800} />
      <OrbitControls enablePan={false} />
    </>
  )
}
""",
    "src/3d/EnergyCore.jsx": """import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Float, MeshDistortMaterial } from '@react-three/drei'
import * as THREE from 'three'
import { pulse } from '../utils/math'

export default function EnergyCore({ intensity = 1, color = '#6b5cff' }) {
  const coreRef = useRef()
  const glowColor = useMemo(() => new THREE.Color(color), [color])

  useFrame((state) => {
    const t = state.clock.getElapsedTime()
    coreRef.current.rotation.y = t * 0.4
    coreRef.current.scale.setScalar(pulse(t) * intensity)
  })

  return (
    <Float speed={2} floatIntensity={1.5}>
      <mesh ref={coreRef}>
        <icosahedronGeometry args={[1, 4]} />
        <MeshDistortMaterial color={glowColor} distort={0.35} speed={2} />
      </mesh>
    </Float>
  )
}
""",
    "src/3d/HolographicRings.jsx": """import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'

export default function HolographicRings({ count = 3 }) {
  const group = useRef()
  useFrame((_, delta) => {
    group.current.rotation.z += delta * 0.2
  })
  return (
    <group ref={group}>
      {Array.from({ length: count }).map((_, i) => (
        <mesh key={i} rotation={[Math.PI / 2, 0, 0]} scale={1.5 + i * 0.4}>
          <torusGeometry args={[1, 0.01, 16, 100]} />
          <meshBasicMaterial color="#8fa8ff" transparent opacity={0.5} />
        </mesh>
      ))}
    </group>
  )
}
""",
    "src/3d/Particles.jsx": """import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

export default function Particles({ count = 500 }) {
  const points = useRef()
  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3)
    for (let i = 0; i < count * 3; i++) arr[i] = (Math.random() - 0.5) * 12
    return arr
  }, [count])

  useFrame((_, delta) => {
    points.current.rotation.y += delta * 0.03
  })

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={count} array={positions} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.02} color={new THREE.Color('#ffffff')} />
    </points>
  )
}
""",
    "src/components/Navbar.jsx": """import { useState } from 'react'

const Navbar = () => {
  const [open, setOpen] = useState(false)
  return (
    <nav className="navbar">
      <button onClick={() => setOpen(!open)}>Menu</button>
      {open && <ul><li>Home</li><li>About</li></ul>}
    </nav>
  )
}

export default Navbar
""",
    "src/components/Hero.jsx": """import { useEffect, useRef } from 'react'
import gsap from 'gsap'
import useScrollProgress from '../hooks/useScrollProgress'

export default function Hero({ title }) {
  const ref = useRef()
  const progress = useScrollProgress()

  useEffect(() => {
    gsap.from(ref.current, { y: 40, opacity: 0, duration: 1 })
  }, [])

  return <h1 ref={ref} className="glow" data-progress={progress}>{title}</h1>
}
""",
    "src/hooks/useScrollProgress.js": """import { useEffect, useState } from 'react'

export default function useScrollProgress() {
  const [progress, setProgress] = useState(0)
  useEffect(() => {
    const onScroll = () => setProgress(window.scrollY / document.body.scrollHeight)
    window.addEventListener('scroll', onScroll)
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  return progress
}
""",
    "src/utils/math.js": """export function pulse(t) {
  return 1 + Math.sin(t * 2) * 0.08
}

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
""",
}

FASTAPI_APP = {
    "README.md": """# Inventory API

A small inventory service built with FastAPI.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```
""",
    "requirements.txt": "fastapi>=0.110\nuvicorn[standard]>=0.29\nsqlalchemy>=2.0\npydantic>=2.6\npytest>=8.0\n",
    "Dockerfile": """FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
    ".env": "SECRET_KEY=super-secret-value-do-not-leak\nDATABASE_URL=postgresql://admin:hunter2pass@db:5432/inv\n",
    "app/__init__.py": "",
    "app/config.py": '''"""Application settings."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./inventory.db")
API_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"
password = "hunter2-hardcoded"
''',
    "app/db.py": '''"""Database engine and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
''',
    "app/models.py": '''"""ORM models."""
from sqlalchemy import Column, Integer, String, Float

from app.db import Base


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
''',
    "app/services/__init__.py": "",
    "app/services/pricing.py": '''"""Pricing rules for inventory items."""


def apply_discount(price: float, percent: float) -> float:
    """Return price reduced by ``percent`` percent."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round(price * (1 - percent / 100), 2)
''',
    "app/routers/__init__.py": "",
    "app/routers/items.py": '''"""HTTP endpoints for inventory items."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Item
from app.services.pricing import apply_discount

router = APIRouter(prefix="/items", tags=["items"])


@router.get("")
def list_items(db: Session = Depends(get_db)):
    """List all items."""
    return db.query(Item).all()


@router.get("/{item_id}/discounted")
def discounted(item_id: int, percent: float = 10, db: Session = Depends(get_db)):
    """Return an item's price after a discount."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    return {"price": apply_discount(item.price, percent)}
''',
    "app/main.py": '''"""Application entry point."""
from fastapi import FastAPI

from app.db import Base, engine
from app.routers import items

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Inventory API")
app.include_router(items.router)


@app.get("/health")
def health():
    return {"status": "ok"}
''',
    "tests/test_pricing.py": '''from app.services.pricing import apply_discount


def test_discount():
    assert apply_discount(100, 10) == 90
''',
}


def build_zip(files: dict, root: str = "") -> io.BytesIO:
    """Build an in-memory ZIP from a {path: text} mapping (optionally under a wrapper folder)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(f"{root}/{path}" if root else path, content)
    buf.seek(0)
    return buf
