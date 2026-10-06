"""Tests for the code_scaffolder desktop templates (tauri_app, electron_app)."""

from __future__ import annotations

import json

from nova_ai.tools.code_scaffolder import TEMPLATES, CodeScaffolderTool, _slugify

_FORMAT_NAMES = {"name": "Demo App", "name_snake": "demo_app", "name_kebab": "demo-app"}


def _names_for(project_name: str) -> dict:
    names = _slugify(project_name)
    names["description"] = "A demo project"
    return names


class TestScaffolderSpec:
    def test_spec_lists_new_templates(self):
        tool = CodeScaffolderTool()
        assert "tauri_app" in tool.spec.description
        assert "electron_app" in tool.spec.description

    def test_templates_dict_contains_new_keys(self):
        assert "tauri_app" in TEMPLATES
        assert "electron_app" in TEMPLATES

    def test_unknown_template(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="qt_app",
            project_name="Demo",
            output_dir=str(tmp_path),
        )
        assert result.success is False
        assert "Unknown template" in result.content
        assert "tauri_app" in result.content


class TestTauriTemplate:
    def test_scaffold_tauri_app(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="tauri_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        project = tmp_path / "demo_app"
        expected = [
            "package.json",
            "index.html",
            "src/main.tsx",
            "src/App.tsx",
            "vite.config.ts",
            "src-tauri/Cargo.toml",
            "src-tauri/build.rs",
            "src-tauri/src/main.rs",
            "src-tauri/tauri.conf.json",
            "README.md",
        ]
        for rel in expected:
            assert (project / rel).is_file(), f"missing {rel}"

    def test_tauri_conf_json_is_valid_with_devurl(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="tauri_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        conf = json.loads(
            (tmp_path / "demo_app" / "src-tauri" / "tauri.conf.json").read_text(
                encoding="utf-8"
            )
        )
        assert conf["build"]["devUrl"] == "http://localhost:1420"
        assert conf["build"]["beforeDevCommand"] == "npm run dev"
        assert conf["build"]["frontendDist"] == "../dist"
        # Reverse-DNS identifier must not contain underscores.
        assert "_" not in conf["identifier"]

    def test_tauri_main_rs_has_working_command(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="tauri_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        main_rs = (
            tmp_path / "demo_app" / "src-tauri" / "src" / "main.rs"
        ).read_text(encoding="utf-8")
        assert "#[tauri::command]" in main_rs
        assert "invoke_handler" in main_rs
        assert "generate_handler![greet]" in main_rs

    def test_tauri_package_json_is_valid(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="tauri_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        pkg = json.loads(
            (tmp_path / "demo_app" / "package.json").read_text(encoding="utf-8")
        )
        assert pkg["dependencies"]["@tauri-apps/api"].startswith("^2")
        assert "tauri" in pkg["scripts"]

    def test_tauri_cargo_toml_declares_tauri_2(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="tauri_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        cargo = (
            tmp_path / "demo_app" / "src-tauri" / "Cargo.toml"
        ).read_text(encoding="utf-8")
        assert 'tauri = { version = "2"' in cargo
        assert "tauri-build" in cargo


class TestElectronTemplate:
    def test_scaffold_electron_app(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="electron_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        project = tmp_path / "demo_app"
        expected = [
            "package.json",
            "electron/main.ts",
            "electron/preload.ts",
            "src/types/global.d.ts",
            "src/main.tsx",
            "src/App.tsx",
            "vite.config.ts",
            "tsconfig.json",
            "tsconfig.electron.json",
            "README.md",
        ]
        for rel in expected:
            assert (project / rel).is_file(), f"missing {rel}"

    def test_electron_main_has_isolated_ipc_handler(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="electron_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        main_ts = (
            tmp_path / "demo_app" / "electron" / "main.ts"
        ).read_text(encoding="utf-8")
        assert "contextIsolation: true" in main_ts
        assert "nodeIntegration: false" in main_ts
        assert "ipcMain.handle('greet'" in main_ts

    def test_electron_preload_exposes_typed_bridge(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="electron_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        preload = (
            tmp_path / "demo_app" / "electron" / "preload.ts"
        ).read_text(encoding="utf-8")
        assert "contextBridge.exposeInMainWorld" in preload
        assert "novaApi" in preload
        assert "ipcRenderer.invoke('greet'" in preload

    def test_electron_renderer_typing(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="electron_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        global_dts = (
            tmp_path / "demo_app" / "src" / "types" / "global.d.ts"
        ).read_text(encoding="utf-8")
        assert "novaApi" in global_dts

    def test_electron_package_json_is_valid(self, tmp_path):
        tool = CodeScaffolderTool()
        result = tool.execute(
            template="electron_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is True
        pkg = json.loads(
            (tmp_path / "demo_app" / "package.json").read_text(encoding="utf-8")
        )
        assert pkg["main"] == "dist-electron/main.js"
        assert pkg["devDependencies"]["electron"].startswith("^30")


class TestTemplateRendering:
    def test_all_templates_render_without_format_errors(self):
        # Every template must render for a multi-word project name: a
        # KeyError here means a stray unescaped brace in a template body.
        for template_name, template in TEMPLATES.items():
            names = _names_for("Demo App")
            names["description"] = "A demo project"
            for rel_path, content in template["files"].items():
                rendered_path = rel_path.format(**names)
                assert rendered_path, template_name
                rendered = content.format(**names)
                assert rendered is not None, f"{template_name}/{rel_path}"

    def test_all_json_template_files_parse(self):
        for template_name, template in TEMPLATES.items():
            names = _names_for("Demo App")
            names["description"] = "A demo project"
            for rel_path, content in template["files"].items():
                if rel_path.endswith(".json"):
                    rendered = content.format(**names)
                    json.loads(rendered)

    def test_existing_project_dir_rejected(self, tmp_path):
        tool = CodeScaffolderTool()
        tool.execute(
            template="tauri_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        result = tool.execute(
            template="tauri_app",
            project_name="Demo App",
            output_dir=str(tmp_path),
        )
        assert result.success is False
        assert "already exists" in result.content
