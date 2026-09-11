# ServiceNow MCP Server

A FastMCP server that exposes ServiceNow Table API operations and developer automation tools through the Model Context Protocol (MCP). It supports CRUD operations, scoped application and update-set workflows, schema creation, Service Portal discovery, and common metadata creation.

## Features

- ServiceNow Table API CRUD operations for arbitrary tables.
- Scoped application and local update-set management.
- Application-scope and update-set context tracking during a server session.
- Table and column creation, including access and reference-field options.
- Creation of reports, Service Portal widgets, Script Includes, Client Scripts, and UI Policies.
- URL discovery for Service Portal pages, widgets, UI pages, tables, and columns.
- Basic Authentication and OAuth 2.0, including access-token, password, refresh-token, and client-credentials flows.

## Requirements

- Python 3.10 or newer.
- A ServiceNow instance with an account that can use the Table API.
- An MCP client that can connect to a streamable HTTP server.

## Repository Layout

```text
src/server.py                                MCP server and tool registrations
tests/test_server_auth.py                    Authentication and request-wrapper tests
update_sets/ServiceNow Agentic Developer-v1.0.xml
                                             ServiceNow application update set
requirements.txt                             Python dependencies
```

## Configuration

The server loads `.env` from the repository root. Exported environment variables take precedence over values in that file.

### Basic Authentication

```dotenv
SN_INSTANCE=dev12345
SN_USERNAME=your_user
SN_PASSWORD=your_password_or_token
SN_AUTH_MODE=basic
SN_SCOPE_PREFIX=x_123456
MCP_PORT=9000
```

`SN_INSTANCE` can be a short instance name such as `dev12345` or a full URL such as `https://dev12345.service-now.com`.

`SN_SCOPE_PREFIX` is used when creating scoped applications. For example, `x_123456` and `order_management` produce the scope `x_123456_order_management`. If it is omitted, the server reads `glide.appcreator.company.code` from `sys_properties`.

`MCP_PORT` controls the local streamable HTTP listener port and defaults to `9000`.

### OAuth 2.0

Set `SN_AUTH_MODE=oauth` and use either a pre-issued access token or OAuth client credentials:

```dotenv
SN_INSTANCE=dev12345
SN_AUTH_MODE=oauth
SN_OAUTH_ACCESS_TOKEN=your_access_token
```

For token acquisition, use:

```dotenv
SN_OAUTH_CLIENT_ID=your_client_id
SN_OAUTH_CLIENT_SECRET=your_client_secret
SN_OAUTH_GRANT_TYPE=client_credentials
SN_OAUTH_SCOPE=useraccount
```

Supported grant types are `client_credentials`, `password`, and `refresh_token`. The password grant also requires `SN_USERNAME` and `SN_PASSWORD`; the refresh-token grant requires `SN_OAUTH_REFRESH_TOKEN`. `SN_OAUTH_TOKEN_URL` can override the default `<instance>/oauth_token.do` endpoint.

Keep credentials in `.env` or another secret store and do not commit them to source control.

## Quick Start

1. Clone the repository and enter its directory.

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

   On Windows, activate the environment with `.venv\\Scripts\\activate`.

3. Install the dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Configure the ServiceNow instance and authentication variables in `.env` as described above.

5. Import the update set from [`update_sets/ServiceNow Agentic Developer-v1.0.xml`](update_sets/ServiceNow%20Agentic%20Developer-v1.0.xml) into the ServiceNow instance. In ServiceNow, load the remote update set, preview it, resolve any collisions, and commit it. This installs the `ServiceNow Agentic Developer` application and the custom endpoints used by the context-switching tools.

6. Start the server:

   ```bash
   python src/server.py
   ```

   The server listens on `http://127.0.0.1:9000/mcp` using FastMCP's streamable HTTP transport.

7. Configure an MCP client to connect to that URL and invoke the registered tools.

## MCP Client Configuration

The server uses streamable HTTP by default. A client configuration typically points to:

```text
http://127.0.0.1:9000/mcp
```

The server binds to localhost. To expose it on another interface, update the `host` argument in the `mcp.run(...)` call in `src/server.py` and apply the appropriate network security controls.

## Available Tools

### Context and application management

- `create_scoped_app(name, scope_id)` - Create a scoped application and switch to it.
- `create_update_set(name, description)` - Create a local update set and switch to it.
- `switch_app_context(application_sys_id)` - Set the active application scope.
- `switch_update_set(update_set_sys_id)` - Set the active update set.

### Schema and discovery

- `create_table(...)` - Create a custom table in `sys_db_object`.
- `create_column(...)` - Create a field definition in `sys_dictionary`.
- `get_table_columns(table_name)` - Retrieve field definitions for a table.
- `discover_url(url)` - Find related Service Portal, UI, table, widget, and column records.

### Records

- `create_record(table_name, fields)`
- `get_record(table_name, sys_id)`
- `get_records(table_name, query, limit)`
- `update_record(table_name, sys_id, fields)`
- `delete_record(table_name, sys_id)`

### Metadata creation

- `create_report(title, table, type, field)`
- `create_widget(name, id, html, css, client_script, server_script)`
- `create_script_include(name, script, api_name, client_callable)`
- `create_client_script(name, table, type, script, ui_type)`
- `create_ui_policy(short_description, table, conditions, reverse_if_false)`

## Context Behavior

Application and update-set context is stored in memory for the lifetime of the server process. The default application context is `global`, and no update set is active until one is created or selected.

When an update set is active, the server sends its sys_id in the `X-UserToken-UpdateSet` request header and includes it in supported metadata payloads. Restarting the server resets this in-memory context, so select the application and update set again for each new session.

## Development and Testing

Run the unit tests from the repository root:

```bash
python -m unittest discover -s tests -v
```

The tests mock ServiceNow and do not require live credentials or network access. Keep tool implementations in `src/server.py` focused, and add tests for changes to authentication, request construction, or context behavior.

For direct ServiceNow API checks, use the same credentials with `curl`:

```bash
curl --user "$SN_USERNAME:$SN_PASSWORD" \
  "https://$SN_INSTANCE.service-now.com/api/now/table/incident?sysparm_limit=1" \
  --header "Accept: application/json"
```

## Troubleshooting

- `401 Unauthorized`: verify the credentials, authentication mode, OAuth token, and Table API permissions. Ensure the MCP process loads the same `.env` file as the shell.
- Context-switching failures: confirm that the `ServiceNow Agentic Developer` update set was imported, previewed, and committed.
- OAuth failures: verify the grant type, client permissions, token endpoint, and required credentials for that grant.
- Connection failures: confirm that the server is running and that the MCP client uses `http://127.0.0.1:9000/mcp`.

## License

See [`LICENSE`](LICENSE).
