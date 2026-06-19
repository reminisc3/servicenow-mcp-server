import os
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment variables
load_dotenv()

# Initialize FastMCP Server
mcp = FastMCP("ServiceNow Developer Server")

# Configuration helpers
INSTANCE = os.getenv("SN_INSTANCE")
USERNAME = os.getenv("SN_USERNAME")
PASSWORD = os.getenv("SN_PASSWORD")
BASE_URL = f"https://{INSTANCE}.service-now.com"

# Context tracking state (In-memory for the session)
# ServiceNow API calls often require the sys_id of the active update set or scope
CURRENT_CONTEXT = {
    "application_sys_id": "global",  # Default to global scope
    "update_set_sys_id": None
}

def _get_auth():
    return (USERNAME, PASSWORD)

def _get_headers():
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    # If a specific update set is selected, we inject it into the headers 
    # to mimic studio/developer context if supported by the endpoint,
    # or use it natively during metadata inserts.
    if CURRENT_CONTEXT["update_set_sys_id"]:
        headers["X-UserToken-UpdateSet"] = CURRENT_CONTEXT["update_set_sys_id"]
    return headers

# --- Helper Request Wrapper ---
def _sn_request(method: str, path: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    try:
        response = requests.request(
            method, url, auth=_get_auth(), headers=_get_headers(), json=payload, params=params
        )
        response.raise_for_status()
        return response.json() if response.text else {"status": "success"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP Error: {e}", "details": response.text}
    except Exception as e:
        return {"error": str(e)}

# --- App & Update Set Management Tools ---

@mcp.tool()
def create_scoped_app(name: str, scope_id: str) -> Dict[str, Any]:
    """
    Creates a new Scoped Application in ServiceNow.
    """
    # Uses the App Repo/App Engine endpoint
    path = "/api/sn_apprepo/v1/apps"
    payload = {"name": name, "scope": scope_id}
    return _sn_request("POST", path, payload)

@mcp.tool()
def create_update_set(name: str, description: str = "") -> Dict[str, Any]:
    """
    Creates a new Local Update Set in the current application scope.
    """
    path = "/api/now/table/sys_update_set"
    payload = {
        "name": name,
        "description": description,
        "application": CURRENT_CONTEXT["application_sys_id"] or "global",
        "state": "in_progress"
    }
    return _sn_request("POST", path, payload)

@mcp.tool()
def switch_update_set(update_set_sys_id: str) -> str:
    """
    Switches the active update set context for subsequent metadata creations.
    """
    CURRENT_CONTEXT["update_set_sys_id"] = update_set_sys_id
    return f"Context switched successfully to Update Set Sys ID: {update_set_sys_id}"

@mcp.tool()
def switch_app_context(application_sys_id: str) -> str:
    """
    Switches the active application scope context (e.g., 'global' or a Scoped App sys_id).
    """
    CURRENT_CONTEXT["application_sys_id"] = application_sys_id
    return f"Context switched successfully to Application Sys ID: {application_sys_id}"


# --- Schema & Table Tools ---

@mcp.tool()
def create_table(label: str, name: str, extends_table: str = "") -> Dict[str, Any]:
    """
    Creates a new custom table schema in ServiceNow.
    """
    path = "/api/now/table/sys_db_object"
    payload = {
        "label": label,
        "name": name,
        "super_class": extends_table, # Needs the sys_id of the parent table if extending
        "sys_scope": CURRENT_CONTEXT["application_sys_id"]
    }
    return _sn_request("POST", path, payload)

@mcp.tool()
def get_table_columns(table_name: str) -> Dict[str, Any]:
    """
    Retrieves column definitions and schema data for a specific table.
    """
    path = "/api/now/table/sys_dictionary"
    params = {"sysparm_query": f"name={table_name}^ORname=sys_metadata", "sysparm_fields": "element,column_label,internal_type,max_length"}
    return _sn_request("GET", path, params=params)


# --- Standard CRUD Tools ---

@mcp.tool()
def get_record(table_name: str, sys_id: str) -> Dict[str, Any]:
    """
    Retrieves a single record from a specified table by its sys_id.
    """
    path = f"/api/now/table/{table_name}/{sys_id}"
    return _sn_request("GET", path)

@mcp.tool()
def get_records(table_name: str, query: str = "", limit: int = 10) -> Dict[str, Any]:
    """
    Retrieves multiple records from a table based on an encoded query string.
    """
    path = f"/api/now/table/{table_name}"
    params = {"sysparm_query": query, "sysparm_limit": limit}
    return _sn_request("GET", path, params=params)

@mcp.tool()
def create_record(table_name: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inserts a new record into a specified table.
    """
    path = f"/api/now/table/{table_name}"
    return _sn_request("POST", path, payload=fields)

@mcp.tool()
def update_record(table_name: str, sys_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates fields on an existing record using its sys_id.
    """
    path = f"/api/now/table/{table_name}/{sys_id}"
    return _sn_request("PUT", path, payload=fields)

@mcp.tool()
def delete_record(table_name: str, sys_id: str) -> Dict[str, Any]:
    """
    Deletes a record from a specified table by its sys_id.
    """
    path = f"/api/now/table/{table_name}/{sys_id}"
    return _sn_request("DELETE", path)


# --- Specialized Metadata / Creation Tools ---

@mcp.tool()
def create_report(title: str, table: str, type: str = "bar", field: str = "") -> Dict[str, Any]:
    """
    Creates a basic ServiceNow report configuration.
    """
    path = "/api/now/table/sys_report"
    payload = {
        "title": title,
        "table": table,
        "type": type,
        "field": field,
        "sys_scope": CURRENT_CONTEXT["application_sys_id"]
    }
    return _sn_request("POST", path, payload)

@mcp.tool()
def create_widget(name: str, id: str, html: str = "", css: str = "", client_script: str = "", server_script: str = "") -> Dict[str, Any]:
    """
    Creates a Service Portal Widget.
    """
    path = "/api/now/table/sp_widget"
    payload = {
        "name": name,
        "id": id,
        "template": html,
        "css": css,
        "client_script": client_script,
        "script": server_script,
        "sys_scope": CURRENT_CONTEXT["application_sys_id"]
    }
    return _sn_request("POST", path, payload)

@mcp.tool()
def create_script_include(name: str, script: str, api_name: Optional[str] = None, client_callable: bool = False) -> Dict[str, Any]:
    """
    Creates a Server-Side Script Include.
    """
    path = "/api/now/table/sys_script_include"
    payload = {
        "name": name,
        "api_name": api_name or name,
        "script": script,
        "client_callable": str(client_callable).lower(),
        "sys_scope": CURRENT_CONTEXT["application_sys_id"]
    }
    if CURRENT_CONTEXT["update_set_sys_id"]:
        payload["update_set"] = CURRENT_CONTEXT["update_set_sys_id"]
        
    return _sn_request("POST", path, payload)

@mcp.tool()
def create_client_script(name: str, table: str, type: str, script: str, ui_type: str = "1") -> Dict[str, Any]:
    """
    Creates a Client Script. Type options: onLoad, onChange, onSubmit, onCellEdit. UI Type: 0=Desktop, 1=Mobile/Service Portal, 10=All.
    """
    path = "/api/now/table/sys_script_client"
    payload = {
        "name": name,
        "table": table,
        "type": type,
        "script": script,
        "ui_type": ui_type,
        "sys_scope": CURRENT_CONTEXT["application_sys_id"],
        "active": "true"
    }
    return _sn_request("POST", path, payload)

@mcp.tool()
def create_ui_policy(short_description: str, table: str, conditions: str = "", reverse_if_false: bool = True) -> Dict[str, Any]:
    """
    Creates a UI Policy. Conditions should be passed as a standard ServiceNow encoded query string.
    """
    path = "/api/now/table/sys_ui_policy"
    payload = {
        "short_description": short_description,
        "table": table,
        "conditions": conditions,
        "reverse_if_false": str(reverse_if_false).lower(),
        "sys_scope": CURRENT_CONTEXT["application_sys_id"],
        "active": "true"
    }
    return _sn_request("POST", path, payload)


if __name__ == "__main__":
    # Launching the FastMCP server via STDIO transport layer
    mcp.run(transport="stdio")