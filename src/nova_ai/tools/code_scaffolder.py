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
    """Generate complete project structures from templates."""

    tool_id = "code_scaffolder"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="code_scaffolder",
            description=(
                "Generate full project structures from starter templates. "
                "Supports: Python package, FastAPI app, React + TypeScript app, CLI tool. "
                "Creates all files, directories, configs, and tests."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "template": {
                        "type": "string",
                        "enum": list(TEMPLATES.keys()),
                        "description": "Project template to use.",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Name of the project.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Short project description.",
                        "default": "A new project scaffolded by NOVA AI",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Base directory where the project folder will be created.",
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
        tmpl = TEMPLATES.get(template)
        if not tmpl:
            return ToolResult(
                tool_name="code_scaffolder",
                content=f"Unknown template: {template}. Available: {', '.join(TEMPLATES.keys())}",
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


__all__ = ["CodeScaffolderTool"]
