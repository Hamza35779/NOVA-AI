# -*- mode: python ; coding: utf-8 -*-
#
# ONEDIR build (not --onefile).
#
# One-file builds crash on Windows at startup with
#   "Failed to extract _polars_runtime_32\_polars_runtime.pyd: decompression
#    resulted in return code -1"
# — the deep onefile temp-extraction paths hit the same MAX_PATH /
# decompression failure that pushed CI (release.yml) to onedir. The empty
# console that flashed for a few seconds and closed was the bootloader
# dying mid-extraction. Onedir ships files on disk; nothing extracts at
# runtime.

a = Analysis(
    ['src/nova_ai/cli/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        # Ship the whole package source as data: prompts, configs, and
        # server/static (the web workstation UI) are read via
        # Path(__file__).parent at runtime — app.pyc lands next to them in
        # _internal/nova_ai/, so the frozen server finds its UI and assets.
        ('src/nova_ai', 'nova_ai'),
    ],
    hiddenimports=[
        'nova_ai.engine.ollama',
        'nova_ai.engine.openai_compat_engines',
        'nova_ai.engine.gguf',
        'nova_ai.server.app',
        'nova_ai.server.gguf_hub_router',
        'nova_ai.server.model_hub_router',
        'nova_ai.server.chat_history_store',
        'nova_ai.security',
        'nova_ai.notifications.notifier',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'httpx',
        'rich',
        'click',
        'anyio._backends._asyncio',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'unittest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='nova-ai-windows-x64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX corrupts some VC-runtime pyd/dlls and triggers antivirus false
    # positives; keep it off for the shipped artifact.
    upx=False,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['frontend/src-tauri/icons/icon.ico'],
    version_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='nova-ai-windows-x64',
)
