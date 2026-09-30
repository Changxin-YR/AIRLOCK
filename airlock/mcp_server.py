"""Genuine MCP v1.x stdio adapter. Holds ONLY a gateway Agent credential."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
from typing import Annotated
from pydantic import Field, StrictInt
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from .client import AgentClient
from .common import AirlockError
from .contracts import Condition, ToolRequest

INSTRUCTIONS = '''This server proposes scoped SQLite operations through AIRLOCK. A returned operation
handle is NOT successful execution. Poll airlock.operation_status until a terminal state; report
PENDING_APPROVAL to the user and let a human independently log into the approval workbench.
Never fabricate approval. UNKNOWN requires receipt reconciliation, not a fresh mutation request.
The pending handle is an application-level result, NOT MCP native Tasks.'''


def create_server(client: AgentClient) -> FastMCP:
    server=FastMCP('AIRLOCK Agent Change Review',instructions=INSTRUCTIONS)
    def submit(tool, idempotency_key, **arguments):
        try:
            request=ToolRequest(tool=tool,**arguments)
            return {'operation':client.submit(request,idempotency_key),'handling':'poll_operation_status; approval is out-of-band'}
        except AirlockError as exc:
            return {'error':exc.public()}

    @server.tool(name='db.query_rows',description='Read limited, permitted customer fields. Creates an auditable operation handle.',
                 annotations=ToolAnnotations(readOnlyHint=True,openWorldHint=False))
    def query_rows(idempotency_key: str, filters: list[Condition] | None=None,
                   columns: list[str] | None=None, limit: Annotated[StrictInt,Field(ge=1,le=100)]=20,
                   task: str='',run_id: str='mcp') -> dict:
        arguments={'filters':filters or [],'limit':limit,'task':task,'run_id':run_id}
        if columns is not None: arguments['columns']=columns
        return submit('db.query_rows',idempotency_key,**arguments)

    @server.tool(name='db.update_rows',description='Propose a scoped update of name, status or tag. Never means already approved.',
                 annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=True,openWorldHint=False))
    def update_rows(idempotency_key: str, values: dict[str,str],filters:list[Condition],task:str='',run_id:str='mcp') -> dict:
        return submit('db.update_rows',idempotency_key,values=values,filters=filters,task=task,run_id=run_id)

    @server.tool(name='db.delete_rows',description='Propose deletion, including supported note cascades. Human confirmation may be required.',
                 annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=True,openWorldHint=False))
    def delete_rows(idempotency_key: str, filters:list[Condition],task:str='',run_id:str='mcp') -> dict:
        return submit('db.delete_rows',idempotency_key,filters=filters,task=task,run_id=run_id)

    @server.tool(name='airlock.operation_status',description='Query only this Agent identity’s operation; no approval capability.',
                 annotations=ToolAnnotations(readOnlyHint=True,openWorldHint=False))
    def operation_status(operation_id:str) -> dict:
        try: return client.get(operation_id)
        except AirlockError as exc: return {'error':exc.public(operation_id)}
    return server


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--env-file',type=Path)
    args=parser.parse_args()
    config={k:os.environ[k] for k in ('AIRLOCK_BASE_URL','AIRLOCK_AGENT_TOKEN') if k in os.environ}
    if args.env_file:
        # Deliberately avoid importing the bootstrap CLI (which imports target initialization).
        entries={}
        for line in args.env_file.read_text().splitlines():
            if line and not line.startswith('#'):
                key,sep,value=line.partition('=')
                if not sep or key not in {'AIRLOCK_BASE_URL','AIRLOCK_AGENT_TOKEN'} or key in entries:
                    raise ValueError('Only an Agent-specific environment file is accepted')
                entries[key]=value
        config=entries
    with AgentClient(config.get('AIRLOCK_BASE_URL','http://127.0.0.1:8080'),config.get('AIRLOCK_AGENT_TOKEN','')) as client:
        create_server(client).run(transport='stdio')


if __name__=='__main__': main()
