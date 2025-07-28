import pytest
from django.urls import reverse
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from uuid import uuid4

from plane.db.models import APIToken, User


@pytest.mark.contract
class TestApiTokenEndpoint:
    """Comprehensive tests for ApiTokenEndpoint CRUD operations"""

    # POST method tests
    @pytest.mark.django_db
    def test_create_api_token_with_all_data(self, session_client):
        """Test creating an API token with complete data"""
        url = reverse("api-tokens")
        
        token_data = {
            "label": "Test API Token",
            "description": "Test description for API token",
            "expired_at": (timezone.now() + timedelta(days=30)).isoformat(),
        }
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["label"] == token_data["label"]
        assert response.data["description"] == token_data["description"]
        assert "token" in response.data  # Token should be visible during creation
        assert response.data["user_type"] == 0  # Regular user type
        assert response.data["is_service"] == False
        
        # Verify token was created in database
        assert APIToken.objects.count() == 1
        created_token = APIToken.objects.first()
        assert created_token.label == token_data["label"]
        assert created_token.description == token_data["description"]
        assert created_token.user_type == 0

    @pytest.mark.django_db
    def test_create_api_token_minimal_data(self, session_client):
        """Test creating an API token with minimal data (empty payload)"""
        url = reverse("api-tokens")
        
        response = session_client.post(url, {}, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["label"]) == 32  # uuid4().hex length
        assert response.data["description"] == ""
        assert "token" in response.data
        assert response.data["user_type"] == 0
        
        # Verify default label is uuid4 hex
        created_token = APIToken.objects.first()
        assert len(created_token.label) == 32

    @pytest.mark.django_db
    def test_create_api_token_with_bot_user(self, session_client, create_bot_user):
        """Test creating an API token with bot user sets user_type=1"""
        # Force authenticate with bot user
        session_client.force_authenticate(user=create_bot_user)
        
        url = reverse("api-tokens")
        token_data = {"label": "Bot Token", "description": "Token for bot user"}
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["user_type"] == 1  # Bot user type
        
        created_token = APIToken.objects.first()
        assert created_token.user_type == 1
        assert created_token.user == create_bot_user

    @pytest.mark.django_db
    def test_create_api_token_with_partial_data(self, session_client):
        """Test creating an API token with only label"""
        url = reverse("api-tokens")
        token_data = {"label": "Partial Token"}
        
        response = session_client.post(url, token_data, format="json")
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["label"] == "Partial Token"
        assert response.data["description"] == ""
        assert response.data["expired_at"] is None

    # GET method tests (list all tokens)
    @pytest.mark.django_db
    def test_get_all_api_tokens_empty(self, session_client):
        """Test getting all API tokens when none exist"""
        url = reverse("api-tokens")
        
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    @pytest.mark.django_db
    def test_get_all_api_tokens_multiple(self, session_client, create_user):
        """Test getting all API tokens when multiple exist"""
        # Create multiple tokens for the authenticated user
        APIToken.objects.create(
            label="Token 1",
            description="First token",
            user=create_user,
            user_type=0
        )
        APIToken.objects.create(
            label="Token 2", 
            description="Second token",
            user=create_user,
            user_type=0
        )
        
        url = reverse("api-tokens")
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        
        # Verify tokens don't include token field (only visible during creation)
        for token_data in response.data:
            assert "token" not in token_data
            assert "label" in token_data
            assert "description" in token_data

    @pytest.mark.django_db
    def test_get_all_api_tokens_excludes_service_tokens(self, session_client, create_user):
        """Test that GET excludes service tokens (is_service=True)"""
        # Create regular token
        APIToken.objects.create(
            label="Regular Token",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        # Create service token
        APIToken.objects.create(
            label="Service Token",
            user=create_user,
            user_type=0,
            is_service=True
        )
        
        url = reverse("api-tokens")
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1  # Only regular token returned
        assert response.data[0]["label"] == "Regular Token"

    @pytest.mark.django_db
    def test_get_all_api_tokens_user_isolation(self, session_client, create_user):
        """Test that users can only see their own tokens"""
        # Create token for authenticated user
        APIToken.objects.create(
            label="My Token",
            user=create_user,
            user_type=0
        )
        
        # Create another user and token
        other_user = User.objects.create(
            email="other@plane.so",
            first_name="Other",
            last_name="User"
        )
        APIToken.objects.create(
            label="Other Token",
            user=other_user,
            user_type=0
        )
        
        url = reverse("api-tokens")
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["label"] == "My Token"

    # GET method tests (specific token by pk)
    @pytest.mark.django_db
    def test_get_specific_api_token_success(self, session_client, create_user):
        """Test getting a specific API token by pk"""
        token = APIToken.objects.create(
            label="Specific Token",
            description="Token description",
            user=create_user,
            user_type=0
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Specific Token"
        assert response.data["description"] == "Token description"
        assert "token" not in response.data  # Token not visible in GET

    @pytest.mark.django_db
    def test_get_specific_api_token_not_found(self, session_client):
        """Test getting a non-existent API token returns 404"""
        non_existent_uuid = uuid4()
        url = reverse("api-tokens-details", kwargs={"pk": non_existent_uuid})
        
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_get_specific_api_token_user_isolation(self, session_client, create_user):
        """Test that users cannot access other users' tokens"""
        # Create another user and their token
        other_user = User.objects.create(
            email="other@plane.so",
            first_name="Other",
            last_name="User"
        )
        other_token = APIToken.objects.create(
            label="Other Token",
            user=other_user,
            user_type=0
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": other_token.pk})
        response = session_client.get(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # DELETE method tests
    @pytest.mark.django_db
    def test_delete_api_token_success(self, session_client, create_user):
        """Test successful deletion of an API token"""
        token = APIToken.objects.create(
            label="Token to Delete",
            user=create_user,
            user_type=0,
            is_service=False
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.delete(url)
        
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert APIToken.objects.count() == 0

    @pytest.mark.django_db
    def test_delete_api_token_not_found(self, session_client):
        """Test deleting a non-existent API token returns 404"""
        non_existent_uuid = uuid4()
        url = reverse("api-tokens-details", kwargs={"pk": non_existent_uuid})
        
        response = session_client.delete(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_delete_api_token_user_isolation(self, session_client, create_user):
        """Test that users cannot delete other users' tokens"""
        other_user = User.objects.create(
            email="other@plane.so",
            first_name="Other",
            last_name="User"
        )
        other_token = APIToken.objects.create(
            label="Other Token",
            user=other_user,
            user_type=0,
            is_service=False
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": other_token.pk})
        response = session_client.delete(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert APIToken.objects.count() == 1  # Token still exists

    @pytest.mark.django_db
    def test_delete_api_token_excludes_service_tokens(self, session_client, create_user):
        """Test that DELETE excludes service tokens (is_service=False filter)"""
        service_token = APIToken.objects.create(
            label="Service Token",
            user=create_user,
            user_type=0,
            is_service=True
        )
        
        url = reverse("api-tokens-details", kwargs={"pk": service_token.pk})
        response = session_client.delete(url)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert APIToken.objects.count() == 1  # Service token still exists

    # PATCH method tests
    @pytest.mark.django_db
    def test_patch_api_token_success(self, session_client, create_user):
        """Test successful update of an API token"""
        token = APIToken.objects.create(
            label="Original Label",
            description="Original Description",
            user=create_user,
            user_type=0
        )
        
        update_data = {
            "label": "Updated Label",
            "description": "Updated Description"
        }
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Updated Label"
        assert response.data["description"] == "Updated Description"
        
        # Verify database was updated
        updated_token = APIToken.objects.get(pk=token.pk)
        assert updated_token.label == "Updated Label"
        assert updated_token.description == "Updated Description"

    @pytest.mark.django_db
    def test_patch_api_token_partial_update(self, session_client, create_user):
        """Test partial update of an API token (only one field)"""
        token = APIToken.objects.create(
            label="Original Label",
            description="Original Description",
            user=create_user,
            user_type=0
        )
        
        update_data = {"label": "Partially Updated Label"}
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Partially Updated Label"
        assert response.data["description"] == "Original Description"  # Unchanged

    @pytest.mark.django_db
    def test_patch_api_token_invalid_data(self, session_client, create_user):
        """Test PATCH with invalid data returns 400"""
        token = APIToken.objects.create(
            label="Original Label",
            user=create_user,
            user_type=0
        )
        
        # Send invalid data (e.g., expired_at in wrong format)
        invalid_data = {"expired_at": "invalid-date-format"}
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, invalid_data, format="json")
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "expired_at" in response.data

    @pytest.mark.django_db
    def test_patch_api_token_not_found(self, session_client):
        """Test updating a non-existent API token returns 404"""
        non_existent_uuid = uuid4()
        update_data = {"label": "Updated Label"}
        
        url = reverse("api-tokens-details", kwargs={"pk": non_existent_uuid})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_patch_api_token_user_isolation(self, session_client, create_user):
        """Test that users cannot update other users' tokens"""
        other_user = User.objects.create(
            email="other@plane.so",
            first_name="Other", 
            last_name="User"
        )
        other_token = APIToken.objects.create(
            label="Other Token",
            user=other_user,
            user_type=0
        )
        
        update_data = {"label": "Hacked Label"}
        
        url = reverse("api-tokens-details", kwargs={"pk": other_token.pk})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        
        # Verify token was not modified
        unchanged_token = APIToken.objects.get(pk=other_token.pk)
        assert unchanged_token.label == "Other Token"

    @pytest.mark.django_db  
    def test_patch_api_token_with_expired_at(self, session_client, create_user):
        """Test updating expired_at field"""
        token = APIToken.objects.create(
            label="Token with Expiry",
            user=create_user,
            user_type=0
        )
        
        future_date = timezone.now() + timedelta(days=60)
        update_data = {"expired_at": future_date.isoformat()}
        
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, update_data, format="json")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["expired_at"] is not None
        
        # Verify database was updated
        updated_token = APIToken.objects.get(pk=token.pk)
        assert updated_token.expired_at is not None

    # Edge case and additional tests
    @pytest.mark.django_db
    def test_api_token_malformed_uuid(self, session_client):
        """Test API endpoints with malformed UUID return 404"""
        malformed_uuid = "not-a-valid-uuid"
        
        # Test GET with malformed UUID
        get_url = reverse("api-tokens-details", kwargs={"pk": malformed_uuid})
        get_response = session_client.get(get_url)
        assert get_response.status_code == status.HTTP_404_NOT_FOUND
        
        # Test DELETE with malformed UUID  
        delete_response = session_client.delete(get_url)
        assert delete_response.status_code == status.HTTP_404_NOT_FOUND
        
        # Test PATCH with malformed UUID
        patch_response = session_client.patch(get_url, {"label": "test"}, format="json")
        assert patch_response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_api_token_serializer_fields(self, session_client, create_user):
        """Test that response contains expected fields and excludes sensitive ones"""
        # Create token
        url = reverse("api-tokens")
        token_data = {
            "label": "Serializer Test Token",
            "description": "Testing serializer fields"
        }
        
        create_response = session_client.post(url, token_data, format="json")
        assert create_response.status_code == status.HTTP_201_CREATED
        
        # Check creation response includes token
        assert "token" in create_response.data
        assert "id" in create_response.data
        assert "label" in create_response.data
        assert "description" in create_response.data
        assert "user_type" in create_response.data
        assert "is_service" in create_response.data
        assert "created_at" in create_response.data
        
        # Get token and verify token field is excluded
        token_id = create_response.data["id"]
        get_url = reverse("api-tokens-details", kwargs={"pk": token_id})
        get_response = session_client.get(get_url)
        
        assert get_response.status_code == status.HTTP_200_OK
        assert "token" not in get_response.data  # Token should not be visible in GET
        assert "id" in get_response.data
        assert "label" in get_response.data

    @pytest.mark.django_db
    def test_unauthenticated_access_denied(self, api_client):
        """Test that unauthenticated requests are denied"""
        url = reverse("api-tokens")
        
        # Test POST
        response = api_client.post(url, {}, format="json")
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        # Test GET
        response = api_client.get(url)
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        # Test with pk
        dummy_uuid = uuid4()
        detail_url = reverse("api-tokens-details", kwargs={"pk": dummy_uuid})
        
        # Test GET with pk
        response = api_client.get(detail_url)
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        # Test DELETE
        response = api_client.delete(detail_url)
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        
        # Test PATCH
        response = api_client.patch(detail_url, {"label": "test"}, format="json")
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]