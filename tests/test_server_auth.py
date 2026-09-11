import unittest
import os
from unittest.mock import call, patch

from src import server


class FakeResponse:
    text = '{"result": {"sys_id": "abc123"}}'

    def raise_for_status(self):
        pass

    def json(self):
        return {"result": {"sys_id": "abc123"}}


class FakeTokenResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"access_token": "client-token", "expires_in": 300}


class ServerAuthenticationTests(unittest.TestCase):
    def test_server_port_uses_environment_value(self):
        with patch.dict(os.environ, {"MCP_PORT": "9100"}):
            self.assertEqual(server._get_server_port(), 9100)

    def test_server_port_rejects_invalid_value(self):
        with patch.dict(os.environ, {"MCP_PORT": "not-a-port"}):
            with self.assertRaisesRegex(RuntimeError, "MCP_PORT"):
                server._get_server_port()

    def setUp(self):
        self.original_auth_mode = server.AUTH_MODE
        self.original_username = server.USERNAME
        self.original_password = server.PASSWORD
        self.original_access_token = server.OAUTH_ACCESS_TOKEN
        self.original_client_id = server.OAUTH_CLIENT_ID
        self.original_client_secret = server.OAUTH_CLIENT_SECRET
        self.original_grant_type = server.OAUTH_GRANT_TYPE
        self.original_scope = server.OAUTH_SCOPE
        self.original_scope_prefix = server.SCOPE_PREFIX
        self.original_oauth_token = server._oauth_token
        self.original_oauth_token_expires_at = server._oauth_token_expires_at
        server._oauth_token = None
        server._oauth_token_expires_at = 0.0
        server.CURRENT_CONTEXT = {
            "application_sys_id": "global",
            "update_set_sys_id": None,
        }

    def tearDown(self):
        server.AUTH_MODE = self.original_auth_mode
        server.USERNAME = self.original_username
        server.PASSWORD = self.original_password
        server.OAUTH_ACCESS_TOKEN = self.original_access_token
        server.OAUTH_CLIENT_ID = self.original_client_id
        server.OAUTH_CLIENT_SECRET = self.original_client_secret
        server.OAUTH_GRANT_TYPE = self.original_grant_type
        server.OAUTH_SCOPE = self.original_scope
        server.SCOPE_PREFIX = self.original_scope_prefix
        server._oauth_token = self.original_oauth_token
        server._oauth_token_expires_at = self.original_oauth_token_expires_at

    @patch("src.server._sn_request")
    def test_create_scoped_app_uses_configured_scope_prefix(self, sn_request):
        sn_request.return_value = {"result": {"sys_id": "abc123"}}
        server.SCOPE_PREFIX = "x_123456"

        server.create_scoped_app("Order Management", "order_management")

        self.assertEqual(
            sn_request.call_args_list,
            [
                call(
            "POST",
            "/api/now/table/sys_scope",
            {
                "sys_name": "Order Management",
                "scope": "x_123456_order_management",
                "vendor_prefix": "123456",
                "can_edit_in_studio": True,
                "private": False,
                "scoped_administration": False,
                "js_level": "es_latest",
            },
                ),
                call(
                    "POST",
                    "/api/x_275150_agentic/agentic_developer/apps/switchScope/abc123",
                ),
            ],
        )
        self.assertEqual(server.CURRENT_CONTEXT["application_sys_id"], "abc123")

    @patch("src.server._sn_request")
    def test_create_scoped_app_falls_back_to_company_code_property(self, sn_request):
        sn_request.side_effect = [
            {"result": [{"value": "x_654321"}]},
            {"result": {"sys_id": "abc123"}},
            {"result": {"status": "switched"}},
        ]
        server.SCOPE_PREFIX = ""

        server.create_scoped_app("Order Management", "order_management")

        self.assertEqual(
            sn_request.call_args_list[0].args,
            ("GET", "/api/now/table/sys_properties"),
        )
        self.assertEqual(
            sn_request.call_args_list[0].kwargs,
            {
                "params": {
                    "sysparm_query": "name=glide.appcreator.company.code",
                    "sysparm_fields": "value",
                    "sysparm_limit": 1,
                }
            },
        )
        self.assertEqual(
            sn_request.call_args_list[1].args,
            (
                "POST",
                "/api/now/table/sys_scope",
                {
                    "sys_name": "Order Management",
                    "scope": "x_654321_order_management",
                    "vendor_prefix": "654321",
                    "can_edit_in_studio": True,
                    "private": False,
                    "scoped_administration": False,
                    "js_level": "es_latest",
                },
            ),
        )

    @patch("src.server.requests.request")
    def test_basic_auth_request_reaches_instance(self, request):
        request.return_value = FakeResponse()
        server.AUTH_MODE = "basic"
        server.USERNAME = "test-user"
        server.PASSWORD = "test-password"

        result = server._sn_request("GET", "/api/now/table/incident", params={"sysparm_limit": 1})

        self.assertEqual(result, {"result": {"sys_id": "abc123"}})
        request.assert_called_once_with(
            "GET",
            f"{server.BASE_URL}/api/now/table/incident",
            auth=("test-user", "test-password"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json=None,
            params={"sysparm_limit": 1},
            timeout=30,
        )

    @patch("src.server._sn_request")
    def test_create_update_set_switches_to_created_update_set(self, sn_request):
        sn_request.side_effect = [
            {"result": {"sys_id": "update-set-123"}},
            {"result": {"status": "switched"}},
        ]

        result = server.create_update_set("Release", "April release")

        self.assertEqual(result, {"result": {"sys_id": "update-set-123"}})
        self.assertEqual(server.CURRENT_CONTEXT["update_set_sys_id"], "update-set-123")
        self.assertEqual(
            sn_request.call_args_list[1],
            call(
                "POST",
                "/api/x_275150_agentic/agentic_developer/update_sets/switch/update-set-123",
            ),
        )

    @patch("src.server._sn_request")
    def test_create_table_uses_scope_and_update_set_context(self, sn_request):
        sn_request.return_value = {"result": {"sys_id": "table-123"}}
        server.CURRENT_CONTEXT = {
            "application_sys_id": "app-123",
            "update_set_sys_id": "update-set-123",
        }

        result = server.create_table("Order", "x_app_order", extends_table="task")

        self.assertEqual(result, {"result": {"sys_id": "table-123"}})
        sn_request.assert_called_once_with(
            "POST",
            "/api/now/table/sys_db_object",
            {
                "access": "public",
                "actions_access": "true",
                "alter_access": "true",
                "caller_access": "",
                "client_scripts_access": "true",
                "configuration_access": "true",
                "create_access": "true",
                "create_access_controls": "false",
                "delete_access": "false",
                "is_extendable": "false",
                "label": "Order",
                "name": "x_app_order",
                "read_access": "true",
                "super_class": "task",
                "sys_scope": "app-123",
                "update_access": "true",
                "update_set": "update-set-123",
            },
        )

    @patch("src.server._sn_request")
    def test_create_column_creates_dictionary_record(self, sn_request):
        sn_request.return_value = {"result": {"sys_id": "column-123"}}

        result = server.create_column(
            "x_app_order",
            "customer",
            "Customer",
            internal_type="reference",
            max_length=32,
            mandatory=True,
            reference="sys_user",
        )

        self.assertEqual(result, {"result": {"sys_id": "column-123"}})
        sn_request.assert_called_once_with(
            "POST",
            "/api/now/table/sys_dictionary",
            {
                "active": "true",
                "array": "false",
                "choice": "0",
                "column_label": "Customer",
                "element": "customer",
                "internal_type": "reference",
                "mandatory": "true",
                "max_length": "32",
                "name": "x_app_order",
                "read_only": "false",
                "sys_scope": "global",
                "unique": "false",
                "reference": "sys_user",
            },
        )

    @patch("src.server._sn_request")
    def test_switch_context_tools_use_custom_endpoints(self, sn_request):
        server.switch_app_context("app-123")
        server.switch_update_set("update-set-123")

        self.assertEqual(
            sn_request.call_args_list,
            [
                call(
                    "POST",
                    "/api/x_275150_agentic/agentic_developer/apps/switchScope/app-123",
                ),
                call(
                    "POST",
                    "/api/x_275150_agentic/agentic_developer/update_sets/switch/update-set-123",
                ),
            ],
        )
        self.assertEqual(server.CURRENT_CONTEXT["application_sys_id"], "app-123")
        self.assertEqual(server.CURRENT_CONTEXT["update_set_sys_id"], "update-set-123")
    @patch("src.server.requests.request")
    def test_oauth_request_uses_bearer_auth(self, request):
        request.return_value = FakeResponse()
        server.AUTH_MODE = "oauth"
        server.OAUTH_ACCESS_TOKEN = "test-access-token"

        result = server._sn_request("GET", "/api/now/table/incident")

        self.assertEqual(result, {"result": {"sys_id": "abc123"}})
        request.assert_called_once_with(
            "GET",
            f"{server.BASE_URL}/api/now/table/incident",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer test-access-token",
            },
            json=None,
            params=None,
            timeout=30,
        )

    @patch("src.server.requests.get")
    def test_oauth_html_request_uses_bearer_auth_without_basic_auth(self, get):
        get.return_value = FakeResponse()
        server.AUTH_MODE = "oauth"
        server.OAUTH_ACCESS_TOKEN = "test-access-token"

        self.assertEqual(server._fetch_html("https://example.service-now.com/sp"), FakeResponse.text)
        get.assert_called_once_with(
            "https://example.service-now.com/sp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer test-access-token",
            },
            timeout=10,
        )

    @patch("src.server._search_table")
    @patch("src.server._fetch_html")
    def test_discover_url_finds_widget_sys_id_in_wrapper_class(self, fetch_html, search_table):
        widget_sys_id = "ce046d5773603010c94f54eb7df6a7ec"
        fetch_html.return_value = (
            '<div class="v%s ng-scope" widget="widget" sn-atf-area="Employee Center Footer">'
            % widget_sys_id
        )
        search_table.return_value = {"result": []}

        result = server.discover_url("https://example.service-now.com/sp?id=home")

        self.assertEqual(result["matches"]["widgets_in_html"], {widget_sys_id: {"result": []}})
        self.assertIn(
            call(
                "sp_widget",
                f"sys_id={widget_sys_id}",
                fields="sys_id,name,sys_scope",
            ),
            search_table.call_args_list,
        )

    @patch("src.server.requests.post")
    def test_oauth_defaults_to_client_credentials_when_only_client_credentials_exist(self, post):
        post.return_value = FakeTokenResponse()
        server.AUTH_MODE = "oauth"
        server.USERNAME = ""
        server.PASSWORD = ""
        server.OAUTH_CLIENT_ID = "client-id"
        server.OAUTH_CLIENT_SECRET = "client-secret"
        server.OAUTH_GRANT_TYPE = ""
        server.OAUTH_SCOPE = ""

        self.assertEqual(server._get_oauth_token(), "client-token")
        post.assert_called_once_with(
            server.OAUTH_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )

    @patch("src.server.requests.post")
    def test_oauth_password_grant_sends_credentials_in_form_body(self, post):
        post.return_value = FakeTokenResponse()
        server.AUTH_MODE = "oauth"
        server.USERNAME = "test-user"
        server.PASSWORD = "test-password"
        server.OAUTH_CLIENT_ID = "client-id"
        server.OAUTH_CLIENT_SECRET = "client-secret"
        server.OAUTH_GRANT_TYPE = "password"
        server.OAUTH_SCOPE = ""

        self.assertEqual(server._get_oauth_token(), "client-token")
        post.assert_called_once_with(
            server.OAUTH_TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "username": "test-user",
                "password": "test-password",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
