"""FastAPI router for application and software integrations (/v1/integrations)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nova_ai.cli.integrations_cmd import (
    APP_CATALOG,
    _load_user_integrations,
    _save_user_integrations,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])

# Actions currently supported by the dispatch endpoint.
SUPPORTED_ACTIONS = {"execute"}


class ToggleIntegrationRequest(BaseModel):
    enabled: bool


class IntegrationActionRequest(BaseModel):
    app_id: str
    action: str
    params: Dict[str, Any] = {}


def _find_app(app_id: str) -> Optional[Dict[str, str]]:
    """Look up an app by ID across all categories."""
    for apps in APP_CATALOG.values():
        for app in apps:
            if app["id"] == app_id:
                return app
    return None


@router.get("")
def get_integrations() -> Dict[str, Any]:
    """Retrieve full catalog of software and apps with user-enabled states."""
    user_config = _load_user_integrations()
    catalog_list = []

    for cat_name, apps in APP_CATALOG.items():
        cat_apps = []
        for a in apps:
            app_id = a["id"]
            is_enabled = user_config.get(app_id, {}).get("enabled", False)
            cat_apps.append(
                {
                    "id": app_id,
                    "name": a["name"],
                    "description": a["desc"],
                    "status": a["status"],
                    "enabled": is_enabled,
                }
            )
        catalog_list.append({"category": cat_name, "apps": cat_apps})

    return {
        "categories": catalog_list,
        "total_apps": sum(len(c["apps"]) for c in catalog_list),
    }


@router.post("/{app_id}/toggle")
def toggle_integration(app_id: str, req: ToggleIntegrationRequest) -> Dict[str, Any]:
    """Enable or disable a specific app integration."""
    app_id = app_id.lower().replace("-", "_")
    found_app = _find_app(app_id)

    if not found_app:
        raise HTTPException(
            status_code=404, detail=f"Integration '{app_id}' not found."
        )

    data = _load_user_integrations()
    data[app_id] = {"enabled": req.enabled, "name": found_app["name"]}
    _save_user_integrations(data)

    return {
        "app_id": app_id,
        "name": found_app["name"],
        "enabled": req.enabled,
        "message": f"{'Enabled' if req.enabled else 'Disabled'} integration with {found_app['name']}.",
    }


@router.post("/action")
def run_integration_action(req: IntegrationActionRequest) -> Dict[str, Any]:
    """Dispatch an automated task/action to an integration."""
    app_id = req.app_id.lower().replace("-", "_")
    action = req.action.lower()

    # Validate the requested action is supported
    if action not in SUPPORTED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported action '{req.action}'. Supported actions: {', '.join(sorted(SUPPORTED_ACTIONS))}.",
        )

    # Verify integration exists
    found = _find_app(app_id)
    if not found:
        logger.warning("Action requested on unknown integration: %s", app_id)
        raise HTTPException(
            status_code=404, detail=f"Integration '{app_id}' not found."
        )

    # Integration must be enabled before actions are dispatched
    user_config = _load_user_integrations()
    if not user_config.get(app_id, {}).get("enabled", False):
        logger.warning("Action requested on disabled integration: %s", app_id)
        raise HTTPException(
            status_code=400,
            detail=f"Integration '{app_id}' is disabled. Enable it first via POST /v1/integrations/{app_id}/toggle.",
        )

    logger.info("Dispatching action '%s' to integration '%s'", action, app_id)

    try:
        if app_id == "cisco_packet_tracer":
            from nova_ai.tools.cisco_packet_tracer import CiscoPacketTracerTool

            tool = CiscoPacketTracerTool()
            project_name = req.params.get("project_name", "Demo_Network")
            topology = req.params.get("topology_type", "multi_router_ospf")
            res = tool.execute(project_name=project_name, topology_type=topology)
            return {
                "success": res.success,
                "content": res.content,
                "metadata": res.metadata,
            }

        elif app_id == "document_generator":
            from nova_ai.tools.doc_generator import DocumentGeneratorTool

            tool = DocumentGeneratorTool()
            # Validate required params before passing
            required = {"doc_type", "title", "filename"}
            missing = required - set(req.params.keys())
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required params: {', '.join(missing)}",
                )
            safe_params = {
                k: v
                for k, v in req.params.items()
                if k
                in ("doc_type", "title", "filename", "sections_or_slides", "output_dir")
            }
            res = tool.execute(**safe_params)
            return {
                "success": res.success,
                "content": res.content,
                "metadata": res.metadata,
            }

        elif app_id in ("claude", "gemini", "opencode", "codex", "aider"):
            from nova_ai.tools.cli_bridge import CLIBridgeTool

            tool = CLIBridgeTool()
            prompt = req.params.get("prompt", "Analyze repository")
            flags = req.params.get("flags", [])
            res = tool.execute(cli_name=app_id, prompt=prompt, flags=flags)
            return {
                "success": res.success,
                "content": res.content,
                "metadata": res.metadata,
            }

        elif app_id == "data_analyzer":
            from nova_ai.tools.data_analyzer import DataAnalyzerTool

            tool = DataAnalyzerTool()
            res = tool.execute(
                file_path=req.params.get("file_path"),
                raw_data=req.params.get("raw_data"),
                query=req.params.get("query", ""),
            )
            return {
                "success": res.success,
                "content": res.content,
                "metadata": res.metadata,
            }

        elif app_id == "system_monitor":
            from nova_ai.tools.system_monitor import SystemMonitorTool

            tool = SystemMonitorTool()
            res = tool.execute(
                include_processes=req.params.get("include_processes", False)
            )
            return {
                "success": res.success,
                "content": res.content,
                "metadata": res.metadata,
            }

        return {
            "success": True,
            "app_id": app_id,
            "action": action,
            "message": f"Action '{action}' dispatched to {app_id}.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Integration action failed for %s: %s", app_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Action failed: {e}")
