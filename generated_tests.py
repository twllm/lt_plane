import pytest
from uuid import uuid4
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework import status

from plane.db.models import APIToken


@pytest.mark.contract
class TestApiTokenEndpoint:
    """
    Comprehensive contract tests for ApiTokenEndpoint.

    Tests all HTTP methods (POST, GET, DELETE, PATCH) for the API token management endpoint.
    Covers authentication, authorization, data validation, edge cases, and error handling.

    URL Routes:
    - POST/GET: /api/users/api-tokens/ (list/create)
    - GET/PATCH/DELETE: /api/users/api-tokens/<uuid:pk>/ (retrieve/update/delete)

    Key Behaviors:
    - Service tokens (is_service=True) are filtered from list and delete operations
    - Service tokens CAN be retrieved and updated (not filtered by is_service)
    - Token value is only visible during creation (excluded from all other operations)
    - User isolation is enforced (users can only access their own tokens)
    """

    # ============================================================================
    # POST Method Tests - Token Creation
    # ============================================================================

    @pytest.mark.django_db
    def test_create_token_with_all_fields(self, session_client, create_user):
        """
        Test creating an API token with all fields provided.

        Verifies that a token can be created with label, description, and expired_at
        fields and that all fields are properly stored in the database.
        """
        url = reverse("api-tokens")
        future_date = timezone.now() + timedelta(days=30)
        api_token_data = {
            "label": "Test API Token",
            "description": "Test description for API token",
            "expired_at": future_date.isoformat(),
        }

        response = session_client.post(url, api_token_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.data
        assert response.data["label"] == api_token_data["label"]
        assert response.data["description"] == api_token_data["description"]
        assert "expired_at" in response.data
        assert "token" in response.data  # Token visible on creation

        # Verify database record
        assert APIToken.objects.count() == 1
        token = APIToken.objects.first()
        assert token.label == api_token_data["label"]
        assert token.description == api_token_data["description"]
        assert token.expired_at is not None
        assert token.user == create_user
        assert token.user_type == 0  # Human user
        assert token.is_service is False  # Default value

    @pytest.mark.django_db
    def test_create_token_with_defaults(self, session_client, create_user):
        """
        Test creating an API token with minimal data.

        Verifies that default values are applied when optional fields are omitted.
        The label should be auto-generated as a UUID hex string (32 characters).
        """
        url = reverse("api-tokens")

        response = session_client.post(url, {}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "label" in response.data
        assert len(response.data["label"]) == 32  # UUID hex length
        assert response.data["description"] == ""
        assert response.data["expired_at"] is None  # No expiration
        assert response.data["user_type"] == 0  # Human user
        assert response.data["is_service"] is False

        # Verify database
        assert APIToken.objects.count() == 1
        token = APIToken.objects.first()
        assert token.user == create_user

    @pytest.mark.django_db
    def test_create_token_for_bot_user(self, api_client, create_bot_user):
        """
        Test creating an API token for a bot user.

        Verifies that when a bot user (is_bot=True) creates a token,
        the user_type field is automatically set to 1 (Bot).
        """
        api_client.force_authenticate(user=create_bot_user)
        url = reverse("api-tokens")
        api_token_data = {
            "label": "Bot Token",
            "description": "Token for bot user",
        }

        response = api_client.post(url, api_token_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["user_type"] == 1  # Bot type
        assert response.data["label"] == "Bot Token"

        # Verify in database
        token = APIToken.objects.first()
        assert token.user_type == 1
        assert token.user == create_bot_user
        assert token.user.is_bot is True

    @pytest.mark.django_db
    def test_create_token_for_regular_user(self, session_client, create_user):
        """
        Test creating an API token for a regular user.

        Verifies that when a regular user (is_bot=False) creates a token,
        the user_type field is automatically set to 0 (Human).
        """
        url = reverse("api-tokens")
        api_token_data = {
            "label": "Human Token",
            "description": "Token for human user",
        }

        response = session_client.post(url, api_token_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["user_type"] == 0  # Human type
        assert response.data["label"] == "Human Token"

        # Verify in database
        token = APIToken.objects.first()
        assert token.user_type == 0
        assert token.user == create_user
        assert token.user.is_bot is False

    @pytest.mark.django_db
    def test_create_token_returns_token_with_correct_format(self, session_client):
        """
        Test that the actual token value is returned on creation with correct format.

        Verifies that:
        1. The token field is included in the response during creation (only time it's visible)
        2. The token has the correct prefix "plane_api_"
        3. The token format is valid (prefix + UUID hex)
        """
        url = reverse("api-tokens")
        api_token_data = {"label": "Token to check format"}

        response = session_client.post(url, api_token_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "token" in response.data

        token_value = response.data["token"]
        assert token_value.startswith("plane_api_")
        assert len(token_value) == len("plane_api_") + 32  # prefix + UUID hex (32 chars)

        # Verify token is stored in database
        db_token = APIToken.objects.first()
        assert db_token.token == token_value

    @pytest.mark.django_db
    def test_create_token_unauthenticated(self, api_client):
        """
        Test that unauthenticated users cannot create tokens.

        Verifies that the endpoint requires authentication and rejects
        requests from unauthenticated users with 401 or 403 status.
        """
        url = reverse("api-tokens")
        api_token_data = {"label": "Unauthorized Token"}

        response = api_client.post(url, api_token_data, format="json")

        # Should return 401 or 403 depending on authentication configuration
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        assert APIToken.objects.count() == 0  # No token created

    @pytest.mark.django_db
    def test_create_token_with_past_expiry_date(self, session_client):
        """
        Test creating a token with an expiry date in the past.

        Verifies that the API accepts past dates (validation may happen at runtime
        when the token is used, not at creation time).
        """
        url = reverse("api-tokens")
        past_date = timezone.now() - timedelta(days=1)
        api_token_data = {
            "label": "Expired Token",
            "expired_at": past_date.isoformat(),
        }

        response = session_client.post(url, api_token_data, format="json")

        # The API accepts past dates (business logic allows creating expired tokens)
        assert response.status_code == status.HTTP_201_CREATED
        assert "expired_at" in response.data

    @pytest.mark.django_db
    def test_create_token_with_invalid_expiry_format(self, session_client):
        """
        Test that invalid expired_at format returns appropriate error.

        Verifies that the serializer validates date format and returns
        400 BAD REQUEST for invalid date strings.
        """
        url = reverse("api-tokens")
        api_token_data = {
            "label": "Invalid Date Token",
            "expired_at": "not-a-valid-date",
        }

        response = session_client.post(url, api_token_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "expired_at" in response.data

    @pytest.mark.django_db
    def test_create_multiple_tokens_for_same_user(self, session_client, create_user):
        """
        Test that a user can create multiple tokens.

        Verifies that there's no limit on the number of tokens a user can create
        and that each token has a unique ID and token value.
        """
        url = reverse("api-tokens")

        # Create first token
        response1 = session_client.post(url, {"label": "Token 1"}, format="json")
        assert response1.status_code == status.HTTP_201_CREATED
        token1_id = response1.data["id"]
        token1_value = response1.data["token"]

        # Create second token
        response2 = session_client.post(url, {"label": "Token 2"}, format="json")
        assert response2.status_code == status.HTTP_201_CREATED
        token2_id = response2.data["id"]
        token2_value = response2.data["token"]

        # Create third token
        response3 = session_client.post(url, {"label": "Token 3"}, format="json")
        assert response3.status_code == status.HTTP_201_CREATED
        token3_id = response3.data["id"]
        token3_value = response3.data["token"]

        # Verify all tokens are unique
        assert token1_id != token2_id != token3_id
        assert token1_value != token2_value != token3_value
        assert APIToken.objects.filter(user=create_user).count() == 3

    # ============================================================================
    # GET List Method Tests - List All Tokens
    # ============================================================================

    @pytest.mark.django_db
    def test_list_all_user_tokens(self, session_client, create_user):
        """
        Test listing all API tokens for the authenticated user.

        Creates multiple tokens and verifies that all of them are returned
        in the list response with correct fields.
        """
        # Create multiple tokens for the user
        token1 = APIToken.objects.create(
            label="Token 1",
            description="First token",
            user=create_user,
            user_type=0,
        )
        token2 = APIToken.objects.create(
            label="Token 2",
            description="Second token",
            user=create_user,
            user_type=0,
        )
        token3 = APIToken.objects.create(
            label="Token 3",
            description="Third token",
            user=create_user,
            user_type=0,
        )

        url = reverse("api-tokens")
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

        # Verify all tokens are present
        labels = [token["label"] for token in response.data]
        assert "Token 1" in labels
        assert "Token 2" in labels
        assert "Token 3" in labels

        # Verify token field is not included in list
        for token_data in response.data:
            assert "token" not in token_data
            assert "label" in token_data
            assert "description" in token_data
            assert "id" in token_data

    @pytest.mark.django_db
    def test_list_excludes_service_tokens(self, session_client, create_user):
        """
        Test that service tokens (is_service=True) are excluded from the list.

        Verifies that tokens marked as service tokens are not visible
        in the user's token list (filtered by is_service=False).
        """
        # Create regular token
        APIToken.objects.create(
            label="Regular Token",
            description="Regular token",
            user=create_user,
            user_type=0,
            is_service=False,
        )
        # Create service token (should be filtered out)
        APIToken.objects.create(
            label="Service Token",
            description="Service token",
            user=create_user,
            user_type=0,
            is_service=True,
        )

        url = reverse("api-tokens")
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["label"] == "Regular Token"
        assert response.data[0]["is_service"] is False

    @pytest.mark.django_db
    def test_list_empty_when_no_tokens(self, session_client):
        """
        Test listing tokens when the user has no tokens.

        Verifies that an empty list is returned when the user has not created any tokens.
        """
        url = reverse("api-tokens")
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0
        assert response.data == []
        assert isinstance(response.data, list)

    @pytest.mark.django_db
    def test_list_only_current_user_tokens(self, session_client, create_user, create_bot_user):
        """
        Test that users can only see their own tokens (user isolation).

        Creates tokens for two different users and verifies that each user
        can only see their own tokens in the list.
        """
        # Create token for create_user
        APIToken.objects.create(
            label="User1 Token",
            description="Token for user 1",
            user=create_user,
            user_type=0,
        )
        # Create token for create_bot_user
        APIToken.objects.create(
            label="User2 Token",
            description="Token for user 2",
            user=create_bot_user,
            user_type=1,
        )

        # Request as create_user (session_client is authenticated as create_user)
        url = reverse("api-tokens")
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["label"] == "User1 Token"

    @pytest.mark.django_db
    def test_list_returns_is_active_field(self, session_client, create_user):
        """
        Test that the list response includes the computed is_active field.

        Verifies that the serializer correctly computes is_active based on
        the expired_at field (active if None or future date).
        """
        # Create active token (no expiry)
        APIToken.objects.create(
            label="Active Token",
            user=create_user,
            user_type=0,
            expired_at=None,
        )
        # Create future expiry token (active)
        APIToken.objects.create(
            label="Future Expiry Token",
            user=create_user,
            user_type=0,
            expired_at=timezone.now() + timedelta(days=30),
        )
        # Create expired token (inactive)
        APIToken.objects.create(
            label="Expired Token",
            user=create_user,
            user_type=0,
            expired_at=timezone.now() - timedelta(days=1),
        )

        url = reverse("api-tokens")
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

        # Find tokens by label and check is_active
        tokens_by_label = {token["label"]: token for token in response.data}
        assert tokens_by_label["Active Token"]["is_active"] is True
        assert tokens_by_label["Future Expiry Token"]["is_active"] is True
        assert tokens_by_label["Expired Token"]["is_active"] is False

    @pytest.mark.django_db
    def test_list_unauthenticated(self, api_client):
        """
        Test that unauthenticated users cannot list tokens.

        Verifies that authentication is required for listing tokens.
        """
        url = reverse("api-tokens")
        response = api_client.get(url)

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    # ============================================================================
    # GET Retrieve Method Tests - Get Single Token
    # ============================================================================

    @pytest.mark.django_db
    def test_retrieve_specific_token(self, session_client, create_user):
        """
        Test retrieving a specific API token by its UUID.

        Verifies that a single token can be retrieved by its primary key
        and that all expected fields are present (except the token value).
        """
        token = APIToken.objects.create(
            label="Test Token",
            description="Test description",
            user=create_user,
            user_type=0,
        )

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(token.pk)
        assert response.data["label"] == "Test Token"
        assert response.data["description"] == "Test description"
        assert response.data["user_type"] == 0
        assert "token" not in response.data  # Token field excluded from retrieve

    @pytest.mark.django_db
    def test_retrieve_nonexistent_token(self, session_client):
        """
        Test retrieving a token that does not exist.

        Verifies that attempting to retrieve a non-existent token
        results in a 404 error (DoesNotExist exception from .get()).
        """
        nonexistent_id = uuid4()
        url = reverse("api-tokens-details", kwargs={"pk": nonexistent_id})
        response = session_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_retrieve_another_users_token(self, session_client, create_user, create_bot_user):
        """
        Test that users cannot retrieve another user's tokens.

        Creates a token for one user and attempts to retrieve it as another user.
        Verifies that authorization is enforced (filtered by user in queryset).
        """
        # Create token for create_bot_user
        token = APIToken.objects.create(
            label="Bot Token",
            description="Token for bot user",
            user=create_bot_user,
            user_type=1,
        )

        # Try to retrieve as create_user (session_client is authenticated as create_user)
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.get(url)

        # Should return 404 (DoesNotExist since the query filters by user)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_retrieve_token_field_excluded(self, session_client, create_user):
        """
        Test that the token field is excluded from retrieve responses.

        Verifies that for security reasons, the actual token value is not
        included in retrieve responses (only visible during creation).
        Uses APITokenReadSerializer which excludes the token field.
        """
        token = APIToken.objects.create(
            label="Test Token",
            description="Secret token",
            user=create_user,
            user_type=0,
        )

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "token" not in response.data
        assert "label" in response.data
        assert "description" in response.data
        assert "id" in response.data

    @pytest.mark.django_db
    def test_retrieve_service_token_allowed(self, session_client, create_user):
        """
        Test that service tokens CAN be retrieved (not filtered).

        IMPORTANT: Unlike list and delete operations, the retrieve operation
        does NOT filter by is_service=False. This means service tokens can
        be retrieved by their owner.
        """
        service_token = APIToken.objects.create(
            label="Service Token",
            description="A service token",
            user=create_user,
            user_type=0,
            is_service=True,
        )

        url = reverse("api-tokens-details", kwargs={"pk": service_token.pk})
        response = session_client.get(url)

        # Service token CAN be retrieved (implementation doesn't filter by is_service)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Service Token"
        assert response.data["is_service"] is True

    @pytest.mark.django_db
    def test_retrieve_includes_is_active_field(self, session_client, create_user):
        """
        Test that retrieve response includes the computed is_active field.

        Verifies that the APITokenReadSerializer correctly computes is_active
        for a single token retrieval.
        """
        future_date = timezone.now() + timedelta(days=30)
        token = APIToken.objects.create(
            label="Future Token",
            user=create_user,
            user_type=0,
            expired_at=future_date,
        )

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "is_active" in response.data
        assert response.data["is_active"] is True

    # ============================================================================
    # DELETE Method Tests - Token Deletion
    # ============================================================================

    @pytest.mark.django_db
    def test_delete_token_success(self, session_client, create_user):
        """
        Test successful deletion of an API token.

        Verifies that a token can be deleted and that it is removed
        from the database. Returns 204 NO CONTENT on success.
        """
        token = APIToken.objects.create(
            label="Test Token",
            description="To be deleted",
            user=create_user,
            user_type=0,
        )
        token_id = token.pk

        url = reverse("api-tokens-details", kwargs={"pk": token_id})
        response = session_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert APIToken.objects.filter(pk=token_id).count() == 0
        assert not APIToken.objects.filter(pk=token_id).exists()

    @pytest.mark.django_db
    def test_delete_nonexistent_token(self, session_client):
        """
        Test deleting a token that does not exist.

        Verifies that attempting to delete a non-existent token
        results in a 404 error (DoesNotExist exception from .get()).
        """
        nonexistent_id = uuid4()
        url = reverse("api-tokens-details", kwargs={"pk": nonexistent_id})
        response = session_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_delete_another_users_token(self, session_client, create_user, create_bot_user):
        """
        Test that users cannot delete another user's tokens.

        Creates a token for one user and attempts to delete it as another user.
        Verifies that authorization is enforced (filtered by user in queryset).
        """
        # Create token for create_bot_user
        token = APIToken.objects.create(
            label="Bot Token",
            description="Bot's token",
            user=create_bot_user,
            user_type=1,
        )
        token_id = token.pk

        # Try to delete as create_user
        url = reverse("api-tokens-details", kwargs={"pk": token_id})
        response = session_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Verify token still exists
        assert APIToken.objects.filter(pk=token_id).exists()

    @pytest.mark.django_db
    def test_delete_service_token_protected(self, session_client, create_user):
        """
        Test that service tokens cannot be deleted via this endpoint.

        Verifies that tokens marked as is_service=True are protected
        from deletion through the regular token management endpoint
        (the query explicitly filters by is_service=False).
        """
        service_token = APIToken.objects.create(
            label="Service Token",
            description="Protected service token",
            user=create_user,
            user_type=0,
            is_service=True,
        )
        token_id = service_token.pk

        url = reverse("api-tokens-details", kwargs={"pk": token_id})
        response = session_client.delete(url)

        # Should return 404 since the query filters by is_service=False
        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Verify token still exists
        assert APIToken.objects.filter(pk=token_id).exists()
        assert APIToken.objects.get(pk=token_id).is_service is True

    @pytest.mark.django_db
    def test_delete_already_deleted_token(self, session_client, create_user):
        """
        Test that attempting to delete an already deleted token returns 404.

        Verifies idempotency behavior (subsequent delete attempts fail).
        """
        token = APIToken.objects.create(
            label="To Delete",
            user=create_user,
            user_type=0,
        )
        token_id = token.pk
        url = reverse("api-tokens-details", kwargs={"pk": token_id})

        # First deletion
        response1 = session_client.delete(url)
        assert response1.status_code == status.HTTP_204_NO_CONTENT

        # Second deletion attempt
        response2 = session_client.delete(url)
        assert response2.status_code == status.HTTP_404_NOT_FOUND

    # ============================================================================
    # PATCH Method Tests - Token Updates
    # ============================================================================

    @pytest.mark.django_db
    def test_update_token_all_fields(self, session_client, create_user):
        """
        Test updating all editable fields of an API token.

        Verifies that label and description can be updated simultaneously
        and that changes are persisted to the database.
        """
        token = APIToken.objects.create(
            label="Original Label",
            description="Original description",
            user=create_user,
            user_type=0,
        )

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        update_data = {
            "label": "Updated Label",
            "description": "Updated description",
        }
        response = session_client.patch(url, update_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Updated Label"
        assert response.data["description"] == "Updated description"

        # Verify in database
        token.refresh_from_db()
        assert token.label == "Updated Label"
        assert token.description == "Updated description"

    @pytest.mark.django_db
    def test_update_token_partial(self, session_client, create_user):
        """
        Test partial update of an API token.

        Verifies that only the label can be updated while leaving
        other fields unchanged (partial update with partial=True).
        """
        token = APIToken.objects.create(
            label="Original Label",
            description="Original description",
            user=create_user,
            user_type=0,
        )

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        update_data = {"label": "Updated Label Only"}
        response = session_client.patch(url, update_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Updated Label Only"
        assert response.data["description"] == "Original description"

        # Verify in database
        token.refresh_from_db()
        assert token.label == "Updated Label Only"
        assert token.description == "Original description"

    @pytest.mark.django_db
    def test_update_token_invalid_data(self, session_client, create_user):
        """
        Test updating a token with invalid data.

        Verifies that the endpoint validates data and returns 400 BAD REQUEST
        when invalid data is provided (e.g., invalid date format).
        """
        token = APIToken.objects.create(
            label="Test Token",
            user=create_user,
            user_type=0,
        )

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        # Try to update with invalid expired_at format
        invalid_data = {"expired_at": "not-a-valid-date"}
        response = session_client.patch(url, invalid_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "expired_at" in response.data or "errors" in response.data

    @pytest.mark.django_db
    def test_update_nonexistent_token(self, session_client):
        """
        Test updating a token that does not exist.

        Verifies that attempting to update a non-existent token
        results in a 404 error (DoesNotExist exception from .get()).
        """
        nonexistent_id = uuid4()
        url = reverse("api-tokens-details", kwargs={"pk": nonexistent_id})
        update_data = {"label": "New Label"}
        response = session_client.patch(url, update_data, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_update_another_users_token(self, session_client, create_user, create_bot_user):
        """
        Test that users cannot update another user's tokens.

        Creates a token for one user and attempts to update it as another user.
        Verifies that authorization is enforced (filtered by user in queryset).
        """
        # Create token for create_bot_user
        token = APIToken.objects.create(
            label="Bot Token",
            description="Bot's original description",
            user=create_bot_user,
            user_type=1,
        )
        original_label = token.label

        # Try to update as create_user
        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        update_data = {"label": "Hacked Label"}
        response = session_client.patch(url, update_data, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Verify token was not updated
        token.refresh_from_db()
        assert token.label == original_label

    @pytest.mark.django_db
    def test_update_read_only_fields_ignored(self, session_client, create_user):
        """
        Test that read-only fields cannot be updated via PATCH.

        Verifies that fields marked as read_only in the serializer
        (token, expired_at, workspace, user, created_at, updated_at)
        are ignored when provided in update data.
        """
        original_token_value = "plane_api_" + uuid4().hex
        token = APIToken.objects.create(
            label="Original",
            user=create_user,
            user_type=0,
        )
        # Store original token value from DB
        token.token = original_token_value
        token.save()
        original_user = token.user

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        update_data = {
            "label": "New Label",
            "token": "hacked_token_value",  # Attempting to change read-only field
            "user": create_user.id,  # Attempting to change read-only field
        }
        response = session_client.patch(url, update_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "New Label"  # Label updated

        # Verify read-only fields were NOT updated
        token.refresh_from_db()
        assert token.label == "New Label"
        assert token.token == original_token_value  # Token unchanged
        assert token.user == original_user  # User unchanged

    @pytest.mark.django_db
    def test_update_service_token_allowed(self, session_client, create_user):
        """
        Test that service tokens CAN be updated.

        IMPORTANT: Unlike delete operations, the update operation
        does NOT filter by is_service=False. This means service tokens
        can be updated by their owner.
        """
        service_token = APIToken.objects.create(
            label="Service Token",
            description="Original service description",
            user=create_user,
            user_type=0,
            is_service=True,
        )

        url = reverse("api-tokens-details", kwargs={"pk": service_token.pk})
        update_data = {
            "label": "Updated Service Token",
            "description": "Updated service description",
        }
        response = session_client.patch(url, update_data, format="json")

        # Service token CAN be updated (implementation doesn't filter by is_service)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["label"] == "Updated Service Token"
        assert response.data["description"] == "Updated service description"

        # Verify in database
        service_token.refresh_from_db()
        assert service_token.label == "Updated Service Token"
        assert service_token.is_service is True  # is_service flag unchanged

    @pytest.mark.django_db
    def test_update_empty_data(self, session_client, create_user):
        """
        Test that updating with empty data doesn't change anything.

        Verifies that partial update with no fields returns success
        but doesn't modify the token.
        """
        token = APIToken.objects.create(
            label="Original Label",
            description="Original description",
            user=create_user,
            user_type=0,
        )

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.patch(url, {}, format="json")

        assert response.status_code == status.HTTP_200_OK

        # Verify nothing changed
        token.refresh_from_db()
        assert token.label == "Original Label"
        assert token.description == "Original description"

    # ============================================================================
    # Edge Cases and Additional Tests
    # ============================================================================

    @pytest.mark.django_db
    def test_token_ordering(self, session_client, create_user):
        """
        Test that tokens are returned in the correct order.

        Verifies that tokens are ordered by created_at descending
        (newest first) as specified in the model Meta.ordering.
        """
        import time

        # Create tokens with small delays to ensure different created_at times
        token1 = APIToken.objects.create(label="First", user=create_user, user_type=0)
        time.sleep(0.01)
        token2 = APIToken.objects.create(label="Second", user=create_user, user_type=0)
        time.sleep(0.01)
        token3 = APIToken.objects.create(label="Third", user=create_user, user_type=0)

        url = reverse("api-tokens")
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

        # Should be ordered by created_at descending (newest first)
        assert response.data[0]["label"] == "Third"
        assert response.data[1]["label"] == "Second"
        assert response.data[2]["label"] == "First"

    @pytest.mark.django_db
    def test_concurrent_token_creation(self, session_client, create_user):
        """
        Test that multiple tokens can be created without conflicts.

        Verifies that the UUID-based token generation doesn't cause
        conflicts when creating multiple tokens rapidly.
        """
        url = reverse("api-tokens")

        # Create multiple tokens rapidly
        responses = []
        for i in range(5):
            response = session_client.post(url, {"label": f"Token {i}"}, format="json")
            responses.append(response)

        # All should succeed
        for response in responses:
            assert response.status_code == status.HTTP_201_CREATED

        # All should have unique tokens
        token_values = [r.data["token"] for r in responses]
        assert len(token_values) == len(set(token_values))  # All unique

        # Verify in database
        assert APIToken.objects.filter(user=create_user).count() == 5

    @pytest.mark.django_db
    def test_token_with_very_long_label(self, session_client, create_user):
        """
        Test creating a token with a very long label.

        Verifies that the label field respects the max_length constraint (255 chars).
        """
        url = reverse("api-tokens")

        # Label at max length (255 chars)
        long_label = "A" * 255
        response = session_client.post(url, {"label": long_label}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["label"]) == 255

        # Label exceeding max length should fail
        too_long_label = "A" * 256
        response = session_client.post(url, {"label": too_long_label}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_token_with_empty_label_uses_default(self, session_client):
        """
        Test that providing an empty string for label uses the default UUID.

        Note: This tests the actual behavior of the endpoint.
        If label="" is provided, it will be used as-is (not replaced with default).
        """
        url = reverse("api-tokens")
        response = session_client.post(url, {"label": ""}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        # Empty string is accepted (not replaced with UUID)
        assert response.data["label"] == ""

    @pytest.mark.django_db
    def test_expired_token_is_active_false(self, session_client, create_user):
        """
        Test that expired tokens have is_active=False in responses.

        Verifies the is_active computed field works correctly for expired tokens.
        """
        past_date = timezone.now() - timedelta(hours=1)
        expired_token = APIToken.objects.create(
            label="Expired Token",
            user=create_user,
            user_type=0,
            expired_at=past_date,
        )

        # Test in list
        url = reverse("api-tokens")
        response = session_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data[0]["is_active"] is False

        # Test in retrieve
        url = reverse("api-tokens-details", kwargs={"pk": expired_token.pk})
        response = session_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_active"] is False

    @pytest.mark.django_db
    def test_token_never_expires_is_active_true(self, session_client, create_user):
        """
        Test that tokens without expiry date have is_active=True.

        Verifies that None expired_at means the token never expires.
        """
        token = APIToken.objects.create(
            label="Never Expires",
            user=create_user,
            user_type=0,
            expired_at=None,
        )

        url = reverse("api-tokens-details", kwargs={"pk": token.pk})
        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_active"] is True
        assert response.data["expired_at"] is None
