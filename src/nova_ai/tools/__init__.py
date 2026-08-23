"""Tools primitive — tool system with ABC interface and built-in tools."""

from __future__ import annotations

from nova_ai.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# Import built-in tools to trigger @ToolRegistry.register() decorators.
# Each is wrapped in try/except so the package loads even before the
# individual tool modules are created.
try:
    import nova_ai.tools.calculator  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.think  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.retrieval  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.llm_tool  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.file_read  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.web_search  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.code_interpreter  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.code_interpreter_docker  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.repl  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.storage_tools  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.mcp_adapter  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.channel_tools  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.http_request  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.docker_shell_exec  # noqa: F401
    import nova_ai.tools.shell_exec  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.memory_manage  # noqa: F401
except ImportError:
    pass
try:
    import nova_ai.tools.user_profile_manage  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.skill_manage  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.file_write  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.apply_patch  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.git_tool  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.db_query  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.pdf_tool  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.image_tool  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.audio_tool  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.knowledge_tools  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.text_to_speech  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.digest_collect  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.screen_capture  # noqa: F401
    import nova_ai.tools.screen_monitor  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.canvas_tool  # noqa: F401
    import nova_ai.tools.cisco_packet_tracer  # noqa: F401
    import nova_ai.tools.cli_bridge  # noqa: F401
    import nova_ai.tools.doc_generator  # noqa: F401
    import nova_ai.tools.memory_wiki_tools  # noqa: F401
    import nova_ai.tools.web_readability  # noqa: F401
except ImportError:
    pass

try:
    import nova_ai.tools.api_tester  # noqa: F401
    import nova_ai.tools.code_scaffolder  # noqa: F401
    import nova_ai.tools.data_analyzer  # noqa: F401
    import nova_ai.tools.file_converter  # noqa: F401
    import nova_ai.tools.git_manager  # noqa: F401
    import nova_ai.tools.scheduler_tool  # noqa: F401
    import nova_ai.tools.system_monitor  # noqa: F401
except ImportError:
    pass

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
