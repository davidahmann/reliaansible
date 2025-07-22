"""Tests for the backend services."""
import pytest
from pathlib import Path

from backend.llm_adapter import LLMClient
from backend.services.playbook_service import PlaybookService, PlaybookValidationError

class MockLLMClient(LLMClient):
    """Mock LLM client for testing."""
    
    def __init__(self):
        self.response = "- name: test task\n  ansible.builtin.debug:\n    msg: test"
        
    def generate(self, prompt: str) -> str:
        """Return a predefined response."""
        return self.response

@pytest.fixture
def playbook_service():
    """Fixture for PlaybookService with a mock LLM client."""
    return PlaybookService(MockLLMClient())

@pytest.fixture
def test_schema():
    """Fixture for a test schema."""
    return {
        "module": "ansible.builtin.debug",
        "options": {
            "msg": {
                "description": "The message to display",
                "type": "str"
            }
        }
    }

def test_generate_playbook(playbook_service, test_schema, tmp_path, monkeypatch):
    """Test generating a playbook."""
    # Set playbook dir to a temp directory
    monkeypatch.setattr("backend.config.settings.PLAYBOOK_DIR", tmp_path)
    
    # Generate a playbook
    playbook_id, content = playbook_service.generate_playbook(
        module="ansible.builtin.debug",
        prompt="Show a test message",
        schema=test_schema
    )
    
    # Check that the playbook was created
    assert Path(tmp_path / f"{playbook_id}.yml").exists()
    assert content == "- name: test task\n  ansible.builtin.debug:\n    msg: test"

def test_get_playbook_path_not_found(playbook_service, tmp_path, monkeypatch):
    """Test getting a non-existent playbook path."""
    # Set playbook dir to a temp directory
    monkeypatch.setattr("backend.config.settings.PLAYBOOK_DIR", tmp_path)
    
    # Try to get a non-existent playbook
    with pytest.raises(PlaybookValidationError, match="Playbook not found"):
        playbook_service._get_playbook_path("00000000-0000-0000-0000-000000000000")

def test_get_playbook_path_invalid_id(playbook_service):
    """Test getting a playbook with an invalid ID."""
    # Try to get a playbook with an invalid ID
    with pytest.raises(PlaybookValidationError, match="Invalid playbook ID format"):
        playbook_service._get_playbook_path("invalid-id")

def test_determine_molecule_image(playbook_service, tmp_path):
    """Test determining the molecule image based on playbook content."""
    # Create test playbooks
    deb_path = tmp_path / "deb.yml"
    deb_path.write_text("- name: Install package\n  apt: name=test")
    
    yum_path = tmp_path / "yum.yml"
    yum_path.write_text("- name: Install package\n  yum: name=test")
    
    other_path = tmp_path / "other.yml"
    other_path.write_text("- name: Do something\n  debug: msg=test")
    
    # Test image selection
    assert "ubuntu" in playbook_service._determine_molecule_image(deb_path)
    assert "centos" in playbook_service._determine_molecule_image(yum_path)
    assert "ubuntu" in playbook_service._determine_molecule_image(other_path)  # Default