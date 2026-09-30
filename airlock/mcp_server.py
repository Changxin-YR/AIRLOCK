from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from airlock.agent_client import AgentClient
from airlock.common import DomainError
from airlock.contracts import Filter, OperationRequest

mcp = FastMCP(
    "AIRLOCK Change Review",
    instructions=(
        "Tools return persistent operation handles, not immediate permission to execute. "
        "Use operation.status after the suggested poll interval. Pending approval requires an independent human. "
        "Never invent an approval response or resubmit a pending change under a new key. "
        "A BLOCKED result cannot be approved. This is application-level polling, not native MCP Tasks."
    ),
)


def submit(
    tool: str,
    intent: str,
    key: str,
    resource_id: str,
    where: list[Filter],
    changes: dict | None = None,
    columns: list[str] | None = None,
    limit: int = 100,
    run_id: str = "mcp",
    supersedes_operation_id: str | None = None,
) -> dict:
    try:
        request = OperationRequest(
            tool=tool,
            intent=intent,
            resource_id=resource_id,
            where=where,
            changes=changes or {},
            columns=columns or [],
            limit=limit,
            run_id=run_id,
            supersedes_operation_id=supersedes_operation_id,
        )
        return AgentClient().submit(request, key)
    except DomainError as exc:
        return {"error": exc.public()}


@mcp.tool(name="db.query_rows")
def query_rows(
    intent: str,
    idempotency_key: str,
    where: list[Filter],
    columns: list[str],
    limit: int = 100,
    resource_id: str = "demo",
    run_id: str = "mcp",
) -> dict:
    """Read only allowlisted customer fields; no email, SQL, connections or protected tables."""
    return submit(
        "db.query_rows",
        intent,
        idempotency_key,
        resource_id,
        where,
        columns=columns,
        limit=limit,
        run_id=run_id,
    )


@mcp.tool(name="db.update_rows")
def update_rows(
    intent: str,
    idempotency_key: str,
    where: list[Filter],
    changes: dict[str, str],
    resource_id: str = "demo",
    run_id: str = "mcp",
    supersedes_operation_id: str | None = None,
) -> dict:
    """Propose a status/tag update. The server owns the plan, approval and execution."""
    return submit(
        "db.update_rows",
        intent,
        idempotency_key,
        resource_id,
        where,
        changes=changes,
        run_id=run_id,
        supersedes_operation_id=supersedes_operation_id,
    )


@mcp.tool(name="db.delete_rows")
def delete_rows(
    intent: str,
    idempotency_key: str,
    where: list[Filter],
    resource_id: str = "demo",
    run_id: str = "mcp",
    supersedes_operation_id: str | None = None,
) -> dict:
    """Propose deletion; non-test or overly broad deletions are blocked. Cascades are previewed."""
    return submit(
        "db.delete_rows",
        intent,
        idempotency_key,
        resource_id,
        where,
        run_id=run_id,
        supersedes_operation_id=supersedes_operation_id,
    )


@mcp.tool(name="operation.status")
def operation_status(operation_id: str) -> dict:
    """Query this Agent's operation only. Wait for the server's terminal result."""
    try:
        return AgentClient().status(operation_id)
    except DomainError as exc:
        return {"error": exc.public()}


@mcp.tool(name="operation.cancel")
def operation_cancel(operation_id: str) -> dict:
    """Cancel an unclaimed request. This cannot undo a started or completed transaction."""
    try:
        return AgentClient().cancel(operation_id)
    except DomainError as exc:
        return {"error": exc.public()}


if __name__ == "__main__":
    mcp.run(transport="stdio")
