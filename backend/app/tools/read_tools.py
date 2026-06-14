"""Read-only Zoho Projects tools for the QueryAgent."""

import logging

from langchain_core.tools import tool

from app.services.zoho_client import ZohoClient

logger = logging.getLogger(__name__)


def make_read_tools(client: ZohoClient, portal_id: str) -> list:
    """Create read tools bound to a specific ZohoClient and portal."""

    @tool
    async def list_projects() -> list[dict]:
        """List all active Zoho Projects for the current user."""
        logger.info("Executing tool: list_projects (portal_id=%s)", portal_id)
        result = await client.get_projects(portal_id)
        logger.info("Tool result: list_projects returned %d projects", len(result))
        return result

    @tool
    async def list_tasks(project_id: str, status: str = "", assignee: str = "") -> list[dict]:
        """List tasks for a project. Optionally filter by status or assignee."""
        logger.info(
            "Executing tool: list_tasks (project_id=%s, status=%r, assignee=%r)",
            project_id, status, assignee,
        )
        filters = {}
        if status:
            filters["status"] = status
        if assignee:
            filters["person_responsible"] = assignee
        result = await client.get_tasks(portal_id, project_id, **filters)
        logger.info("Tool result: list_tasks returned %d tasks", len(result))
        return result

    @tool
    async def get_task_details(project_id: str, task_id: str) -> dict:
        """Get full details for a specific task."""
        logger.info(
            "Executing tool: get_task_details (project_id=%s, task_id=%s)",
            project_id, task_id,
        )
        result = await client.get_task(portal_id, project_id, task_id)
        logger.info("Tool result: get_task_details -> %s", str(result)[:300])
        return result

    @tool
    async def list_project_members(project_id: str) -> list[dict]:
        """Get all members of a project with their roles."""
        logger.info("Executing tool: list_project_members (project_id=%s)", project_id)
        result = await client.get_project_members(portal_id, project_id)
        logger.info("Tool result: list_project_members returned %d members", len(result))
        return result

    @tool
    async def get_task_utilisation(project_id: str) -> list[dict]:
        """Summarise task count per member for a project."""
        logger.info("Executing tool: get_task_utilisation (project_id=%s)", project_id)
        tasks = await client.get_tasks(portal_id, project_id)
        usage: dict[str, dict] = {}
        for task in tasks:
            assignee = (
                task.get("details", {}).get("owners", [{}])[0].get("name", "Unassigned")
            )
            if assignee not in usage:
                usage[assignee] = {"member": assignee, "task_count": 0, "tasks": []}
            usage[assignee]["task_count"] += 1
            usage[assignee]["tasks"].append({"id": task.get("id"), "name": task.get("name")})
        result = list(usage.values())
        logger.info("Tool result: get_task_utilisation -> %d members", len(result))
        return result

    tools = [list_projects, list_tasks, get_task_details, list_project_members, get_task_utilisation]
    logger.info("Registered read tools: %s", [t.name for t in tools])
    return tools
