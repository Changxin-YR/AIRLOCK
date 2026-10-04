"""Actual official MCP SDK stateful/SSE server over a separate CAS fixture.

Only synthetic tests use this wrapper. It never receives reviewer/audit keys.
"""
import argparse
import os
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--counter-origin',required=True);args=parser.parse_args()
    server=FastMCP('independent-sdk-counter',host='127.0.0.1',port=args.port,stateless_http=False,json_response=False)
    def call(method,path,body=None):
        with httpx.Client(trust_env=False,timeout=3,follow_redirects=False) as client:
            response=client.request(method,args.counter_origin+path,json=body,
                headers={'Authorization':'Bearer '+os.environ['AIRLOCK_UPSTREAM_TEST_TOKEN']})
            response.raise_for_status();return response.json()
    @server.tool()
    def counter_preview(arguments:dict)->dict[str,Any]:
        return call('POST','/preview',{'arguments':arguments})
    @server.tool()
    def counter_execute(action_id:str,request_hash:str,expected_version:str,arguments:dict)->dict[str,Any]:
        return call('POST','/execute',{'action_id':action_id,'request_hash':request_hash,
                                     'expected_version':expected_version,'arguments':arguments})
    @server.tool()
    def counter_receipt(action_id:str)->dict[str,Any]:
        return call('GET','/receipts/'+action_id)
    server.run(transport='streamable-http')


if __name__=='__main__':main()
