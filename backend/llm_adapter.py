"""LLM Adapter with retry + timeout using tenacity."""
from __future__ import annotations
import os
import json
import logging
import yaml
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import time

from tenacity import (
    retry, 
    stop_after_attempt, 
    wait_exponential, 
    retry_if_exception_type
)

# Configure module-level logger
logger = logging.getLogger(__name__)

class LLMError(Exception):
    """Base exception for LLM-related errors."""
    pass

class LLMTimeoutError(LLMError):
    """Raised when LLM request times out."""
    pass

class LLMConnectionError(LLMError):
    """Raised when connection to LLM provider fails."""
    pass

class LLMAuthenticationError(LLMError):
    """Raised when authentication with LLM provider fails."""
    pass

class LLMValidationError(LLMError):
    """Raised when response validation fails."""
    pass

class LLMClient(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate and return a YAML string from the LLM."""
        
    def validate_yaml(self, content: str) -> str:
        """Validate that the response is valid YAML."""
        try:
            if not content or not content.strip():
                raise LLMValidationError("Empty response from LLM")
                
            # Try to parse as YAML to validate
            yaml.safe_load(content)
            return content
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in LLM response: {e}")
            raise LLMValidationError(f"LLM generated invalid YAML: {e}")

# --- OpenAI Adapter --------------------------------------------------------
class OpenAIClient(LLMClient):
    def __init__(self, model: Optional[str] = None, use_cache: bool = True):
        try:
            from .cache import llm_cache
            self.use_cache = use_cache
            self.llm_cache = llm_cache

            import openai
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                # Try reading from ~/.reliarc
                try:
                    reliarc_path = Path.home().joinpath(".reliarc")
                    if reliarc_path.exists():
                        cfg = json.loads(reliarc_path.read_text(encoding="utf-8"))
                        key = cfg.get("OPENAI_API_KEY")
                except (json.JSONDecodeError, FileNotFoundError) as e:
                    logger.warning(f"Failed to read ~/.reliarc: {e}")
                    
            if not key:
                raise LLMAuthenticationError("OPENAI_API_KEY not set in env or ~/.reliarc")
                
            openai.api_key = key
            self._client = openai
            self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            logger.info(f"OpenAI client initialized with model: {self.model}")
        except ImportError:
            raise LLMError("openai package not installed. Run 'pip install openai'.")
    
    def _get_cache_key(self, prompt: str) -> str:
        """Generate a cache key for the prompt."""
        # Use a hash of the prompt and model as the cache key
        import hashlib
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        
        # Create a semantic key for similar prompts
        # Extract key elements from the prompt (module name and task description)
        import re
        module_match = re.search(r"using\s+([a-z0-9_.]+)", prompt, re.IGNORECASE)
        module = module_match.group(1) if module_match else ""
        
        task_match = re.search(r"Task:\s*(.+?)(?:\n|$)", prompt, re.IGNORECASE)
        task = task_match.group(1) if task_match else ""
        
        # Create a normalized task string (lowercase, remove stop words)
        stop_words = {"a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "with"}
        normalized_task = " ".join([word for word in task.lower().split() if word not in stop_words])
        
        # Create a semantic fingerprint
        semantic_key = f"{module}:{normalized_task}"
        semantic_hash = hashlib.md5(semantic_key.encode()).hexdigest()
        
        return f"openai:{self.model}:{prompt_hash}:{semantic_hash}"
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def generate(self, prompt: str) -> str:
        """Generate YAML response from OpenAI with caching."""
        # Check cache first if enabled
        if self.use_cache:
            cache_key = self._get_cache_key(prompt)
            cached_response = self.llm_cache.get(cache_key)
            if cached_response:
                logger.info(f"Using cached response for {cache_key[:10]}...")
                return cached_response
        
        try:
            start_time = time.time()
            logger.info(f"Sending request to OpenAI model: {self.model}")
            
            resp = self._client.ChatCompletion.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.3,
                request_timeout=30,
            )
            
            duration = time.time() - start_time
            logger.info(f"OpenAI response received in {duration:.2f}s")
            
            content = resp.choices[0].message.content
            validated_content = self.validate_yaml(content)
            
            # Store in cache if enabled
            if self.use_cache:
                cache_key = self._get_cache_key(prompt)
                self.llm_cache.set(cache_key, validated_content)
                logger.debug(f"Cached response with key {cache_key[:10]}...")
            
            return validated_content
            
        except TimeoutError as e:
            logger.error(f"OpenAI request timed out: {e}")
            raise LLMTimeoutError(f"OpenAI request timed out: {e}")
        except ConnectionError as e:
            logger.error(f"Failed to connect to OpenAI: {e}")
            raise LLMConnectionError(f"Failed to connect to OpenAI: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in OpenAI request: {e}")
            raise LLMError(f"OpenAI request failed: {e}")

# --- AWS Bedrock Adapter ----------------------------------------------------
class BedrockClient(LLMClient):
    def __init__(self, model_id: Optional[str] = None, use_cache: bool = True):
        try:
            from .cache import llm_cache
            self.use_cache = use_cache
            self.llm_cache = llm_cache

            import boto3
            self._client = boto3.client("bedrock-runtime")
            self.model_id = model_id or os.getenv("BEDROCK_MODEL", "anthropic.claude-instant-v1")
            logger.info(f"AWS Bedrock client initialized with model: {self.model_id}")
        except ImportError:
            raise LLMError("boto3 package not installed. Run 'pip install boto3'.")
        except Exception as e:
            raise LLMConnectionError(f"Failed to initialize AWS Bedrock client: {e}")
    
    def _get_cache_key(self, prompt: str) -> str:
        """Generate a cache key for the prompt."""
        # Use a hash of the prompt and model as the cache key
        import hashlib
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        
        # Create a semantic key for similar prompts
        # Extract key elements from the prompt (module name and task description)
        import re
        module_match = re.search(r"using\s+([a-z0-9_.]+)", prompt, re.IGNORECASE)
        module = module_match.group(1) if module_match else ""
        
        task_match = re.search(r"Task:\s*(.+?)(?:\n|$)", prompt, re.IGNORECASE)
        task = task_match.group(1) if task_match else ""
        
        # Create a normalized task string (lowercase, remove stop words)
        stop_words = {"a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "with"}
        normalized_task = " ".join([word for word in task.lower().split() if word not in stop_words])
        
        # Create a semantic fingerprint
        semantic_key = f"{module}:{normalized_task}"
        semantic_hash = hashlib.md5(semantic_key.encode()).hexdigest()
        
        return f"bedrock:{self.model_id}:{prompt_hash}:{semantic_hash}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def generate(self, prompt: str) -> str:
        """Generate YAML response from AWS Bedrock with caching."""
        # Check cache first if enabled
        if self.use_cache:
            cache_key = self._get_cache_key(prompt)
            cached_response = self.llm_cache.get(cache_key)
            if cached_response:
                logger.info(f"Using cached response for {cache_key[:10]}...")
                return cached_response
        
        try:
            start_time = time.time()
            logger.info(f"Sending request to AWS Bedrock model: {self.model_id}")
            
            payload = json.dumps({
                "prompt": prompt,
                "max_tokens_to_sample": 600,
                "temperature": 0.3,
                "top_p": 0.9,
            })
            
            resp = self._client.invoke_model(
                body=payload,
                modelId=self.model_id,
                accept="application/json",
                contentType="application/json"
            )
            
            duration = time.time() - start_time
            logger.info(f"AWS Bedrock response received in {duration:.2f}s")
            
            body = resp["body"].read()
            content = json.loads(body)["completion"]
            validated_content = self.validate_yaml(content)
            
            # Store in cache if enabled
            if self.use_cache:
                cache_key = self._get_cache_key(prompt)
                self.llm_cache.set(cache_key, validated_content)
                logger.debug(f"Cached response with key {cache_key[:10]}...")
            
            return validated_content
            
        except TimeoutError as e:
            logger.error(f"AWS Bedrock request timed out: {e}")
            raise LLMTimeoutError(f"AWS Bedrock request timed out: {e}")
        except ConnectionError as e:
            logger.error(f"Failed to connect to AWS Bedrock: {e}")
            raise LLMConnectionError(f"Failed to connect to AWS Bedrock: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AWS Bedrock response: {e}")
            raise LLMError(f"Failed to parse AWS Bedrock response: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in AWS Bedrock request: {e}")
            raise LLMError(f"AWS Bedrock request failed: {e}")

# --- Factory ---------------------------------------------------------------
def get_client() -> LLMClient:
    """Return an LLMClient based on RELIA_LLM env ("bedrock" or default OpenAI)."""
    try:
        provider = os.getenv("RELIA_LLM", "openai").lower()
        logger.info(f"Initializing LLM client for provider: {provider}")
        
        if provider == "bedrock":
            return BedrockClient()
        elif provider == "openai":
            return OpenAIClient()
        else:
            raise LLMError(f"Unsupported LLM provider: {provider}")
    except Exception as e:
        logger.exception(f"Failed to initialize LLM client: {e}")
        raise
