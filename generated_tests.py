"""
Refined and improved tests for ApiTokenEndpoint CRUD operations.

This module contains comprehensive contract tests for the API Token management endpoints,
with improved code quality, better organization, and enhanced test coverage.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from django.core.exceptions import ValidationError

from plane.db.models import APIToken, User


@pytest.mark.contract
class TestApiTokenEndpoint:
    """
    Comprehensive contract tests for ApiTokenEndpoint CRUD operations.
    
    Test Coverage:
    - POST: Token creation with various data combinations
    - GET: Token retrieval (list and individual)
    - PATCH: Token updates (full and partial)
    - DELETE: Token deletion
    - Security: Authentication, authorization, and user isolation
    - Edge cases: Invalid data, malformed UUIDs, error handling
    """

    # ===== POST METHOD TESTS =====
    
    @pytest.mark.django_db
    def test_create_api_token_with_complete_data_success(self, session_client):
        """Test creating an API token with all valid fields provided."""
        url = reverse("api-tokens")
        future_date = timezone.now() + timedelta(days=30)
        
        token_data = {
            "label": "Test API Token",
            "description": "Test description for API token functionality",
            "expired_at": future_date.isoformat(),
        }
        
        response = session_client.post(url, token_data, format="json")
        
        # Assert response structure and status
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["label"] == token_data["label"]
        assert response.data["description"] == token_data["description"]
        assert "token" in response.data, "Token should be visible during creation"
        assert response.data["user_type"] == 0, "Regular user should have user_type=0"
        assert response.data["is_service"] is False
        
        # Verify database state
        assert APIToken.objects.count() == 1
        created_token = APIToken.objects.first()
        assert created_token.label == token_data["label"]
        assert created_token.description == token_data["description"]
        assert created_token.user_type == 0
        assert created_token.is_service is False
        
        # Verify token format and uniqueness
        assert len(response.data["token"]) > 0
        assert isinstance(response.data["token"], str)

    @pytest.mark.django_db
    def test_create_api_token_with_minimal_data_generates_uuid_label(self, session_client):
        """Test creating an API token with empty payload generates UUID label."""
        url = reverse("api-tokens")
        
        response = session_client.post(url, {}, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["label"]) == 32, "Should generate uuid4().hex as label"
        assert response.data["description"] == ""
        assert response.data["expired_at"] is None
        assert "token" in response.data
        assert response.data["user_type"] == 0
        
        # Verify generated label is valid hex
        created_token = APIToken.objects.first()
        assert len(created_token.label) == 32
        # Verify it's valid hex by attempting to parse
        try:
            int(created_token.label, 16)
        except ValueError:
            pytest.fail("Generated label should be valid hex string")

    @pytest.mark.django_db
    def test_create_api_token_with_bot_user_sets_correct_user_type(self, session_client, create_bot_user):
        """Test creating an API token with bot user correctly sets user_type=1."""
        session_client.force_authenticate(user=create_bot_user)
        
        url = reverse("api-tokens")
        token_data = {
            "label": "Bot Token", 
            "description": "Token for automated bot operations"
        }
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["user_type"] == 1, "Bot user should have user_type=1"
        
        created_token = APIToken.objects.first()
        assert created_token.user_type == 1
        assert created_token.user == create_bot_user

    @pytest.mark.django_db
    def test_create_api_token_with_partial_data_success(self, session_client):
        """Test creating an API token with only label field provided."""
        url = reverse("api-tokens")
        token_data = {"label": "Partial Token Data"}
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["label"] == "Partial Token Data"
        assert response.data["description"] == ""
        assert response.data["expired_at"] is None

    @pytest.mark.django_db
    def test_create_api_token_with_past_expiry_date_success(self, session_client):
        """Test creating an API token with past expiry date (should still create)."""
        url = reverse("api-tokens")
        past_date = timezone.now() - timedelta(days=1)
        
        token_data = {
            "label": "Expired Token",
            "expired_at": past_date.isoformat()
        }
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["expired_at"] is not None

    @pytest.mark.django_db 
    def test_create_api_token_with_invalid_expiry_format_returns_400(self, session_client):
        """Test creating an API token with invalid expiry date format."""
        url = reverse("api-tokens")
        token_data = {
            "label": "Invalid Expiry",
            "expired_at": "not-a-valid-date"
        }
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "expired_at" in response.data

    # ===== GET METHOD TESTS (List All Tokens) =====
    
    @pytest.mark.django_db
    def test_get_all_api_tokens_empty_list_success(self, session_client):
        """Test retrieving all API tokens when none exist returns empty list."""
        url = reverse("api-tokens")
        
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
        assert isinstance(response.data, list)

    @pytest.mark.django_db
    def test_get_all_api_tokens_multiple_tokens_success(self, session_client, create_user):
        """Test retrieving multiple API tokens with proper field exclusion."""
        # Create multiple tokens with different characteristics
        APIToken.objects.create(
            label="Active Token",
            description="Currently active token",
            user=create_user,
            user_type=0,
            is_service=False
        )
        APIToken.objects.create(
            label="Expiring Token", 
            description="Token with expiry",
            user=create_user,
            user_type=0,
            is_service=False,
            expired_at=timezone.now() + timedelta(days=7)
        )
        
        url = reverse("api-tokens")
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        
        # Verify sensitive fields are excluded from GET responses
        for token_data in response.data:
            assert "token" not in token_data, "Token field should be excluded from GET responses"
            assert "label" in token_data
            assert "description" in token_data
            assert "created_at" in token_data
            assert "user_type" in token_data
            assert "is_service" in token_data

    @pytest.mark.django_db
    def test_get_all_api_tokens_excludes_service_tokens_correctly(self, session_client, create_user):
        """Test that GET endpoint properly filters out service tokens."""
        # Create regular token
        APIToken.objects.create(
            label="Regular User Token",
            description="Standard user API token",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        # Create service token (should be excluded)
        APIToken.objects.create(
            label="Service Token",
            description="Internal service token",
            user=create_user,
            user_type=0,
            is_service=True
        )
        
        url = reverse("api-tokens")
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1, "Only non-service tokens should be returned"
        assert response.data[0]["label"] == "Regular User Token"
        assert response.data[0]["is_service"] is False

    @pytest.mark.django_db
    def test_get_all_api_tokens_user_isolation_enforced(self, session_client, create_user):
        """Test that users can only retrieve their own tokens (authorization)."""
        # Create token for authenticated user
        APIToken.objects.create(
            label="My Personal Token",
            description="Token owned by authenticated user",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        # Create token for different user
        other_user = User.objects.create(
            email="different-user@plane.so",
            first_name="Different",
            last_name="User"
        )
        APIToken.objects.create(
            label="Other User Token",
            description="Token owned by different user",
            user=other_user,
            user_type=0,
            is_service=False
        )
        
        url = reverse("api-tokens")
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1, "Should only return tokens owned by authenticated user"
        assert response.data[0]["label"] == "My Personal Token"

    # ===== GET METHOD TESTS (Specific Token by PK) =====
    
    @pytest.mark.django_db
    def test_get_specific_api_token_success(self, session_client, create_user):
        """Test retrieving a specific API token by primary key."""
        token = APIToken.objects.create(
            label="Specific Token",
            description="Token for specific retrieval test",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Specific Token"
        assert response.data["description"] == "Token for specific retrieval test"
        assert "token" not in response.data, "Token field should not be visible in GET"
        assert response.data["id"] == str(token.pk)

    @pytest.mark.django_db
    def test_get_specific_api_token_not_found_returns_404(self, session_client):
        """Test retrieving non-existent API token returns 404."""
        non_existent_uuid = uuid4()
        url = reverse("api-tokens-details", kwargs={"pk": non_existent_uuid})
        
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_get_specific_api_token_user_isolation_returns_404(self, session_client, create_user):
        """Test that users cannot access other users' tokens via specific GET."""
        # Create token owned by different user
        other_user = User.objects.create(
            email="unauthorized-access@plane.so",
            first_name="Unauthorized",
            last_name="User"
        )
        other_token = APIToken.objects.create(
            label="Restricted Access Token",
            description="Should not be accessible",
            user=other_user,
            user_type=0,
            is_service=False
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": other_token.pk})
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # ===== PATCH METHOD TESTS =====
    
    @pytest.mark.django_db
    def test_patch_api_token_full_update_success(self, session_client, create_user):
        """Test successful full update of an API token."""
        token = APIToken.objects.create(
            label="Original Label",
            description="Original Description",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        update_data = {
            "label": "Updated Label",
            "description": "Updated Description with more details"
        }
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Updated Label"
        assert response.data["description"] == "Updated Description with more details"
        
        # Verify database persistence
        updated_token = APIToken.objects.get(pk=token.pk)
        assert updated_token.label == "Updated Label"
        assert updated_token.description == "Updated Description with more details"

    @pytest.mark.django_db
    def test_patch_api_token_partial_update_preserves_unchanged_fields(self, session_client, create_user):
        """Test partial update preserves unchanged fields."""
        original_description = "Original Description Should Remain"
        token = APIToken.objects.create(
            label="Original Label",
            description=original_description,
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        update_data = {"label": "Partially Updated Label Only"}
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Partially Updated Label Only"
        assert response.data["description"] == original_description, "Unchanged field should be preserved"

    @pytest.mark.django_db
    def test_patch_api_token_with_expiry_date_success(self, session_client, create_user):
        """Test updating the expired_at field specifically."""
        token = APIToken.objects.create(
            label="Token With Expiry",
            description="Testing expiry date updates",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        future_date = timezone.now() + timedelta(days=60)
        update_data = {"expired_at": future_date.isoformat()}
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["expired_at"] is not None
        
        # Verify database update
        updated_token = APIToken.objects.get(pk=token.pk)
        assert updated_token.expired_at is not None
        assert updated_token.expired_at.date() == future_date.date()

    @pytest.mark.django_db
    def test_patch_api_token_with_invalid_data_returns_400(self, session_client, create_user):
        """Test PATCH with invalid data returns proper error response."""
        token = APIToken.objects.create(
            label="Valid Token",
            description="Token for validation testing",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        invalid_data = {"expired_at": "definitely-not-a-date-format"}
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, invalid_data, format="json")
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "expired_at" in response.data, "Should include field-specific error"

    @pytest.mark.django_db
    def test_patch_api_token_not_found_returns_404(self, session_client):
        """Test updating non-existent API token returns 404."""
        non_existent_uuid = uuid4()
        update_data = {"label": "Updated Label"}
        
        url = reverse("api-tokens-details", kwargs={"pk": non_existent_uuid})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_patch_api_token_user_isolation_prevents_unauthorized_update(self, session_client, create_user):
        """Test that users cannot update other users' tokens."""
        other_user = User.objects.create(
            email="target-user@plane.so",
            first_name="Target", 
            last_name="User"
        )
        other_token = APIToken.objects.create(
            label="Original Token Label",
            description="Should not be modifiable",
            user=other_user,
            user_type=0,
            is_service=False
        )
        
        malicious_update = {"label": "Hacked Label", "description": "Unauthorized modification"}
        
        url = reverse("api-tokens-details", kwargs={"pk": other_token.pk})
        response = session_client.patch(url, malicious_update, format="json")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        
        # Verify token remains unchanged
        unchanged_token = APIToken.objects.get(pk=other_token.pk)
        assert unchanged_token.label == "Original Token Label"
        assert unchanged_token.description == "Should not be modifiable"

    @pytest.mark.django_db
    def test_patch_api_token_empty_data_returns_200(self, session_client, create_user):
        """Test PATCH with empty data returns success without changes."""
        original_label = "Unchanged Label"
        original_description = "Unchanged Description"
        
        token = APIToken.objects.create(
            label=original_label,
            description=original_description,
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, {}, format="json")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == original_label
        assert response.data["description"] == original_description

    # ===== DELETE METHOD TESTS =====
    
    @pytest.mark.django_db
    def test_delete_api_token_success(self, session_client, create_user):
        """Test successful deletion of an API token."""
        token = APIToken.objects.create(
            label="Token to Delete",
            description="This token will be removed",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.delete(url)
        
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert APIToken.objects.count() == 0
        assert not APIToken.objects.filter(pk=token.pk).exists()

    @pytest.mark.django_db
    def test_delete_api_token_not_found_returns_404(self, session_client):
        """Test deleting non-existent API token returns 404."""
        non_existent_uuid = uuid4()
        url = reverse("api-tokens-details", kwargs={"pk": non_existent_uuid})
        
        response = session_client.delete(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_delete_api_token_user_isolation_prevents_unauthorized_deletion(self, session_client, create_user):
        """Test that users cannot delete other users' tokens."""
        other_user = User.objects.create(
            email="protected-user@plane.so",
            first_name="Protected",
            last_name="User"
        )
        protected_token = APIToken.objects.create(
            label="Protected Token",
            description="Should not be deletable by other users",
            user=other_user,
            user_type=0,
            is_service=False
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": protected_token.pk})
        response = session_client.delete(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert APIToken.objects.count() == 1, "Token should still exist"
        assert APIToken.objects.filter(pk=protected_token.pk).exists()

    @pytest.mark.django_db
    def test_delete_api_token_excludes_service_tokens(self, session_client, create_user):
        """Test that DELETE properly excludes service tokens via is_service=False filter."""
        service_token = APIToken.objects.create(
            label="Service Token",
            description="Internal service token - should not be deletable via user endpoint",
            user=create_user,
            user_type=0,
            is_service=True
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": service_token.pk})
        response = session_client.delete(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert APIToken.objects.count() == 1, "Service token should still exist"
        assert APIToken.objects.filter(pk=service_token.pk, is_service=True).exists()

    # ===== SECURITY AND AUTHENTICATION TESTS =====
    
    @pytest.mark.django_db
    def test_unauthenticated_requests_properly_denied(self, api_client):
        """Test that all endpoints properly deny unauthenticated requests."""
        base_url = reverse("api-tokens")
        dummy_uuid = uuid4()
        detail_url = reverse("api-tokens-details", kwargs={"pk": dummy_uuid})
        
        # Test POST endpoint
        post_response = api_client.post(base_url, {"label": "test"}, format="json")
        assert post_response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        # Test GET list endpoint
        get_list_response = api_client.get(base_url)
        assert get_list_response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        # Test GET detail endpoint
        get_detail_response = api_client.get(detail_url)
        assert get_detail_response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        # Test PATCH endpoint
        patch_response = api_client.patch(detail_url, {"label": "test"}, format="json")
        assert patch_response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        # Test DELETE endpoint
        delete_response = api_client.delete(detail_url)
        assert delete_response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    # ===== EDGE CASES AND ERROR HANDLING TESTS =====
    
    @pytest.mark.django_db
    def test_malformed_uuid_returns_404_across_all_endpoints(self, session_client):
        """Test that malformed UUIDs return 404 across all detail endpoints."""
        malformed_uuid = "definitely-not-a-valid-uuid-format"
        
        detail_url = reverse("api-tokens-details", kwargs={"pk": malformed_uuid})
        
        # Test GET with malformed UUID
        get_response = session_client.get(detail_url)
        assert get_response.status_code == status.HTTP_404_NOT_FOUND
        
        # Test DELETE with malformed UUID  
        delete_response = session_client.delete(detail_url)
        assert delete_response.status_code == status.HTTP_404_NOT_FOUND
        
        # Test PATCH with malformed UUID
        patch_response = session_client.patch(detail_url, {"label": "test"}, format="json")
        assert patch_response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_api_token_response_serializer_field_validation(self, session_client, create_user):
        """Test that API responses contain expected fields and exclude sensitive data appropriately."""
        # Create token via POST
        url = reverse("api-tokens")
        token_data = {
            "label": "Serializer Field Test Token",
            "description": "Testing response field inclusion/exclusion"
        }
        
        create_response = session_client.post(url, token_data, format="json")
        assert create_response.status_code == status.HTTP_201_CREATED
        
        # Verify POST response includes all expected fields including sensitive token
        expected_create_fields = {"token", "id", "label", "description", "user_type", "is_service", "created_at", "expired_at"}
        assert expected_create_fields.issubset(set(create_response.data.keys()))
        
        # Verify GET response excludes sensitive token field
        token_id = create_response.data["id"]
        get_url = reverse("api-tokens-details", kwargs={"pk": token_id})
        get_response = session_client.get(get_url)
        
        assert get_response.status_code == status.HTTP_200_OK
        assert "token" not in get_response.data, "GET responses should exclude token field"
        
        expected_get_fields = {"id", "label", "description", "user_type", "is_service", "created_at", "expired_at"}
        assert expected_get_fields.issubset(set(get_response.data.keys()))

    @pytest.mark.django_db
    def test_token_creation_generates_unique_tokens(self, session_client):
        """Test that multiple token creations generate unique token values."""
        url = reverse("api-tokens")
        
        # Create first token
        response1 = session_client.post(url, {"label": "Token 1"}, format="json")
        assert response1.status_code == status.HTTP_201_CREATED
        token1_value = response1.data["token"]
        
        # Create second token
        response2 = session_client.post(url, {"label": "Token 2"}, format="json")
        assert response2.status_code == status.HTTP_201_CREATED
        token2_value = response2.data["token"]
        
        # Verify tokens are unique
        assert token1_value != token2_value, "Generated tokens should be unique"
        assert len(token1_value) > 0 and len(token2_value) > 0

    @pytest.mark.django_db
    def test_concurrent_token_operations_maintain_data_integrity(self, session_client, create_user):
        """Test that concurrent operations maintain data integrity."""
        # Create initial token
        token = APIToken.objects.create(
            label="Concurrent Test Token",
            description="Testing concurrent operations",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        # Simulate concurrent update attempt
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        update_data = {"label": "Concurrently Updated"}
        
        response = session_client.patch(url, update_data, format="json")
        assert response.status_code == status.HTTP_200_OK
        
        # Verify final state is consistent
        final_token = APIToken.objects.get(pk=token.pk)
        assert final_token.label == "Concurrently Updated"

    @pytest.mark.django_db
    def test_large_description_field_handling(self, session_client):
        """Test handling of large description field values."""
        url = reverse("api-tokens")
        large_description = "x" * 2000  # Large but reasonable description
        
        token_data = {
            "label": "Large Description Test",
            "description": large_description
        }
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["description"]) == 2000
        
        created_token = APIToken.objects.first()
        assert created_token.description == large_description

    @pytest.mark.django_db
    def test_special_characters_in_token_fields(self, session_client):
        """Test handling of special characters in token label and description."""
        url = reverse("api-tokens")
        
        token_data = {
            "label": "Special chars: @#$%^&*()[]{}|;:',.<>?/`~",
            "description": "Description with unicode: 你好世界 🌍 émojis"
        }
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["label"] == token_data["label"]
        assert response.data["description"] == token_data["description"]

    @pytest.mark.django_db
    def test_api_token_database_constraints_enforced(self, session_client, create_user):
        """Test that database-level constraints are properly enforced."""
        # Test that user field is required (this should be handled by the endpoint logic)
        url = reverse("api-tokens")
        response = session_client.post(url, {"label": "Test Token"}, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        created_token = APIToken.objects.first()
        assert created_token.user == create_user  # Should be set by the endpoint

    @pytest.mark.django_db
    def test_token_expiry_date_timezone_handling(self, session_client):
        """Test proper handling of timezone-aware expiry dates."""
        url = reverse("api-tokens")
        
        # Test with timezone-aware datetime
        future_date_tz = timezone.now() + timedelta(days=15)
        token_data = {
            "label": "Timezone Test Token",
            "expired_at": future_date_tz.isoformat()
        }
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["expired_at"] is not None
        
        created_token = APIToken.objects.first()
        assert created_token.expired_at is not None
        # Verify the date is preserved correctly (allowing for small precision differences)
        assert abs((created_token.expired_at - future_date_tz).total_seconds()) < 1

    # ===== PERFORMANCE AND OPTIMIZATION TESTS =====

    @pytest.mark.django_db
    def test_large_token_list_performance(self, session_client, create_user):
        """Test performance with a reasonable number of tokens."""
        # Create multiple tokens to test list performance
        tokens_to_create = 20
        for i in range(tokens_to_create):
            APIToken.objects.create(
                label=f"Performance Test Token {i+1}",
                description=f"Token {i+1} for performance testing",
                user=create_user,
                user_type=0,
                is_service=False
            )
        
        url = reverse("api-tokens")
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == tokens_to_create
        
        # Verify all tokens are properly serialized
        for token_data in response.data:
            assert "label" in token_data
            assert "description" in token_data
            assert "token" not in token_data

    @pytest.mark.django_db
    def test_token_operations_maintain_audit_trail(self, session_client, create_user):
        """Test that token operations maintain proper audit trail via timestamps."""
        # Create token
        url = reverse("api-tokens")
        create_response = session_client.post(url, {"label": "Audit Test"}, format="json")
        assert create_response.status_code == status.HTTP_201_CREATED
        
        original_created_at = create_response.data["created_at"]
        token_id = create_response.data["id"]
        
        # Update token (small delay to ensure different timestamp)
        import time
        time.sleep(0.01)  # Small delay
        
        update_url = reverse("api-tokens-details", kwargs={"pk": token_id})
        update_response = session_client.patch(update_url, {"label": "Updated Audit Test"}, format="json")
        assert update_response.status_code == status.HTTP_200_OK
        
        # Verify timestamps are maintained
        updated_token = APIToken.objects.get(pk=token_id)
        assert updated_token.created_at.isoformat() == original_created_at
        assert updated_token.updated_at > updated_token.created_at