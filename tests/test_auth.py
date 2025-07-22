"""Tests for the authentication module."""
import pytest
import jwt
import time
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.auth import (
    create_token, 
    verify_token, 
    get_current_user, 
    role_required,
    AuthError
)

@pytest.fixture
def mock_request():
    """Mock request for testing."""
    class MockRequest:
        def __init__(self):
            self.url = type('obj', (object,), {'path': '/test'})
            self.method = 'GET'
            self.client = type('obj', (object,), {'host': '127.0.0.1'})
    return MockRequest()

@pytest.fixture
def mock_credentials():
    """Mock credentials for testing."""
    return HTTPAuthorizationCredentials(scheme="bearer", credentials="test-token")

def test_create_token():
    """Test creating a JWT token."""
    with patch('backend.auth.SECRET', 'test-secret'):
        token_data = create_token("test-user", ["generator"], 1)
        # The create_token function returns a dictionary with tokens
        assert "access_token" in token_data
        assert "refresh_token" in token_data
        assert token_data["token_type"] == "bearer"
        
        # Decode and verify the access token (with verification disabled)
        access_token = token_data["access_token"]
        # Disable token verification since we're generating a real token with current timestamp
        payload = jwt.decode(access_token, "test-secret", algorithms=["HS256"], 
                            options={"verify_exp": False, "verify_iat": False})
        assert payload["sub"] == "test-user"
        assert "generator" in payload["roles"]
        # Just check that exp and iat exist
        assert "exp" in payload
        assert "iat" in payload
        assert payload["type"] == "access"

def test_verify_token_valid():
    """Test verifying a valid token."""
    with patch('backend.auth.SECRET', 'test-secret'):
        # Create a token with 1 hour expiry
        expiry = time.time() + 3600
        token = jwt.encode(
            {"sub": "test-user", "roles": ["generator"], "exp": expiry},
            "test-secret",
            algorithm="HS256"
        )
        
        # Verify the token
        payload = verify_token(token)
        assert payload["sub"] == "test-user"
        assert "generator" in payload["roles"]

def test_verify_token_expired():
    """Test verifying an expired token."""
    with patch('backend.auth.SECRET', 'test-secret'):
        # Create a token that has expired
        expiry = time.time() - 3600
        token = jwt.encode(
            {"sub": "test-user", "roles": ["generator"], "exp": expiry},
            "test-secret",
            algorithm="HS256"
        )
        
        # Verify the token - PyJWT expiry messages may differ,
        # so check for either direct "Token has expired" or any expiry message
        with pytest.raises(AuthError, match="(Token has expired|.*expired.*)"):
            verify_token(token)

def test_verify_token_invalid():
    """Test verifying an invalid token."""
    with patch('backend.auth.SECRET', 'test-secret'):
        # Create a token with a different secret
        token = jwt.encode(
            {"sub": "test-user", "roles": ["generator"]},
            "wrong-secret",
            algorithm="HS256"
        )
        
        # Verify the token
        with pytest.raises(AuthError, match="Invalid token"):
            verify_token(token)

@pytest.mark.asyncio
async def test_get_current_user_auth_disabled(mock_request):
    """Test getting the current user with authentication disabled."""
    with patch('backend.auth.SECRET', None):
        user = await get_current_user(mock_request, None)
        assert user["sub"] == "anonymous"
        assert "generator" in user["roles"]
        assert "tester" in user["roles"]

@pytest.mark.asyncio
async def test_get_current_user_with_valid_token(mock_request, mock_credentials):
    """Test getting the current user with a valid token."""
    with patch('backend.auth.SECRET', 'test-secret'), \
         patch('backend.auth.verify_token') as mock_verify:
        mock_verify.return_value = {"sub": "test-user", "roles": ["generator"]}
        
        user = await get_current_user(mock_request, mock_credentials)
        assert user["sub"] == "test-user"
        assert "generator" in user["roles"]

@pytest.mark.asyncio
async def test_get_current_user_with_invalid_token(mock_request, mock_credentials):
    """Test getting the current user with an invalid token."""
    with patch('backend.auth.SECRET', 'test-secret'), \
         patch('backend.auth.verify_token') as mock_verify:
        mock_verify.side_effect = AuthError("Invalid token")
        
        with pytest.raises(HTTPException) as excinfo:
            await get_current_user(mock_request, mock_credentials)
        
        assert excinfo.value.status_code == 401
        assert "Invalid token" in excinfo.value.detail

def test_role_required_with_required_role(mock_request):
    """Test role_required with a user that has the required role."""
    user_data = {"sub": "test-user", "roles": ["generator"]}
    
    # Create a dependency
    checker = role_required("generator")
    
    # The role_required function returns a callable dependency that takes
    # a user object directly, as it is used after get_current_user dependency
    # It's not async in the actual implementation
    result = checker(request=mock_request, user=user_data)
    
    # Result should be the user object
    assert result == user_data
    assert result["sub"] == "test-user"
    assert "generator" in result["roles"]

def test_role_required_without_required_role(mock_request):
    """Test role_required with a user that doesn't have the required role."""
    user_data = {"sub": "test-user", "roles": ["generator"]}
    
    # Create a dependency
    checker = role_required("admin")
    
    # Call the checker, should raise an HTTPException
    with pytest.raises(HTTPException) as excinfo:
        checker(request=mock_request, user=user_data)
    
    assert excinfo.value.status_code == 403
    assert "admin" in excinfo.value.detail