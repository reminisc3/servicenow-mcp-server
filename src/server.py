import os
import requests
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from fastmcp import FastMCP
from urllib.parse import urlparse, parse_qs
import re

# Load the repository .env regardless of the process working directory. Values
# already exported by the process take precedence over the file.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

# Initialize FastMCP Server
mcp = FastMCP("ServiceNow Developer Server")
TOOL_NAME_PREFIX = "snmcp_"

# Configuration helpers
INSTANCE = os.getenv("SN_INSTANCE", "").strip()
USERNAME = os.getenv("SN_USERNAME", "").strip()
PASSWORD = os.getenv("SN_PASSWORD")
AUTH_MODE = os.getenv("SN_AUTH_MODE", "basic").strip().lower()
OAUTH_ACCESS_TOKEN = os.getenv("SN_OAUTH_ACCESS_TOKEN", "").strip()
OAUTH_CLIENT_ID = os.getenv("SN_OAUTH_CLIENT_ID", "").strip()
OAUTH_CLIENT_SECRET = os.getenv("SN_OAUTH_CLIENT_SECRET", "")
OAUTH_REFRESH_TOKEN = os.getenv("SN_OAUTH_REFRESH_TOKEN", "").strip()
OAUTH_GRANT_TYPE = os.getenv("SN_OAUTH_GRANT_TYPE", "").strip().lower()
OAUTH_SCOPE = os.getenv("SN_OAUTH_SCOPE", "").strip()
SCOPE_PREFIX = os.getenv("SN_SCOPE_PREFIX", "").strip()
_oauth_token: Optional[str] = None
_oauth_token_expires_at = 0.0


def _get_server_port() -> int:
    """Return the configured MCP server port."""
    value = os.getenv("MCP_PORT", "9000").strip()
    try:
        port = int(value)
    except ValueError as exc:
        raise RuntimeError("MCP_PORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("MCP_PORT must be an integer between 1 and 65535")
    return port


if INSTANCE.startswith(("http://", "https://")):
    BASE_URL = INSTANCE.rstrip("/")
else:
    BASE_URL = f"https://{INSTANCE}.service-now.com"
OAUTH_TOKEN_URL = os.getenv("SN_OAUTH_TOKEN_URL", "").strip() or f"{BASE_URL}/oauth_token.do"

# Context tracking state (In-memory for the session)
# ServiceNow API calls often require the sys_id of the active update set or scope
CURRENT_CONTEXT = {
    "application_sys_id": "global",  # Default to global scope
    "update_set_sys_id": None
}

def _get_auth():
    if not USERNAME or not PASSWORD:
        raise RuntimeError(
            "SN_USERNAME and SN_PASSWORD must be set for ServiceNow Basic Auth"
        )
    return (USERNAME, PASSWORD)


def _get_oauth_token() -> str:
    """Return a configured or freshly acquired OAuth access token."""
    global _oauth_token, _oauth_token_expires_at

    if OAUTH_ACCESS_TOKEN:
        return OAUTH_ACCESS_TOKEN
    if _oauth_token and time.time() < _oauth_token_expires_at:
        return _oauth_token
    if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET:
        raise RuntimeError(
            "SN_OAUTH_CLIENT_ID and SN_OAUTH_CLIENT_SECRET must be set for OAuth"
        )

    grant_type = OAUTH_GRANT_TYPE or (
        "refresh_token"
        if OAUTH_REFRESH_TOKEN
        else (
            "client_credentials"
            if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and not USERNAME and not PASSWORD
            else "password"
        )
    )
    if grant_type not in {"client_credentials", "password", "refresh_token"}:
        raise RuntimeError(
            "SN_OAUTH_GRANT_TYPE must be client_credentials, password, or refresh_token"
        )

    form = {
        "grant_type": grant_type,
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
    }
    if OAUTH_SCOPE:
        form["scope"] = OAUTH_SCOPE
    if grant_type == "refresh_token":
        if not OAUTH_REFRESH_TOKEN:
            raise RuntimeError(
                "SN_OAUTH_REFRESH_TOKEN must be set for the refresh_token grant"
            )
        form["refresh_token"] = OAUTH_REFRESH_TOKEN
    elif grant_type == "password":
        if not USERNAME or not PASSWORD:
            raise RuntimeError(
                "SN_USERNAME and SN_PASSWORD are required for the OAuth password grant"
            )
        form.update({"username": USERNAME, "password": PASSWORD})

    response = requests.post(
        OAUTH_TOKEN_URL,
        data=form,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
    )
    response.raise_for_status()
    token_data = response.json()

    _oauth_token = token_data.get("access_token", "")
    if not _oauth_token:
        raise RuntimeError("OAuth token response did not contain access_token")
    expires_in = int(token_data.get("expires_in", 300))
    _oauth_token_expires_at = time.time() + max(expires_in - 30, 1)
    return _oauth_token


def _get_request_auth() -> Optional[tuple[str, str]]:
    if AUTH_MODE == "oauth":
        return None
    return _get_auth()

def _get_headers():
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    if AUTH_MODE == "oauth":
        headers["Authorization"] = f"Bearer {_get_oauth_token()}"
    # If a specific update set is selected, we inject it into the headers 
    # to mimic studio/developer context if supported by the endpoint,
    # or use it natively during metadata inserts.
    if CURRENT_CONTEXT["update_set_sys_id"]:
        headers["X-UserToken-UpdateSet"] = CURRENT_CONTEXT["update_set_sys_id"]
    return headers

# --- Helper Request Wrapper ---
def _sn_request(method: str, path: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    print(url)
    response = None
    try:
        request_kwargs = {
            "headers": _get_headers(),
            "json": payload,
            "params": params,
            "timeout": 30,
        }
        request_auth = _get_request_auth()
        if request_auth is not None:
            request_kwargs["auth"] = request_auth
        response = requests.request(
            method,
            url,
            **request_kwargs,
        )
        response.raise_for_status()
        return response.json() if response.text else {"status": "success"}
    except requests.exceptions.HTTPError as e:
        return {
            "error": f"HTTP Error: {e}",
            "details": response.text if response is not None else None,
        }
    except Exception as e:
        return {"error": str(e)}

# --- App & Update Set Management Tools ---

def _get_scope_prefix() -> str:
    """Return the configured scope prefix, falling back to the company code property."""
    if SCOPE_PREFIX:
        return SCOPE_PREFIX

    response = _sn_request(
        "GET",
        "/api/now/table/sys_properties",
        params={
            "sysparm_query": "name=glide.appcreator.company.code",
            "sysparm_fields": "value",
            "sysparm_limit": 1,
        },
    )
    result = response.get("result", [])
    if isinstance(result, list) and result:
        return str(result[0].get("value", "")).strip()
    return ""

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_scoped_app")
def create_scoped_app(name: str, scope_id: str) -> Dict[str, Any]:
    """
    Creates a new Scoped Application in ServiceNow.
    """
    path = "/api/now/table/sys_scope"
    scope_prefix = _get_scope_prefix()
    vendor_prefix = scope_prefix.removeprefix("x_")
    scope = f"x_{vendor_prefix}_{scope_id}" if vendor_prefix else scope_id
    payload = {
        "sys_name": name,
        "scope": scope,
        "vendor_prefix": vendor_prefix,
        "can_edit_in_studio": True,
        "private": False,
        "scoped_administration": False,
        "js_level": "es_latest",
    }
    response = _sn_request("POST", path, payload)
    sys_id = response.get("result", {}).get("sys_id")
    if sys_id:
        switch_app_context(sys_id)
    return response

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_update_set")
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
    response = _sn_request("POST", path, payload)
    sys_id = response.get("result", {}).get("sys_id")
    if sys_id:
        switch_update_set(sys_id)
    return response

@mcp.tool(name=f"{TOOL_NAME_PREFIX}switch_update_set")
def switch_update_set(update_set_sys_id: str) -> str:
    """
    Switches the active update set context for subsequent metadata creations.
    """
    _sn_request(
        "POST",
        f"/api/x_275150_agentic/agentic_developer/update_sets/switch/{update_set_sys_id}",
    )
    CURRENT_CONTEXT["update_set_sys_id"] = update_set_sys_id
    return f"Context switched successfully to Update Set Sys ID: {update_set_sys_id}"

@mcp.tool(name=f"{TOOL_NAME_PREFIX}switch_app_context")
def switch_app_context(application_sys_id: str) -> str:
    """
    Switches the active application scope context (e.g., 'global' or a Scoped App sys_id).
    """
    _sn_request(
        "POST",
        f"/api/x_275150_agentic/agentic_developer/apps/switchScope/{application_sys_id}",
    )
    CURRENT_CONTEXT["application_sys_id"] = application_sys_id
    return f"Context switched successfully to Application Sys ID: {application_sys_id}"


# --- Schema & Table Tools ---

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_table")
def create_table(
    label: str,
    name: str,
    extends_table: str = "",
    access: str = "public",
    create_access: bool = True,
    read_access: bool = True,
    update_access: bool = True,
    delete_access: bool = False,
    is_extendable: bool = False,
) -> Dict[str, Any]:
    """
    Creates a new custom table schema in ServiceNow.
    """
    path = "/api/now/table/sys_db_object"
    payload = {
        "access": access,
        "actions_access": "true",
        "alter_access": "true",
        "caller_access": "",
        "client_scripts_access": "true",
        "configuration_access": "true",
        "create_access": str(create_access).lower(),
        "create_access_controls": "false",
        "delete_access": str(delete_access).lower(),
        "is_extendable": str(is_extendable).lower(),
        "label": label,
        "name": name,
        "read_access": str(read_access).lower(),
        "super_class": extends_table,
        "sys_scope": CURRENT_CONTEXT["application_sys_id"]
        or "global",
        "update_access": str(update_access).lower(),
    }
    if CURRENT_CONTEXT["update_set_sys_id"]:
        payload["update_set"] = CURRENT_CONTEXT["update_set_sys_id"]
    return _sn_request("POST", path, payload)


@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_column")
def create_column(
    table_name: str,
    element: str,
    column_label: str,
    internal_type: str = "string",
    max_length: int = 256,
    mandatory: bool = False,
    read_only: bool = False,
    default_value: str = "",
    reference: str = "",
    choice: int = 0,
    unique: bool = False,
) -> Dict[str, Any]:
    """
    Creates a column definition in ServiceNow's sys_dictionary table.

    For reference columns, provide the referenced table in ``reference``.
    """
    path = "/api/now/table/sys_dictionary"
    payload = {
        "active": "true",
        "array": "false",
        "choice": str(choice),
        "column_label": column_label,
        "element": element,
        "internal_type": internal_type,
        "mandatory": str(mandatory).lower(),
        "max_length": str(max_length),
        "name": table_name,
        "read_only": str(read_only).lower(),
        "sys_scope": CURRENT_CONTEXT["application_sys_id"] or "global",
        "unique": str(unique).lower(),
    }
    if default_value:
        payload["default_value"] = default_value
    if reference:
        payload["reference"] = reference
    if CURRENT_CONTEXT["update_set_sys_id"]:
        payload["update_set"] = CURRENT_CONTEXT["update_set_sys_id"]
    return _sn_request("POST", path, payload)

@mcp.tool(name=f"{TOOL_NAME_PREFIX}get_table_columns")
def get_table_columns(table_name: str) -> Dict[str, Any]:
    """
    Retrieves column definitions and schema data for a specific table.
    """
    path = "/api/now/table/sys_dictionary"
    params = {"sysparm_query": f"name={table_name}^ORname=sys_metadata", "sysparm_fields": "element,column_label,internal_type,max_length"}
    return _sn_request("GET", path, params=params)


# --- URL Discovery Helpers ---
def _parse_url(input_url: str) -> Dict[str, Any]:
    """
    Parse an input URL or path and return components (path, query params).
    """
    # If the user passes just a path, allow that by prefixing BASE_URL
    if input_url.startswith("/"):
        full = f"{BASE_URL}{input_url}"
    elif input_url.startswith("http://") or input_url.startswith("https://"):
        full = input_url
    else:
        # fallback: assume it's a full path missing scheme/host
        full = f"https://{input_url}"

    parsed = urlparse(full)
    qs = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
    return {"full": full, "path": parsed.path, "query": qs}


def _fetch_html(url: str) -> Optional[str]:
    """Fetch HTML for the provided URL (best-effort). Returns None on failure."""
    try:
        request_kwargs = {"headers": _get_headers(), "timeout": 10}
        request_auth = _get_request_auth()
        if request_auth is not None:
            request_kwargs["auth"] = request_auth
        resp = requests.get(url, **request_kwargs)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _search_table(table: str, query: str, fields: str = "sys_id,name,sys_created_on") -> Dict[str, Any]:
    path = f"/api/now/table/{table}"
    params = {"sysparm_query": query, "sysparm_limit": 20, "sysparm_fields": fields}
    return _sn_request("GET", path, params=params)


def _extract_table_from_parsed(parsed: Dict[str, Any]) -> Optional[str]:
    """Attempt to extract a table name from parsed URL components.

    Examples:
    - /incident_list.do -> incident
    - /incident.do -> incident
    - nav_to.do?uri=/incident.do -> incident
    - ?table=incident -> incident
    """
    # 1) explicit table query param
    q = parsed.get("query", {})
    if isinstance(q, dict):
        for key in ("table", "table_name", "sysparm_name"):
            if key in q and q[key]:
                return q[key]

    path = parsed.get("path", "")

    # 2) path patterns
    m = re.search(r"/([A-Za-z0-9_]+)_list\\.do$", path)
    if m:
        return m.group(1)
    m = re.search(r"/([A-Za-z0-9_]+)\\.do$", path)
    if m:
        return m.group(1)

    # 3) search the full URL for any /<table>.do occurrences (e.g., nav_to.do?uri=/incident.do)
    full = parsed.get("full", "")
    candidates = re.findall(r"/([A-Za-z0-9_]+)\\.do", full)
    for cand in candidates:
        if cand and cand.lower() not in ("sp", "home", "nav_to"):
            return cand

    return None


@mcp.tool(name=f"{TOOL_NAME_PREFIX}discover_url")
def discover_url(url: str) -> Dict[str, Any]:
    """
    Discover ServiceNow artifacts related to a given URL.

    Heuristics used:
    - Parse query param `id` (common for Service Portal pages like `/sp?id=home`).
    - Search `sp_page` for matching `id` or URL-like fields.
    - Fetch the page HTML and scan for widget sys_ids (data-widget-id patterns) and try to resolve them.
    - Fall back to searching `sys_ui_page` and `sp_widget` by name/url fragments.
    Returns an aggregated dictionary of matches.
    """
    parsed = _parse_url(url)
    results: Dict[str, Any] = {"url": parsed["full"], "matches": {}, "html_snippet": None}

    # 1) If query param 'id' exists, try to find a portal page by that id
    page_id = parsed["query"].get("id")
    if page_id:
        # Search sp_page by its id field
        r = _search_table("sp_page", f"id={page_id}", fields="sys_id,title,id,sys_scope")
        results["matches"]["sp_page_by_id"] = r

    # 2) Try to match sp_page by path fragment
    path_fragment = parsed["path"].strip("/")
    if path_fragment:
        # Search by url-like fragments and title/name
        q = f"idLIKEY{path_fragment}^ORtitleLIKEY{path_fragment}^ORnameLIKEY{path_fragment}"
        r = _search_table("sp_page", q, fields="sys_id,title,id,sys_scope")
        results["matches"]["sp_page_by_fragment"] = r

    # 3) Fetch the HTML and look for widget IDs or widget references
    html = _fetch_html(parsed["full"])
    if html:
        # store a short snippet for quick inspection
        results["html_snippet"] = html[:400]
        widgets_found: List[str] = []
        # common pattern: data-widget-id="<sys_id>"
        widgets_found += re.findall(r"data-widget-id=[\"']([0-9a-fA-F]{32})[\"']", html)
        # some pages embed widget sys_ids in other attributes or scripts
        widgets_found += re.findall(r"widget['\\\"]?\\s*[:=]\\s*['\\\"]?([0-9a-fA-F]{32})['\\\"]?", html)
        # Service Portal widget wrappers use a class token made from "v" + sys_id
        widgets_found += re.findall(r'class=["\'][^"\']*\bv([0-9a-fA-F]{32})(?=\s|["\'])', html)
        # unique
        widgets_found = list(dict.fromkeys(widgets_found))
        if widgets_found:
            results["matches"]["widgets_in_html"] = {}
            for wid in widgets_found:
                results["matches"]["widgets_in_html"][wid] = _search_table("sp_widget", f"sys_id={wid}", fields="sys_id,name,sys_scope")

    # 4) Additional fallback searches: sp_widget and sys_ui_page by fragments
    if path_fragment:
        wq = f"nameLIKEY{path_fragment}^ORidLIKEY{path_fragment}"
        results["matches"]["sp_widget_by_fragment"] = _search_table("sp_widget", wq, fields="sys_id,name,sys_scope")
        results["matches"]["sys_ui_page_by_fragment"] = _search_table("sys_ui_page", f"urlLIKEY{path_fragment}^ORnameLIKEY{path_fragment}", fields="sys_id,name,sys_scope")

    # 5) Try to detect a CRUD table from classic .do/list URLs (e.g., incident_list.do -> incident)
    detected_table = _extract_table_from_parsed(parsed)
    if detected_table:
        results["matches"]["detected_table"] = detected_table
        results["matches"]["table_metadata"] = _search_table("sys_db_object", f"name={detected_table}", fields="sys_id,name,super_class,sys_scope")
        # include column definitions for convenience
        results["matches"]["table_columns"] = get_table_columns(detected_table)

    return results


# --- Standard CRUD Tools ---

@mcp.tool(name=f"{TOOL_NAME_PREFIX}get_record")
def get_record(table_name: str, sys_id: str) -> Dict[str, Any]:
    """
    Retrieves a single record from a specified table by its sys_id.
    """
    path = f"/api/now/table/{table_name}/{sys_id}"
    return _sn_request("GET", path)

@mcp.tool(name=f"{TOOL_NAME_PREFIX}get_records")
def get_records(table_name: str, query: str = "", limit: int = 10) -> Dict[str, Any]:
    """
    Retrieves multiple records from a table based on an encoded query string.
    """
    path = f"/api/now/table/{table_name}"
    params = {"sysparm_query": query, "sysparm_limit": limit}
    return _sn_request("GET", path, params=params)

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_record")
def create_record(table_name: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inserts a new record into a specified table.
    """
    path = f"/api/now/table/{table_name}"
    return _sn_request("POST", path, payload=fields)

@mcp.tool(name=f"{TOOL_NAME_PREFIX}update_record")
def update_record(table_name: str, sys_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates fields on an existing record using its sys_id.
    """
    path = f"/api/now/table/{table_name}/{sys_id}"
    return _sn_request("PUT", path, payload=fields)

@mcp.tool(name=f"{TOOL_NAME_PREFIX}delete_record")
def delete_record(table_name: str, sys_id: str) -> Dict[str, Any]:
    """
    Deletes a record from a specified table by its sys_id.
    """
    path = f"/api/now/table/{table_name}/{sys_id}"
    return _sn_request("DELETE", path)


# --- Specialized Metadata / Creation Tools ---

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_report")
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

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_widget")
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

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_script_include")
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

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_client_script")
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

@mcp.tool(name=f"{TOOL_NAME_PREFIX}create_ui_policy")
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
    mcp.run(transport="streamable-http", host="127.0.0.1", port=_get_server_port())