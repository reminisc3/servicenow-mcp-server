# ServiceNow MCP Server

> A lightweight MCP (Model Context Protocol) adapter that exposes a set of ServiceNow helper tools via a FastMCP server. Designed for developer automation, scripting, and rapid metadata creation against a ServiceNow instance.

## Features

- Exposes common ServiceNow REST operations as MCP tools (CRUD on tables).
- Helpers for managing scoped applications and update sets.
- Convenience functions for creating widgets, reports, client scripts, and script includes.
- Context-aware requests that respect the current application scope and active update set.

## Repository Layout

- `src/server.py` — Main FastMCP server implementation and tool registrations.
- `src/utils/` — Utilities and helpers (if present).
- `requirements.txt` — Python dependencies.

## Requirements

- Python 3.10+ recommended
- See `requirements.txt` for exact dependencies (e.g., `requests`, `python-dotenv`, `mcp` / `mcp-server`)

## Environment

The server uses environment variables for ServiceNow credentials and instance configuration. Create a `.env` file or export these variables in your shell:

```
SN_INSTANCE=your_instance_name_without_domain_prefix
SN_USERNAME=your_user
SN_PASSWORD=your_password_or_token
```

`SN_INSTANCE` should be the short instance name (for example `dev12345`) — the server builds the base URL as `https://{SN_INSTANCE}.service-now.com`.

## Quick Start

1. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

2. Add your environment variables (see above).

3. Run the MCP server:

```bash
python src/server.py
```

The server runs a FastMCP instance that communicates over STDIO by default. Use an MCP-capable client to call tools.

## Using with VS Code

You can integrate the MCP server workflow into VS Code for a comfortable development experience. Two common approaches:

1. Use an MCP-capable extension or client in the editor that supports STDIO transports (or TCP if you adapt `mcp.run`). Configure the extension to launch `python src/server.py` as the background MCP server process and bind its STDIO to the extension.

2. Use the built-in `Run`/`Debug` configuration to start the server and then interact with it from an external MCP client. Example `launch.json` snippet:

```json
{
	"version": "0.2.0",
	"configurations": [
		{
			"name": "Run MCP Server",
			"type": "python",
			"request": "launch",
			"program": "${workspaceFolder}/src/server.py",
			"console": "integratedTerminal",
			"envFile": "${workspaceFolder}/.env"
		}
	]
}
```

Tips:

- Open an integrated terminal in VS Code to monitor server logs and output.
- Use the `Python` extension to ensure the correct interpreter and virtual environment are active.
- If you use an MCP client extension that supports TCP, modify `mcp.run(transport="tcp", host="127.0.0.1", port=12345)` and update the client to connect to that port.

## Using with Postman, curl, or Node

This project exposes ServiceNow REST calls through MCP tools rather than exposing HTTP directly. To test ServiceNow APIs without an MCP client, you can either call the ServiceNow REST endpoints directly with `curl`/Postman using the same credentials, or wrap MCP tool calls with a small client. Examples below assume you prefer direct REST testing.

curl example (get a record):

```bash
curl -u "$SN_USERNAME:$SN_PASSWORD" \
	"https://$SN_INSTANCE.service-now.com/api/now/table/incident?sysparm_limit=1" \
	-H "Accept: application/json"
```

Node (axios) example:

```js
const axios = require('axios');

const instance = process.env.SN_INSTANCE;
const auth = { username: process.env.SN_USERNAME, password: process.env.SN_PASSWORD };

axios.get(`https://${instance}.service-now.com/api/now/table/incident?sysparm_limit=1`, { auth })
	.then(res => console.log(res.data))
	.catch(err => console.error(err.response ? err.response.data : err.message));
```

If you want to call the MCP tools from Node or another language, implement an MCP client that communicates over STDIO or TCP and invokes the registered tool names (for example `create_record`, `get_record`).

## Example Tool Usage

Below are example MCP tool names and brief descriptions — these map to functions registered in `src/server.py`:

- `create_record(table_name, fields)` — Create a record in a table.
- `get_record(table_name, sys_id)` — Retrieve a single record by `sys_id`.
- `get_records(table_name, query, limit)` — Query records with an encoded query string.
- `update_record(table_name, sys_id, fields)` — Update a record by `sys_id`.
- `delete_record(table_name, sys_id)` — Delete a record by `sys_id`.
- `create_update_set(name, description)` — Create an update set in the current application scope.
- `switch_update_set(update_set_sys_id)` — Switch the active update set for subsequent metadata operations.
- `create_script_include(name, script, api_name, client_callable)` — Create a server-side Script Include.

Example: using an MCP client call to create a record might look like calling the `create_record` tool with `table_name` set to `incident` and `fields` containing JSON for required fields.

## Context & Behavior Notes

- The server keeps an in-memory `CURRENT_CONTEXT` for `application_sys_id` and `update_set_sys_id`. Call `switch_app_context()` and `switch_update_set()` to change behavior for subsequent creations.
- When an update set is active, some creation helpers include the `update_set` field so ServiceNow will associate metadata with that update set.

## Development

- Implement or extend tools in `src/server.py`. Keep tool functions small and focused.
- Add new helper functions under `src/utils/` as needed.
- Follow ServiceNow REST API best practices: prefer `sysparm_fields` and `sysparm_query` when retrieving lists.

## Testing

- There are no automated tests included by default. For manual testing, run the server and exercise tools with an MCP client or write simple scripts that call the ServiceNow REST API directly using the same credentials.

## Contributing

Contributions are welcome. Open issues or PRs for bug fixes and feature requests. Please include reproducible examples when reporting bugs.

## License

See the repository `LICENSE` file for licensing details.

