"""Relia CLI entrypoint.

Commands:
  relia-cli generate --module <mod> --prompt <text>
  relia-cli lint <playbook_id>
  relia-cli test <playbook_id>
  relia-cli feedback <playbook_id>
  relia-cli export-feedback [file.csv]
  relia-cli refresh-schemas <module>...
  relia-cli doctor
  relia-cli init-starter <name>
  relia-cli telemetry <enable|disable|status>
"""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from backend.app import app, settings
from backend.security import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from backend.auth import HTTPAuthorizationCredentials
from backend.llm_adapter import LLMClient

class NoAuthTestClient(TestClient):
    """TestClient that bypasses authentication and CSRF protection."""
    
    def request(self, *args, **kwargs):
        # Initialize headers if None
        if kwargs.get("headers") is None:
            kwargs["headers"] = {}
            
        # Add the Authorization header to bypass JWT auth
        kwargs["headers"]["Authorization"] = "Bearer test-token"
        
        # Initialize cookies if None
        if kwargs.get("cookies") is None:
            kwargs["cookies"] = {}
            
        # Add CSRF token cookie
        kwargs["cookies"][CSRF_COOKIE_NAME] = "test-csrf-token"
        
        # Add CSRF header if this is a state-changing method
        method = kwargs.get("method", args[0] if args else "GET")
        if method in ["POST", "PUT", "DELETE", "PATCH"]:
            kwargs["headers"][CSRF_HEADER_NAME] = "test-csrf-token"
        
        return super().request(*args, **kwargs)

client = NoAuthTestClient(app)

class MockLLMClient(LLMClient):
    """Mock LLM client for testing."""
    
    def generate(self, prompt: str) -> str:
        """Return a predefined response."""
        return "- name: test task\n  ansible.builtin.debug:\n    msg: test"

@pytest.fixture(autouse=True)
def setup_auth_bypass(monkeypatch):
    """Bypass all authentication and security mechanisms for tests."""
    # 1. Replace role_required to do nothing
    monkeypatch.setattr("backend.app.role_required", lambda role: lambda request=None, user=None: None)
    
    # 2. Bypass the get_current_user dependency
    async def mock_get_current_user(*args, **kwargs):
        return {"sub": "test-user", "roles": ["generator", "tester", "admin"]}
    monkeypatch.setattr("backend.auth.get_current_user", mock_get_current_user)
    
    # 3. Mock auth.verify_token to accept any token
    def mock_verify_token(token):
        return {"sub": "test-user", "roles": ["generator", "tester", "admin"]}
    monkeypatch.setattr("backend.auth.verify_token", mock_verify_token)
    
    # 4. Mock auth.bearer_scheme to always return valid credentials
    def mock_bearer_scheme(request=None):
        return HTTPAuthorizationCredentials(scheme="bearer", credentials="test-token")
    monkeypatch.setattr("backend.auth.bearer_scheme", mock_bearer_scheme)
    
    # 5. Completely disable CSRF protection
    monkeypatch.setattr("backend.security.CSRFMiddleware.dispatch", 
                       lambda self, request, call_next: call_next(request))
    
    # 6. Set auth SECRET to a known value for tests
    monkeypatch.setattr("backend.auth.SECRET", "test-secret")
    
    # 7. Disable database for tests
    monkeypatch.setattr("backend.app.settings.DB_ENABLED", False)
    monkeypatch.setattr("backend.database.initialize_database", lambda **kwargs: True)
    
    # 8. Mock LLM client
    mock_instance = MockLLMClient()
    monkeypatch.setattr("backend.app.get_llm_client", lambda: mock_instance)
    monkeypatch.setattr("backend.app.get_client", lambda: mock_instance)
    monkeypatch.setattr("backend.llm_adapter.get_client", lambda *args, **kwargs: mock_instance)


def test_generate_endpoint(tmp_path, monkeypatch):
    # Override config for test
    monkeypatch.setattr(settings, 'SCHEMA_DIR', tmp_path / 'schemas')
    monkeypatch.setattr(settings, 'PLAYBOOK_DIR', tmp_path / 'pb')
    monkeypatch.setattr('backend.app.schemas', {"ansible.builtin.lineinfile": {"options": {}}})

    resp = client.post(
        '/v1/generate',
        json={"module": "ansible.builtin.lineinfile", "prompt": "demo"}
    )
    assert resp.status_code == 201  # Note: The new endpoint returns 201 Created
    data = resp.json()
    assert "playbook_id" in data
    assert data["playbook_yaml"].startswith("-")


def test_schema_endpoint(tmp_path, monkeypatch):
    # Setup schema
    dummy_schema = {"options": {"foo": {}}}
    monkeypatch.setattr('backend.app.schemas', {"lineinfile": dummy_schema})
    resp = client.get('/v1/schema', params={'module': 'ansible.builtin.lineinfile'})
    assert resp.status_code == 200
    assert resp.json() == dummy_schema


def test_history_endpoint():
    resp = client.get('/v1/history')
    assert resp.status_code == 200
    assert resp.json() == []


def test_feedback_endpoint(monkeypatch):
    # We need to mock the playbook service to avoid the validation error
    test_uuid = "abcdef12-3456-789a-bcde-f1234567890f"  # Valid UUID format
    
    # Create a simple mock for the _get_playbook_path method to bypass validation
    def mock_get_playbook_path(self, playbook_id):
        return "/tmp/playbook.yml"
    
    # Patch the method in the PlaybookService class
    monkeypatch.setattr("backend.services.playbook_service.PlaybookService._get_playbook_path", mock_get_playbook_path)
    
    # Now the API call should work
    payload = {"playbook_id": test_uuid, "rating": 1, "comment": "ok"}
    resp = client.post('/v1/feedback', json=payload)
    assert resp.status_code == 200
    assert "status" in resp.json()
