"""Write Zoho Projects tools for the ActionAgent."""

import logging
from typing import Optional

from langchain_core.tools import tool

from app.services.zoho_client import ZohoClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal validation helpers
# ---------------------------------------------------------------------------

async def _resolve_project_id(client: ZohoClient, portal_id: str, supplied: str) -> str:
    """Resolve a project name, key, or numeric ID to the Zoho numeric project ID.

    Returns the resolved ID string.
    Raises ValueError with a user-friendly message listing available projects if not found.
    """
    supplied_str = str(supplied).strip()

    if supplied_str.isdigit():
        logger.info("project_id '%s' is already numeric — no resolution needed", supplied_str)
        return supplied_str

    logger.info("Resolving project reference '%s' via Zoho API", supplied_str)
    projects = await client.get_projects(portal_id)

    # Check for Zoho-level error from the API
    if isinstance(projects, dict) and projects.get("error"):
        raise ValueError(f"Could not fetch projects: {projects['error'].get('message', 'unknown error')}")

    supplied_lower = supplied_str.lower()
    for project in projects:
        pid = str(project.get("id", project.get("id_string", "")))
        pname = str(project.get("name", "")).lower()
        pkey = str(project.get("key", "")).lower()
        if supplied_lower in (pid, pname, pkey):
            logger.info(
                "Resolved project reference '%s' -> '%s' (name=%r key=%r)",
                supplied_str, pid, project.get("name"), project.get("key"),
            )
            return pid

    available = [p.get("name") for p in projects if p.get("name")]
    raise ValueError(
        f"Project '{supplied}' not found. Available projects: {available}"
    )


async def _resolve_task_id(
    client: ZohoClient, portal_id: str, project_id: str, supplied: str
) -> str:
    """Resolve a task name or numeric ID to the Zoho numeric task ID.

    Returns the resolved task ID string.
    Raises ValueError with available task names if not found.
    """
    supplied_str = str(supplied).strip()

    logger.info("Resolving task reference '%s' in project '%s'", supplied_str, project_id)
    tasks = await client.get_tasks(portal_id, project_id)

    if isinstance(tasks, dict) and tasks.get("error"):
        raise ValueError(f"Could not fetch tasks: {tasks['error'].get('message', 'unknown error')}")

    supplied_lower = supplied_str.lower()
    for task in tasks:
        tid = str(task.get("id", task.get("id_string", "")))
        tname = str(task.get("name", "")).lower()
        if supplied_str == tid or supplied_lower == tname:
            logger.info("Resolved task reference '%s' -> '%s'", supplied_str, tid)
            return tid

    available = [t.get("name") for t in tasks if t.get("name")]
    raise ValueError(
        f"Task '{supplied}' not found in this project. "
        f"Available tasks: {available if available else '(none)'}"
    )


def _check_api_error(result: dict, operation: str) -> Optional[str]:
    """Return a human-friendly error string if result contains a Zoho error, else None."""
    if not isinstance(result, dict):
        return None
    err = result.get("error")
    if not err:
        return None
    if isinstance(err, dict):
        code = err.get("code", "")
        msg = err.get("message", str(err))
    else:
        code = ""
        msg = str(err)
    logger.error("%s API error code=%s message=%s", operation, code, msg)
    return f"⚠️ {operation} failed (code {code}): {msg}" if code else f"⚠️ {operation} failed: {msg}"


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def make_write_tools(client: ZohoClient, portal_id: str) -> list:
    """Create write tools bound to a specific ZohoClient and portal."""

    @tool
    async def create_task(
        project_id: str,
        name: str,
        assignee_id: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Create a new task in a Zoho project.

        project_id may be a numeric ID, project key (e.g. CH-1), or project name.
        assignee_id may be a name, email, or numeric zpuid — resolved automatically.
        Returns {"error": "..."} on failure instead of raising.
        """
        logger.info(
            "create_task validation: project_id=%s name=%r assignee_id=%s",
            project_id, name, assignee_id,
        )
        try:
            # 1. Validate and resolve project
            try:
                resolved_project = await _resolve_project_id(client, portal_id, project_id)
            except ValueError as exc:
                logger.warning("create_task: %s", exc)
                return {"error": str(exc)}

            # 2. Validate and resolve assignee (if provided)
            resolved_assignee: Optional[str] = None
            if assignee_id:
                try:
                    members = await client.get_project_members(portal_id, resolved_project)
                    if isinstance(members, dict) and members.get("error"):
                        logger.warning("create_task: could not fetch members — %s", members)
                    else:
                        needle = str(assignee_id).lower()
                        for member in members:
                            if (
                                needle == str(member.get("name", "")).lower()
                                or needle == str(member.get("email", "")).lower()
                                or needle == str(member.get("id", ""))
                                or needle == str(member.get("zpuid", ""))
                            ):
                                resolved_assignee = str(member["zpuid"])
                                logger.info(
                                    "Resolved assignee '%s' -> zpuid='%s'",
                                    assignee_id, resolved_assignee,
                                )
                                break
                        if not resolved_assignee:
                            available = [m.get("name") for m in members if m.get("name")]
                            logger.warning(
                                "create_task: assignee '%s' not found. Available: %s",
                                assignee_id, available,
                            )
                            return {
                                "error": (
                                    f"Assignee '{assignee_id}' not found in project. "
                                    f"Available members: {available}"
                                )
                            }
                except Exception:
                    logger.exception("create_task: assignee resolution failed")
                    # Non-fatal — proceed without assignee rather than failing entirely
                    resolved_assignee = None

            # 3. Build fields and execute
            fields: dict = {}
            if resolved_assignee:
                fields["person_responsible"] = resolved_assignee
            if due_date:
                fields["due_date"] = due_date
            if priority:
                fields["priority"] = priority
            if description:
                fields["description"] = description

            logger.info(
                "Executing create_task: project='%s' name=%r fields=%s",
                resolved_project, name, fields,
            )
            result = await client.create_task(portal_id, resolved_project, name, **fields)

            err_msg = _check_api_error(result, "create_task")
            if err_msg:
                return {"error": err_msg}

            logger.info("Tool result: create_task -> %s", result)
            return result

        except Exception:
            logger.exception("create_task: unexpected error")
            return {"error": "An unexpected error occurred while creating the task. Please try again."}

    @tool
    async def update_task(project_id: str, task_id: str, fields: dict) -> dict:
        """Update specific fields on an existing task.

        project_id may be a numeric ID, project key, or project name.
        task_id may be a numeric ID or task name — resolved automatically.
        If fields contains 'assignee_id', it is resolved to a Zoho zpuid and
        translated to 'person_responsible' before the API call.
        Returns {"error": "..."} on failure instead of raising.
        """
        logger.info(
            "update_task validation: project_id=%s task_id=%s fields=%s",
            project_id, task_id, fields,
        )
        try:
            # 1. Resolve project
            try:
                resolved_project = await _resolve_project_id(client, portal_id, project_id)
            except ValueError as exc:
                logger.warning("update_task: %s", exc)
                return {"error": str(exc)}

            # 2. Resolve task (verify it exists)
            try:
                resolved_task = await _resolve_task_id(
                    client, portal_id, resolved_project, task_id
                )
            except ValueError as exc:
                logger.warning("update_task: %s", exc)
                return {"error": str(exc)}

            # 3. Resolve assignee if provided.
            #    The LLM puts the display name in fields["assignee_id"].
            #    Zoho's Update Task API requires the field to be named
            #    "person_responsible" and its value to be a numeric zpuid (Long).
            send_fields = dict(fields)
            raw_assignee = send_fields.pop("assignee_id", None)
            if raw_assignee:
                logger.info(
                    "update_task: resolving assignee '%s' for project '%s'",
                    raw_assignee, resolved_project,
                )
                try:
                    members = await client.get_project_members(portal_id, resolved_project)
                    logger.info(
                        "update_task: project has %d members: %s",
                        len(members),
                        [(m.get("name"), m.get("zpuid")) for m in members],
                    )
                    if isinstance(members, dict) and members.get("error"):
                        logger.warning("update_task: could not fetch members — %s", members)
                        return {"error": f"Could not fetch project members: {members}"}

                    needle = str(raw_assignee).lower()
                    matched_zpuid: Optional[str] = None
                    for member in members:
                        if (
                            needle == str(member.get("name", "")).lower()
                            or needle == str(member.get("email", "")).lower()
                            or needle == str(member.get("id", ""))
                            or needle == str(member.get("zpuid", ""))
                        ):
                            matched_zpuid = str(member["zpuid"])
                            logger.info(
                                "update_task: resolved assignee '%s' -> zpuid='%s'",
                                raw_assignee, matched_zpuid,
                            )
                            break

                    if not matched_zpuid:
                        available = [m.get("name") for m in members if m.get("name")]
                        logger.warning(
                            "update_task: assignee '%s' not found. Available members: %s",
                            raw_assignee, available,
                        )
                        return {
                            "error": (
                                f"User '{raw_assignee}' is not a member of this project. "
                                f"Available members: {available}"
                            )
                        }

                    # Correct Zoho field name for owner on update
                    send_fields["person_responsible"] = matched_zpuid

                except Exception:
                    logger.exception("update_task: assignee resolution failed")
                    return {"error": "Failed to resolve assignee. Please try again."}

            # 4. Execute update
            logger.info(
                "update_task: sending payload to Zoho — project='%s' task='%s' fields=%s",
                resolved_project, resolved_task, send_fields,
            )
            result = await client.update_task(portal_id, resolved_project, resolved_task, send_fields)

            err_msg = _check_api_error(result, "update_task")
            if err_msg:
                return {"error": err_msg}

            # 5. Verify assignee actually changed (when an assignment was requested)
            if raw_assignee and matched_zpuid:
                owners = result.get("details", {}).get("owners", [])
                logger.info("update_task: owners in response = %s", owners)
                assigned_zpuids = [str(o.get("zpuid", "")) for o in owners]
                if matched_zpuid not in assigned_zpuids:
                    logger.warning(
                        "update_task: assignment verification FAILED — "
                        "expected zpuid=%s but owners=%s",
                        matched_zpuid, owners,
                    )
                    return {
                        "error": (
                            f"Assignment may not have taken effect. "
                            f"Zoho returned owners: {[o.get('name') for o in owners]}. "
                            "Please verify in Zoho Projects."
                        )
                    }
                logger.info(
                    "update_task: assignment verified — zpuid=%s is now an owner",
                    matched_zpuid,
                )

            logger.info("Tool result: update_task -> %s", result)
            return result

        except Exception:
            logger.exception("update_task: unexpected error")
            return {"error": "An unexpected error occurred while updating the task. Please try again."}

    @tool
    async def delete_task(project_id: str, task_id: str) -> dict:
        """Permanently delete a task from a project.

        project_id may be a numeric ID, project key, or project name.
        task_id may be a numeric ID or task name — resolved automatically.
        Returns {"error": "..."} on failure instead of raising.
        """
        logger.info(
            "delete_task validation: project_id=%s task_id=%s", project_id, task_id
        )
        try:
            # 1. Resolve project
            try:
                resolved_project = await _resolve_project_id(client, portal_id, project_id)
            except ValueError as exc:
                logger.warning("delete_task: %s", exc)
                return {"error": str(exc)}

            # 2. Resolve task (verify it exists before attempting delete)
            try:
                resolved_task = await _resolve_task_id(
                    client, portal_id, resolved_project, task_id
                )
            except ValueError as exc:
                logger.warning("delete_task: %s", exc)
                return {"error": str(exc)}

            # 3. Execute delete
            logger.info(
                "Executing delete_task: project='%s' task='%s'",
                resolved_project, resolved_task,
            )
            result = await client.delete_task(portal_id, resolved_project, resolved_task)

            # delete_task returns True on success or a dict with error
            if isinstance(result, dict):
                err_msg = _check_api_error(result, "delete_task")
                if err_msg:
                    return {"error": err_msg}

            logger.info("Tool result: delete_task -> task_id=%s deleted", resolved_task)
            return {"deleted": True, "task_id": resolved_task}

        except Exception:
            logger.exception("delete_task: unexpected error")
            return {"error": "An unexpected error occurred while deleting the task. Please try again."}

    tools = [create_task, update_task, delete_task]
    logger.info("Registered write tools: %s", [t.name for t in tools])
    return tools
