"""Code Scaffolder tool — generate full project structures, boilerplate, and starter templates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

# ── Project Templates ──────────────────────────────────────────

TEMPLATES = {
    "python_package": {
        "description": "Python package with src layout, tests, pyproject.toml",
        "files": {
            "pyproject.toml": """[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "{name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.10"
license = {{text = "MIT"}}

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "src/{name_snake}/__init__.py": '"""Top-level package for {name}."""\n\n__version__ = "0.1.0"\n',
            "src/{name_snake}/main.py": '"""Main entry point."""\n\n\ndef main() -> None:\n    print("Hello from {name}!")\n\n\nif __name__ == "__main__":\n    main()\n',
            "tests/__init__.py": "",
            "tests/test_main.py": '''"""Basic tests for {name}."""\n\nimport pytest\n\n\ndef test_import():\n    import {name_snake}\n    assert {name_snake}.__version__ == "0.1.0"\n''',
            "README.md": "# {name}\n\n{description}\n\n## Installation\n\n```bash\npip install -e .\n```\n\n## Usage\n\n```bash\npython -m {name_snake}.main\n```\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\ndist/\n*.egg-info/\n.pytest_cache/\n",
        },
    },
    "fastapi_app": {
        "description": "FastAPI web application with routes, models, and tests",
        "files": {
            "app/__init__.py": "",
            "app/main.py": '''"""FastAPI application."""\n\nfrom fastapi import FastAPI\n\napp = FastAPI(title="{name}", version="0.1.0")\n\n\n@app.get("/")\ndef root():\n    return {{"message": "Welcome to {name}"}}\n\n\n@app.get("/health")\ndef health():\n    return {{"status": "ok"}}\n''',
            "app/models.py": '"""Pydantic data models."""\n\nfrom pydantic import BaseModel\n\n\nclass Item(BaseModel):\n    name: str\n    description: str = ""\n    price: float\n',
            "app/routes/__init__.py": "",
            "app/routes/items.py": '''"""Item routes."""\n\nfrom fastapi import APIRouter\n\nrouter = APIRouter(prefix="/items", tags=["items"])\n\n\n@router.get("")\ndef list_items():\n    return []\n''',
            "requirements.txt": "fastapi>=0.100\nuvicorn[standard]>=0.23\npydantic>=2.0\n",
            "tests/__init__.py": "",
            "tests/test_app.py": '''"""API tests."""\n\nfrom fastapi.testclient import TestClient\nfrom app.main import app\n\nclient = TestClient(app)\n\n\ndef test_root():\n    resp = client.get("/")\n    assert resp.status_code == 200\n\n\ndef test_health():\n    resp = client.get("/health")\n    assert resp.json()["status"] == "ok"\n''',
            "README.md": "# {name}\n\n{description}\n\n## Run\n\n```bash\nuvicorn app.main:app --reload\n```\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\n",
        },
    },
    "react_app": {
        "description": "React + TypeScript starter with Vite",
        "files": {
            "package.json": """{{\n  "name": "{name_kebab}",\n  "private": true,\n  "version": "0.1.0",\n  "scripts": {{\n    "dev": "vite",\n    "build": "tsc && vite build",\n    "preview": "vite preview"\n  }},\n  "dependencies": {{\n    "react": "^18.2.0",\n    "react-dom": "^18.2.0"\n  }},\n  "devDependencies": {{\n    "@types/react": "^18.2.0",\n    "@types/react-dom": "^18.2.0",\n    "typescript": "^5.0.0",\n    "vite": "^5.0.0",\n    "@vitejs/plugin-react": "^4.0.0"\n  }}\n}}\n""",
            "index.html": """<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n  <title>{name}</title>\n</head>\n<body>\n  <div id="root"></div>\n  <script type="module" src="/src/main.tsx"></script>\n</body>\n</html>\n""",
            "src/main.tsx": "import React from 'react';\nimport ReactDOM from 'react-dom/client';\nimport App from './App';\n\nReactDOM.createRoot(document.getElementById('root')!).render(\n  <React.StrictMode>\n    <App />\n  </React.StrictMode>\n);\n",
            "src/App.tsx": "function App() {{\n  return (\n    <div style={{{{ padding: '2rem', fontFamily: 'system-ui' }}}}>\n      <h1>{name}</h1>\n      <p>{description}</p>\n    </div>\n  );\n}}\n\nexport default App;\n",
            "tsconfig.json": '{{\n  "compilerOptions": {{\n    "target": "ES2020",\n    "module": "ESNext",\n    "jsx": "react-jsx",\n    "strict": true,\n    "moduleResolution": "bundler"\n  }},\n  "include": ["src"]\n}}\n',
            "vite.config.ts": "import {{ defineConfig }} from 'vite';\nimport react from '@vitejs/plugin-react';\n\nexport default defineConfig({{\n  plugins: [react()],\n}});\n",
            "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\nnpm install\nnpm run dev\n```\n",
            ".gitignore": "node_modules/\ndist/\n.env\n",
        },
    },
    "cli_tool": {
        "description": "Python CLI tool with Click, rich output",
        "files": {
            "pyproject.toml": """[build-system]\nrequires = ["setuptools>=68.0"]\nbuild-backend = "setuptools.backends._legacy:_Backend"\n\n[project]\nname = "{name_kebab}"\nversion = "0.1.0"\ndescription = "{description}"\nrequires-python = ">=3.10"\ndependencies = ["click>=8.0", "rich>=13.0"]\n\n[project.scripts]\n{name_kebab} = "{name_snake}.cli:main"\n""",
            "{name_snake}/__init__.py": '__version__ = "0.1.0"\n',
            "{name_snake}/cli.py": '''"""CLI entry point."""\n\nimport click\nfrom rich.console import Console\n\nconsole = Console()\n\n\n@click.group()\n@click.version_option()\ndef main():\n    """{name} — {description}"""\n    pass\n\n\n@main.command()\n@click.argument("name", default="World")\ndef hello(name: str):\n    """Say hello."""\n    console.print(f"[bold green]Hello, {{name}}![/bold green]")\n\n\nif __name__ == "__main__":\n    main()\n''',
            "tests/test_cli.py": '''"""CLI tests."""\n\nfrom click.testing import CliRunner\nfrom {name_snake}.cli import main\n\n\ndef test_hello():\n    runner = CliRunner()\n    result = runner.invoke(main, ["hello"])\n    assert result.exit_code == 0\n    assert "Hello" in result.output\n''',
            "README.md": "# {name}\n\n{description}\n\n## Install\n\n```bash\npip install -e .\n```\n\n## Usage\n\n```bash\n{name_kebab} hello\n```\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\ndist/\n*.egg-info/\n",
        },
    },
    "rust_app": {
        "description": "Rust binary crate with Cargo.toml, src/main.rs, src/lib.rs, and tests",
        "files": {
            "Cargo.toml": "[package]\nname = \"{name_kebab}\"\nversion = \"0.1.0\"\nedition = \"2021\"\ndescription = \"{description}\"\n\n[dependencies]\nanyhow = \"1\"\nclap = {{ version = \"4\", features = [\"derive\"] }}\n",
            "src/main.rs": "//! {name} — {description}\n\nuse anyhow::Result;\nuse clap::Parser;\n\n#[derive(Parser, Debug)]\n#[command(name = \"{name_kebab}\", about = \"{description}\")]\nstruct Args {{\n    #[arg(short, long, default_value = \"World\")]\n    name: String,\n}}\n\nfn main() -> Result<()> {{\n    let args = Args::parse();\n    println!(\"Hello, {{}}! From {name}.\", args.name);\n    Ok(())\n}}\n",
            "src/lib.rs": "//! Library root for {name}.\n\npub fn greet(name: &str) -> String {{\n    format!(\"Hello, {{}}!\", name)\n}}\n\n#[cfg(test)]\nmod tests {{\n    use super::*;\n\n    #[test]\n    fn test_greet() {{\n        assert_eq!(greet(\"NOVA\"), \"Hello, NOVA!\");\n    }}\n}}\n",
            ".gitignore": "/target\nCargo.lock\n",
            "README.md": "# {name}\n\n{description}\n\n## Build & Run\n\n```bash\ncargo build --release\ncargo run -- --name NOVA\ncargo test\n```\n",
        },
    },
    "go_app": {
        "description": "Go module with cmd entry point, internal package, and tests",
        "files": {
            "go.mod": "module github.com/example/{name_kebab}\n\ngo 1.22\n",
            "main.go": "// {name} — {description}\npackage main\n\nimport \"fmt\"\n\nfunc main() {{\n\tfmt.Println(\"Hello from {name}!\")\n}}\n",
            "internal/{name_snake}/{name_snake}.go": "// Package {name_snake} provides core logic for {name}.\npackage {name_snake}\n\n// Greet returns a personalised greeting.\nfunc Greet(name string) string {{\n\treturn \"Hello, \" + name + \"! From {name}.\"\n}}\n",
            "internal/{name_snake}/{name_snake}_test.go": "package {name_snake}_test\n\nimport (\n\t\"testing\"\n\t\"{name_kebab}/internal/{name_snake}\"\n)\n\nfunc TestGreet(t *testing.T) {{\n\tgot := {name_snake}.Greet(\"NOVA\")\n\twant := \"Hello, NOVA! From {name}.\"\n\tif got != want {{\n\t\tt.Errorf(\"got %q, want %q\", got, want)\n\t}}\n}}\n",
            ".gitignore": "*.exe\n*.out\nvendor/\n",
            "README.md": "# {name}\n\n{description}\n\n## Run\n\n```bash\ngo run main.go\ngo test ./...\n```\n",
        },
    },
    "cpp_app": {
        "description": "Modern C++20 project with CMakeLists.txt, src, include, and unit tests",
        "files": {
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nproject({name_snake} VERSION 0.1.0 LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\nset(CMAKE_CXX_STANDARD_REQUIRED ON)\nadd_executable({name_snake} src/main.cpp src/{name_snake}.cpp)\ntarget_include_directories({name_snake} PRIVATE include)\nenable_testing()\nadd_executable(test_{name_snake} tests/test_{name_snake}.cpp src/{name_snake}.cpp)\ntarget_include_directories(test_{name_snake} PRIVATE include)\nadd_test(NAME {name_snake}_tests COMMAND test_{name_snake})\n",
            "include/{name_snake}.hpp": "#pragma once\n#include <string>\n\nnamespace {name_snake} {{\n\n/// Returns a greeting for the given name.\nstd::string greet(const std::string& name);\n\n}} // namespace {name_snake}\n",
            "src/{name_snake}.cpp": "#include \"{name_snake}.hpp\"\n\nnamespace {name_snake} {{\n\nstd::string greet(const std::string& name) {{\n    return \"Hello, \" + name + \"! From {name}.\";\n}}\n\n}} // namespace {name_snake}\n",
            "src/main.cpp": "// {name} — {description}\n#include <iostream>\n#include \"{name_snake}.hpp\"\n\nint main(int argc, char** argv) {{\n    std::string who = (argc > 1) ? argv[1] : \"World\";\n    std::cout << {name_snake}::greet(who) << std::endl;\n    return 0;\n}}\n",
            "tests/test_{name_snake}.cpp": "#include <cassert>\n#include <iostream>\n#include \"{name_snake}.hpp\"\n\nint main() {{\n    assert({name_snake}::greet(\"NOVA\") == \"Hello, NOVA! From {name}.\");\n    std::cout << \"All tests passed.\" << std::endl;\n    return 0;\n}}\n",
            ".gitignore": "build/\n*.o\n*.out\n",
            "README.md": "# {name}\n\n{description}\n\n## Build\n\n```bash\ncmake -B build && cmake --build build\n./build/{name_snake}\n```\n",
        },
    },
    "nodejs_ts": {
        "description": "Node.js + TypeScript Express backend with jest tests",
        "files": {
            "package.json": "{{\n  \"name\": \"{name_kebab}\",\n  \"version\": \"0.1.0\",\n  \"description\": \"{description}\",\n  \"main\": \"dist/index.js\",\n  \"scripts\": {{\n    \"build\": \"tsc\",\n    \"start\": \"node dist/index.js\",\n    \"dev\": \"ts-node src/index.ts\",\n    \"test\": \"jest --passWithNoTests\"\n  }},\n  \"dependencies\": {{ \"express\": \"^4.18.0\" }},\n  \"devDependencies\": {{\n    \"@types/express\": \"^4.17.21\",\n    \"@types/jest\": \"^29.5.0\",\n    \"@types/node\": \"^20.0.0\",\n    \"jest\": \"^29.7.0\",\n    \"ts-jest\": \"^29.1.0\",\n    \"ts-node\": \"^10.9.0\",\n    \"typescript\": \"^5.4.0\"\n  }}\n}}\n",
            "tsconfig.json": "{{\n  \"compilerOptions\": {{\n    \"target\": \"ES2022\",\n    \"module\": \"commonjs\",\n    \"outDir\": \"dist\",\n    \"rootDir\": \"src\",\n    \"strict\": true,\n    \"esModuleInterop\": true\n  }},\n  \"include\": [\"src\"]\n}}\n",
            "src/index.ts": "import express, {{ Request, Response }} from 'express';\n\nconst app = express();\nconst PORT = process.env.PORT ?? 3000;\n\napp.use(express.json());\n\napp.get('/', (_req: Request, res: Response) => {{\n    res.json({{ message: 'Welcome to {name}', version: '0.1.0' }});\n}});\n\napp.get('/health', (_req: Request, res: Response) => {{\n    res.json({{ status: 'ok' }});\n}});\n\napp.listen(PORT, () => console.log(`{name} running on http://localhost:${{PORT}}`));\n\nexport default app;\n",
            "src/utils.ts": "/** Returns a greeting string. */\nexport function greet(name: string): string {{\n    return `Hello, ${{name}}! From {name}.`;\n}}\n",
            "tests/utils.test.ts": "import {{ greet }} from '../src/utils';\n\ndescribe('greet', () => {{\n    it('returns correct greeting', () => {{\n        expect(greet('NOVA')).toBe('Hello, NOVA! From {name}.');\n    }});\n}});\n",
            ".gitignore": "node_modules/\ndist/\n.env\n",
            "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\nnpm install\nnpm run dev\nnpm test\n```\n",
        },
    },
    "django_app": {
        "description": "Django web project with app, models, views, and URL config",
        "files": {
            "manage.py": "#!/usr/bin/env python\n\"\"\"Django management entry point.\"\"\"\nimport os, sys\n\ndef main():\n    os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{name_snake}.settings')\n    from django.core.management import execute_from_command_line\n    execute_from_command_line(sys.argv)\n\nif __name__ == '__main__':\n    main()\n",
            "{name_snake}/settings.py": "from pathlib import Path\nBASE_DIR = Path(__file__).resolve().parent.parent\nSECRET_KEY = 'change-me-in-production'\nDEBUG = True\nALLOWED_HOSTS = ['*']\nINSTALLED_APPS = [\n    'django.contrib.admin', 'django.contrib.auth',\n    'django.contrib.contenttypes', 'django.contrib.sessions',\n    'django.contrib.messages', 'django.contrib.staticfiles', 'core',\n]\nDATABASES = {{\n    'default': {{\n        'ENGINE': 'django.db.backends.sqlite3',\n        'NAME': BASE_DIR / 'db.sqlite3',\n    }}\n}}\nSTATIC_URL = '/static/'\nDEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'\n",
            "{name_snake}/urls.py": "from django.contrib import admin\nfrom django.urls import path, include\n\nurlpatterns = [\n    path('admin/', admin.site.urls),\n    path('', include('core.urls')),\n]\n",
            "{name_snake}/__init__.py": "",
            "{name_snake}/wsgi.py": "import os\nfrom django.core.wsgi import get_wsgi_application\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', '{name_snake}.settings')\napplication = get_wsgi_application()\n",
            "core/__init__.py": "",
            "core/models.py": "from django.db import models\n\nclass Item(models.Model):\n    name = models.CharField(max_length=200)\n    description = models.TextField(blank=True)\n    created_at = models.DateTimeField(auto_now_add=True)\n\n    def __str__(self) -> str:\n        return self.name\n",
            "core/views.py": "from django.http import JsonResponse\nfrom django.views import View\n\nclass HealthView(View):\n    def get(self, request):\n        return JsonResponse({{\"status\": \"ok\", \"app\": \"{name}\"}})\n",
            "core/urls.py": "from django.urls import path\nfrom .views import HealthView\n\nurlpatterns = [\n    path('health/', HealthView.as_view(), name='health'),\n]\n",
            "requirements.txt": "django>=4.2\n",
            ".gitignore": "*.pyc\n__pycache__/\n.venv/\ndb.sqlite3\n",
            "README.md": "# {name}\n\n{description}\n\n## Run\n\n```bash\npip install -r requirements.txt\npython manage.py migrate\npython manage.py runserver\n```\n",
        },
    },
    "flutter_app": {
        "description": "Flutter/Dart mobile app with basic widget structure and tests",
        "files": {
            "pubspec.yaml": "name: {name_snake}\ndescription: {description}\nversion: 0.1.0+1\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\ndependencies:\n  flutter:\n    sdk: flutter\n  cupertino_icons: ^1.0.8\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n  flutter_lints: ^4.0.0\nflutter:\n  uses-material-design: true\n",
            "lib/main.dart": "import 'package:flutter/material.dart';\nimport 'package:{name_snake}/app.dart';\n\nvoid main() => runApp(const {name}App());\n",
            "lib/app.dart": "import 'package:flutter/material.dart';\n\nclass {name}App extends StatelessWidget {{\n  const {name}App({{super.key}});\n\n  @override\n  Widget build(BuildContext context) {{\n    return MaterialApp(\n      title: '{name}',\n      home: const HomePage(),\n    );\n  }}\n}}\n\nclass HomePage extends StatelessWidget {{\n  const HomePage({{super.key}});\n\n  @override\n  Widget build(BuildContext context) {{\n    return Scaffold(\n      appBar: AppBar(title: const Text('{name}')),\n      body: const Center(\n        child: Text('Hello from {name}!', style: TextStyle(fontSize: 24)),\n      ),\n    );\n  }}\n}}\n",
            "test/widget_test.dart": "import 'package:flutter_test/flutter_test.dart';\nimport 'package:{name_snake}/app.dart';\n\nvoid main() {{\n  testWidgets('App renders title', (tester) async {{\n    await tester.pumpWidget(const {name}App());\n    expect(find.text('{name}'), findsOneWidget);\n  }});\n}}\n",
            ".gitignore": ".dart_tool/\nbuild/\n.flutter-plugins\n.packages\n",
            "README.md": "# {name}\n\n{description}\n\n## Run\n\n```bash\nflutter pub get\nflutter run\nflutter test\n```\n",
        },
    },
}


# ── Language Extension Mapping ─────────────────────────────────

_EXT_LANG: dict[str, str] = {
    ".py": "python", ".rs": "rust", ".go": "go",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".c": "c", ".hpp": "cpp", ".h": "c",
    ".java": "java", ".kt": "kotlin", ".swift": "swift",
    ".dart": "dart", ".rb": "ruby", ".php": "php",
    ".cs": "csharp", ".lua": "lua",
    ".sh": "bash", ".ps1": "powershell",
    ".sql": "sql", ".html": "html", ".css": "css",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".md": "markdown",
}

_FILE_STUBS: dict[str, str] = {
    "python": '"""Module: {name}.\n\n{description}\n"""\n\n\ndef main() -> None:\n    print("Hello from {name}!")\n\n\nif __name__ == "__main__":\n    main()\n',
    "rust": '//! {name} — {description}\n\nfn main() {{\n    println!("Hello from {name}!");\n}}\n',
    "go": '// {name} — {description}\npackage main\n\nimport "fmt"\n\nfunc main() {{\n\tfmt.Println("Hello from {name}!")\n}}\n',
    "typescript": '// {name} — {description}\n\nexport function greet(name: string): string {{\n    return `Hello, ${{name}}! From {name}.`;\n}}\n',
    "javascript": '// {name} — {description}\n\nfunction greet(name) {{\n    return `Hello, ${{name}}! From {name}.`;\n}}\n\nmodule.exports = {{ greet }};\n',
    "cpp": '#include <iostream>\n\n// {name} — {description}\n\nint main() {{\n    std::cout << "Hello from {name}!" << std::endl;\n    return 0;\n}}\n',
    "c": '#include <stdio.h>\n\n/* {name} — {description} */\n\nint main(void) {{\n    printf("Hello from {name}!\\n");\n    return 0;\n}}\n',
    "java": '// {name} — {description}\n\npublic class {name} {{\n    public static void main(String[] args) {{\n        System.out.println("Hello from {name}!");\n    }}\n}}\n',
    "kotlin": '// {name} — {description}\n\nfun main() {{\n    println("Hello from {name}!")\n}}\n',
    "swift": '// {name} — {description}\n\nimport Foundation\n\nprint("Hello from {name}!")\n',
    "dart": '// {name} — {description}\n\nvoid main() {{\n  print("Hello from {name}!");\n}}\n',
    "ruby": '# {name} — {description}\n\ndef greet(name)\n  "Hello, #{{name}}! From {name}."\nend\n\nputs greet("World")\n',
    "php": '<?php\n// {name} — {description}\n\nfunction greet(string $name): string {{\n    return "Hello, {{$name}}! From {name}.";\n}}\n\necho greet("World");\n',
    "csharp": '// {name} — {description}\n\nConsole.WriteLine("Hello from {name}!");\n',
    "lua": '-- {name} — {description}\n\nlocal function greet(name)\n    return string.format("Hello, %s! From {name}.", name)\nend\n\nprint(greet("World"))\n',
    "bash": '#!/usr/bin/env bash\n# {name} — {description}\n\nset -euo pipefail\n\nmain() {{\n    echo "Hello from {name}!"\n}}\n\nmain "$@"\n',
    "powershell": '# {name} — {description}\n\nfunction Invoke-Greet {{\n    param([string]$Name = "World")\n    Write-Host "Hello, $Name! From {name}."\n}}\n\nInvoke-Greet\n',
    "sql": '-- {name}\n-- {description}\n\nCREATE TABLE IF NOT EXISTS items (\n    id         INTEGER PRIMARY KEY AUTOINCREMENT,\n    name       TEXT NOT NULL,\n    created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n);\n\nSELECT * FROM items;\n',
    "html": '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n  <title>{name}</title>\n</head>\n<body>\n  <h1>{name}</h1>\n  <p>{description}</p>\n</body>\n</html>\n',
    "css": '/* {name} — {description} */\n\n:root {{\n  --primary: #7c3aed;\n  --bg: #0f0b1e;\n  --text: #f8fafc;\n}}\n\nbody {{\n  margin: 0;\n  font-family: system-ui, sans-serif;\n  background-color: var(--bg);\n  color: var(--text);\n}}\n',
    "json": '{{\n  "name": "{name}",\n  "version": "0.1.0",\n  "description": "{description}"\n}}\n',
    "yaml": 'name: {name}\nversion: "0.1.0"\ndescription: "{description}"\n',
    "toml": '[package]\nname = "{name_kebab}"\nversion = "0.1.0"\ndescription = "{description}"\n',
    "markdown": '# {name}\n\n> {description}\n\n## Overview\n\nAdd your content here.\n',
}


def _slugify(name: str) -> Dict[str, str]:
    """Generate name variants for template substitution."""
    snake = name.strip().lower().replace(" ", "_").replace("-", "_")
    snake = "".join(c for c in snake if c.isalnum() or c == "_")
    kebab = snake.replace("_", "-")
    return {
        "name": name.strip(),
        "name_snake": snake,
        "name_kebab": kebab,
    }


@ToolRegistry.register("code_scaffolder")
class CodeScaffolderTool(BaseTool):
    """Generate complete project structures from templates, or create individual source files."""

    tool_id = "code_scaffolder"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        all_templates = list(TEMPLATES.keys()) + ["file"]
        return ToolSpec(
            name="code_scaffolder",
            description=(
                "Generate full project structures from starter templates, OR create individual "
                "source files in any programming language. "
                "Project templates: python_package, fastapi_app, react_app, cli_tool, rust_app, "
                "go_app, cpp_app, nodejs_ts, django_app, flutter_app. "
                "Single-file mode: set template='file' and provide a filename with extension "
                "(.py, .rs, .go, .ts, .cpp, .java, .kt, .swift, .dart, .rb, .php, .cs, "
                ".lua, .sh, .ps1, .sql, .html, .css, .json, .yaml, .toml, .md, etc.)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "template": {
                        "type": "string",
                        "enum": all_templates,
                        "description": (
                            "Project template name, or 'file' to generate a single source file."
                        ),
                    },
                    "project_name": {
                        "type": "string",
                        "description": (
                            "Name of the project (for project templates), or the filename with "
                            "extension (e.g. 'main.py', 'server.go', 'app.rs') for single-file mode."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Short description embedded in file headers and README.",
                        "default": "A new project scaffolded by NOVA AI",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory where the project folder or single file will be written.",
                    },
                },
                "required": ["template", "project_name", "output_dir"],
            },
            category="development",
            timeout_seconds=15.0,
        )

    @track_execution("code_scaffolder")
    def execute(
        self,
        template: str,
        project_name: str,
        output_dir: str,
        description: str = "A new project scaffolded by NOVA AI",
        **kwargs: Any,
    ) -> ToolResult:
        # ── Single-file generation mode ──────────────────────────
        if template == "file":
            return self._generate_file(project_name, output_dir, description)

        # ── Full project scaffolding mode ─────────────────────────
        tmpl = TEMPLATES.get(template)
        if not tmpl:
            available = ", ".join(list(TEMPLATES.keys()) + ["file"])
            return ToolResult(
                tool_name="code_scaffolder",
                content=f"Unknown template: '{template}'. Available: {available}",
                success=False,
            )

        names = _slugify(project_name)
        names["description"] = description
        project_dir = Path(output_dir) / names["name_snake"]

        if project_dir.exists():
            return ToolResult(
                tool_name="code_scaffolder",
                content=f"Directory already exists: {project_dir}. Choose a different name or location.",
                success=False,
            )

        created_files = []
        try:
            for rel_path_template, content_template in tmpl["files"].items():
                rel_path = rel_path_template.format(**names)
                content = content_template.format(**names)
                file_path = project_dir / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")
                created_files.append(rel_path)

        except Exception as e:
            return ToolResult(
                tool_name="code_scaffolder",
                content=f"Scaffolding failed: {e}",
                success=False,
            )

        file_list = "\n".join(f"  📄 {f}" for f in created_files)
        return ToolResult(
            tool_name="code_scaffolder",
            content=(
                f"✅ Created {template} project '{project_name}' at {project_dir}\n\n"
                f"Files created ({len(created_files)}):\n{file_list}"
            ),
            success=True,
            metadata={
                "template": template,
                "project_name": project_name,
                "project_dir": str(project_dir),
                "files_created": len(created_files),
            },
        )

    def _generate_file(
        self,
        filename: str,
        output_dir: str,
        description: str,
    ) -> ToolResult:
        """Write a single source file with a language-appropriate starter stub."""
        file_path = Path(output_dir) / filename
        ext = Path(filename).suffix.lower()
        lang = _EXT_LANG.get(ext)

        if lang is None:
            supported = ", ".join(sorted(_EXT_LANG.keys()))
            return ToolResult(
                tool_name="code_scaffolder",
                content=(
                    f"Unsupported file extension '{ext}'. "
                    f"Supported extensions: {supported}"
                ),
                success=False,
            )

        stub_template = _FILE_STUBS.get(lang, "# {name}\n# {description}\n")
        names = _slugify(Path(filename).stem)
        names["description"] = description
        content = stub_template.format(**names)

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        return ToolResult(
            tool_name="code_scaffolder",
            content=(
                f"✅ Generated {lang} file: {file_path}\n\n"
                f"```{lang}\n{content}\n```"
            ),
            success=True,
            metadata={
                "template": "file",
                "language": lang,
                "filename": filename,
                "file_path": str(file_path),
            },
        )


__all__ = ["CodeScaffolderTool"]
