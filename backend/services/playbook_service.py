"""Service layer for playbook-related operations."""
import json
import logging
import shutil
import structlog
import subprocess
import uuid
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime


from ..config import settings
from ..llm_adapter import LLMClient
from ..cache import playbook_cache
from .. import database
from ..utils import validate_safe_path, is_safe_file_name

# Configure loggers
logger = logging.getLogger(__name__)
structured_logger = structlog.get_logger(__name__)

class PlaybookValidationError(Exception):
    """Raised when playbook validation fails."""
    pass

class PlaybookExecutionError(Exception):
    """Raised when playbook execution fails."""
    pass

class PlaybookService:
    """Service for playbook generation, validation, and testing."""
    
    def __init__(self, llm_client: LLMClient, use_cache: bool = True):
        """Initialize the service with an LLM client."""
        self.llm_client = llm_client
        self.use_cache = use_cache
    
    def _get_cache_key(self, module: str, prompt: str) -> str:
        """Generate a deterministic cache key for a playbook request."""
        # Create a deterministic hash of the module and prompt
        key_content = f"{module}:{prompt}".lower()
        key_hash = hashlib.md5(key_content.encode()).hexdigest()
        return f"playbook:{key_hash}"
        
    def generate_playbook(self, module: str, prompt: str, schema: Dict[str, Any], 
                         user_id: str = "anonymous") -> Tuple[str, str]:
        """Generate a playbook using the LLM and return the ID and content."""
        # Check cache if enabled
        if self.use_cache:
            cache_key = self._get_cache_key(module, prompt)
            cached_result = playbook_cache.get(cache_key)
            if cached_result:
                playbook_id, yaml_content = cached_result
                logger.info(f"Using cached playbook {playbook_id} for {module} prompt")
                
                # Ensure the file exists (might have been cleaned up)
                pb_path = settings.PLAYBOOK_DIR / f"{playbook_id}.yml"
                if not pb_path.exists():
                    logger.info(f"Cached playbook file not found, recreating: {playbook_id}")
                    self._save_playbook(playbook_id, yaml_content)
                
                # Record telemetry for cache hit
                if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                    database.record_telemetry(
                        "generate_cache_hit",
                        {
                            "module": module,
                            "playbook_id": playbook_id,
                            "cache_key": cache_key[:10],
                        },
                        user_id=user_id
                    )
                
                return playbook_id, yaml_content
        
        # Cache miss, create a new playbook
        # Create module-specific prompt
        start_time = datetime.now()
        opts = json.dumps(schema["options"], indent=2)
        llm_prompt = (
            f"Generate an Ansible task using {module}.\n"
            f"Parameters:\n{opts}\n"
            f"Task: {prompt}\n"
            f"Return YAML only."
        )
        
        # Generate YAML via LLM
        yaml_content = self.llm_client.generate(llm_prompt)
        
        # Create unique playbook ID and save
        playbook_id = str(uuid.uuid4())
        self._save_playbook(playbook_id, yaml_content)
        
        # Store in cache if enabled
        if self.use_cache:
            cache_key = self._get_cache_key(module, prompt)
            playbook_cache.set(cache_key, (playbook_id, yaml_content))
            logger.debug(f"Cached playbook {playbook_id} with key {cache_key[:10]}...")
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Generated playbook {playbook_id} in {duration:.2f}s")
        
        # Record playbook in database
        if settings.DB_ENABLED:
            try:
                database.record_playbook(
                    playbook_id=playbook_id,
                    module=module,
                    prompt=prompt,
                    yaml_content=yaml_content,
                    user_id=user_id
                )
                
                # Record telemetry for generation
                if settings.COLLECT_TELEMETRY:
                    database.record_telemetry(
                        "generate",
                        {
                            "module": module,
                            "playbook_id": playbook_id,
                            "duration_ms": int(duration * 1000),
                            "yaml_length": len(yaml_content),
                        },
                        user_id=user_id
                    )
            except Exception as e:
                logger.error(f"Failed to record playbook in database: {e}")
        
        return playbook_id, yaml_content
        
    def lint_playbook(self, playbook_id: str, timeout: int = 30, 
                      user_id: str = "anonymous") -> List[str]:
        """Lint a playbook using ansible-lint and return errors."""
        # Get playbook path
        pb_path = self._get_playbook_path(playbook_id)
        
        # Check if we have cached lint results
        if self.use_cache:
            cache_key = f"lint:{playbook_id}"
            cached_errors = playbook_cache.get(cache_key)
            if cached_errors is not None:
                logger.info(f"Using cached lint results for {playbook_id}")
                
                # Record telemetry for cache hit
                if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                    database.record_telemetry(
                        "lint_cache_hit",
                        {
                            "playbook_id": playbook_id,
                            "error_count": len(cached_errors),
                        },
                        user_id=user_id
                    )
                
                return cached_errors
        
        # Run ansible-lint
        start_time = datetime.now()
        try:
            proc = subprocess.run(
                ["ansible-lint", "-p", str(pb_path)], 
                capture_output=True, 
                text=True,
                timeout=timeout,
            )
            
            # Parse results
            errors = proc.stdout.splitlines() if proc.stdout else []
            
            # Cache the results
            if self.use_cache:
                cache_key = f"lint:{playbook_id}"
                playbook_cache.set(cache_key, errors, ttl_seconds=3600)  # Cache for 1 hour
                logger.debug(f"Cached lint results for {playbook_id}")
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Linted playbook {playbook_id} in {duration:.2f}s, found {len(errors)} issues")
            
            # Update playbook status and record telemetry
            if settings.DB_ENABLED:
                try:
                    # Update playbook status
                    database.update_playbook_status(playbook_id, "linted")
                    
                    # Record telemetry
                    if settings.COLLECT_TELEMETRY:
                        database.record_telemetry(
                            "lint",
                            {
                                "playbook_id": playbook_id,
                                "duration_ms": int(duration * 1000),
                                "error_count": len(errors),
                                "exit_code": proc.returncode,
                            },
                            user_id=user_id
                        )
                except Exception as e:
                    logger.error(f"Failed to record lint data in database: {e}")
            
            return errors
            
        except subprocess.TimeoutExpired:
            structured_logger.error("Linting timeout", playbook_id=playbook_id)
            if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "lint_timeout",
                    {"playbook_id": playbook_id, "timeout": timeout},
                    user_id=user_id
                )
            raise PlaybookExecutionError("Linting process timed out")
        except Exception as e:
            structured_logger.error("Linting error", playbook_id=playbook_id, error=str(e))
            if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "lint_error",
                    {"playbook_id": playbook_id, "error": str(e)},
                    user_id=user_id
                )
            raise PlaybookExecutionError(f"Linting failed: {e}")
    
    def test_playbook(self, playbook_id: str, timeout: int = 60, 
                       user_id: str = "anonymous") -> Tuple[str, str]:
        """Test a playbook using Molecule and return status and logs."""
        # Get playbook path
        pb_path = self._get_playbook_path(playbook_id)
        
        # Check if we have cached test results (future enhancement)
        # For now, we run tests every time as they're more dynamic
        
        start_time = datetime.now()
        try:
            # Create molecule scenario directory
            scenario_dir = settings.PLAYBOOK_DIR / playbook_id / "molecule" / "default"
            scenario_dir.mkdir(parents=True, exist_ok=True)
            
            # Determine Docker image based on playbook content
            image = self._determine_molecule_image(pb_path)

            # Create molecule.yml config
            molecule_config = f"""---
driver:
  name: docker
platforms:
  - name: instance
    image: {image}
provisioner:
  name: ansible
  playbooks:
    converge: ../../../../{pb_path.relative_to(settings.PLAYBOOK_DIR.parent)}
"""
            (scenario_dir / "molecule.yml").write_text(molecule_config)
            
            # Run molecule test with timeout
            proc = subprocess.run(
                ["molecule", "test"], 
                cwd=scenario_dir.parent.parent, 
                capture_output=True, 
                text=True,
                timeout=timeout,
            )
            
            # Process results
            status = "passed" if proc.returncode == 0 else "failed"
            logs = proc.stdout + proc.stderr
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Tested playbook {playbook_id} in {duration:.2f}s: {status}")
            
            # Update playbook status and record telemetry
            if settings.DB_ENABLED:
                try:
                    # Update playbook status to include test result
                    database.update_playbook_status(playbook_id, f"tested_{status}")
                    
                    # Record telemetry
                    if settings.COLLECT_TELEMETRY:
                        database.record_telemetry(
                            "test",
                            {
                                "playbook_id": playbook_id,
                                "duration_ms": int(duration * 1000),
                                "status": status,
                                "exit_code": proc.returncode,
                                "log_length": len(logs),
                                "image": image,
                            },
                            user_id=user_id
                        )
                except Exception as e:
                    logger.error(f"Failed to record test data in database: {e}")
            
            return status, logs
            
        except subprocess.TimeoutExpired:
            structured_logger.error("Testing timeout", playbook_id=playbook_id)
            if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "test_timeout",
                    {"playbook_id": playbook_id, "timeout": timeout},
                    user_id=user_id
                )
            raise PlaybookExecutionError("Testing process timed out")
        except Exception as e:
            structured_logger.error("Testing error", playbook_id=playbook_id, error=str(e))
            if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "test_error",
                    {"playbook_id": playbook_id, "error": str(e)},
                    user_id=user_id
                )
            raise PlaybookExecutionError(f"Testing failed: {e}")
    
    def cleanup_molecule_artifacts(self, playbook_id: str):
        """Clean up molecule artifacts with security validation."""
        try:
            # Validate UUID format to prevent path injection
            try:
                uuid.UUID(playbook_id)
            except ValueError:
                structured_logger.error("Invalid playbook ID format for cleanup", playbook_id=playbook_id)
                raise PlaybookValidationError("Invalid playbook ID format")
            
            # Validate the directory name is safe
            if not is_safe_file_name(playbook_id):
                structured_logger.error("Potentially malicious playbook ID for cleanup", playbook_id=playbook_id)
                raise PlaybookValidationError("Invalid playbook ID")
                
            # Use our path validation function to ensure we're accessing a safe path
            playbook_dir_path = validate_safe_path(settings.PLAYBOOK_DIR, playbook_id)
            if not playbook_dir_path or not playbook_dir_path.exists():
                structured_logger.error("Playbook directory not found or validation failed", playbook_id=playbook_id)
                return  # Nothing to clean up
                
            molecule_dir = playbook_dir_path / "molecule"
            if molecule_dir.exists():
                # Validate the molecule directory path
                if not str(molecule_dir).startswith(str(settings.PLAYBOOK_DIR)):
                    structured_logger.error("Path traversal attempt in molecule cleanup", playbook_id=playbook_id)
                    return
                    
                # Run molecule destroy to clean up containers
                subprocess.run(
                    ["molecule", "destroy"], 
                    cwd=molecule_dir.parent, 
                    capture_output=True, 
                    timeout=60,
                )
                
                # Remove molecule directory - final validation before deletion
                if molecule_dir.parent.exists() and molecule_dir.parent.is_dir() and \
                   str(molecule_dir.parent).startswith(str(settings.PLAYBOOK_DIR)):
                    shutil.rmtree(molecule_dir.parent, ignore_errors=True)
                
            logger.info("Molecule cleanup completed", playbook_id=playbook_id)
        except PlaybookValidationError:
            # Validation errors are already logged
            pass
        except Exception as e:
            structured_logger.error("Molecule cleanup failed", playbook_id=playbook_id, error=str(e))
    
    def _save_playbook(self, playbook_id: str, content: str) -> Path:
        """Save playbook content to file and return the path with security validation."""
        # Validate UUID format to prevent path injection
        try:
            uuid.UUID(playbook_id)
        except ValueError:
            structured_logger.error("Invalid playbook ID format for saving", playbook_id=playbook_id)
            raise PlaybookValidationError("Invalid playbook ID format")
        
        # Ensure the playbook directory exists
        settings.PLAYBOOK_DIR.mkdir(exist_ok=True)
        
        # Validate the filename is safe
        if not is_safe_file_name(f"{playbook_id}.yml"):
            structured_logger.error("Potentially malicious playbook ID for saving", playbook_id=playbook_id)
            raise PlaybookValidationError("Invalid playbook ID")
        
        # Construct and validate the path
        file_path = f"{playbook_id}.yml"
        safe_path = validate_safe_path(settings.PLAYBOOK_DIR, file_path)
        
        if not safe_path:
            structured_logger.error("Path validation failed for saving", playbook_id=playbook_id)
            raise PlaybookValidationError("Invalid playbook path")
        
        # Write the content
        safe_path.write_text(content)
        return safe_path
    
    def _get_playbook_path(self, playbook_id: str) -> Path:
        """Get path to playbook, raising PlaybookValidationError if not found or invalid."""
        try:
            # Validate UUID format to prevent path injection
            try:
                uuid.UUID(playbook_id)
            except ValueError:
                structured_logger.error("Invalid playbook ID format", playbook_id=playbook_id)
                raise PlaybookValidationError("Invalid playbook ID format")
            
            # Validate the playbook ID is safe
            if not is_safe_file_name(f"{playbook_id}.yml"):
                structured_logger.error("Potentially malicious playbook ID", playbook_id=playbook_id)
                raise PlaybookValidationError("Invalid playbook ID")
            
            # Create the path and validate it's within the allowed directory
            file_path = f"{playbook_id}.yml"
            safe_path = validate_safe_path(settings.PLAYBOOK_DIR, file_path)
            
            if not safe_path:
                structured_logger.error("Path validation failed", playbook_id=playbook_id)
                raise PlaybookValidationError("Invalid playbook path")
            
            # Check existence
            if not safe_path.exists():
                structured_logger.error("Playbook not found", playbook_id=playbook_id)
                raise PlaybookValidationError("Playbook not found")
                
            return safe_path
        except PlaybookValidationError:
            # Re-raise validation errors
            raise
        except Exception as e:
            structured_logger.error("Error accessing playbook", playbook_id=playbook_id, error=str(e))
            raise PlaybookValidationError(f"Error accessing playbook: {e}")
    
    def _determine_molecule_image(self, playbook_path: Path) -> str:
        """Determine the appropriate Docker image for Molecule testing based on playbook content."""
        text = playbook_path.read_text().lower()
        if any(k in text for k in ("apt", "deb")):
            return "geerlingguy/docker-ubuntu2004-ansible:latest"
        if any(k in text for k in ("yum", "dnf")):
            return "geerlingguy/docker-centos7-ansible:latest"
        return "geerlingguy/docker-ubuntu2004-ansible:latest"