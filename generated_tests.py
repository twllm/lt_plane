"""
Refined State Endpoint Tests

This test suite provides comprehensive coverage for state endpoints including:
- State creation (list/create endpoint)
- State retrieval, update, and deletion (detail endpoint)
- Permission and authorization checks
- Edge cases and validation scenarios
- External ID handling and conflicts
- Default state management
- Triage state filtering
- Pagination and field filtering

The tests are organized for maintainability with shared fixtures and helper methods.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from unittest.mock import patch
from uuid import uuid4

from plane.db.models import State, Issue, Workspace, WorkspaceMember, Project, ProjectMember, User


class BaseStateTestSetup:
    """Base class providing common test setup and utilities"""

    @pytest.fixture
    def base_setup_data(self, create_user):
        """Create base test data with user, workspace, and project"""
        user = create_user
        workspace = Workspace.objects.create(
            name="Test Workspace",
            slug="test-workspace",
            owner=user
        )
        WorkspaceMember.objects.create(
            workspace=workspace,
            member=user,
            role=20
        )
        project = Project.objects.create(
            name="Test Project",
            identifier="TEST",
            workspace=workspace,
            created_by=user
        )
        ProjectMember.objects.create(
            project=project,
            member=user,
            role=20
        )
        return {
            "user": user,
            "workspace": workspace,
            "project": project,
        }

    @pytest.fixture
    def authenticated_client(self, api_client, base_setup_data):
        """Return authenticated API client"""
        api_client.force_authenticate(user=base_setup_data["user"])
        return api_client

    @pytest.fixture
    def unauthorized_user(self):
        """Create a user without project membership"""
        return User.objects.create(
            email="unauthorized@test.com",
            first_name="Unauthorized",
            last_name="User"
        )

    def create_state(self, setup_data, **kwargs):
        """Helper method to create a state with default values"""
        defaults = {
            "project": setup_data["project"],
            "workspace": setup_data["workspace"],
            "color": "#FF0000",
            "group": "backlog"
        }
        defaults.update(kwargs)
        return State.objects.create(**defaults)

    def get_list_url(self, setup_data):
        """Get URL for state list/create endpoint"""
        return f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"

    def get_detail_url(self, setup_data, state_id):
        """Get URL for state detail endpoint"""
        return f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/{state_id}/"


@pytest.mark.contract
class TestStateListCreateAPI(BaseStateTestSetup):
    """Test contract for StateListCreateAPIEndpoint"""

    @pytest.fixture
    def list_url(self, base_setup_data):
        """Return URL for state list/create endpoint"""
        return self.get_list_url(base_setup_data)

    # Creation Tests
    @pytest.mark.django_db
    def test_create_state_success(self, authenticated_client, list_url, base_setup_data):
        """Test successful state creation with all fields"""
        data = {
            "name": "New State",
            "description": "Test state description",
            "color": "#FF0000",
            "group": "started",
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        expected_fields = ["name", "description", "color", "group", "default", "is_triage"]
        for field in expected_fields:
            assert field in response.data
        
        assert response.data["name"] == "New State"
        assert response.data["description"] == "Test state description"
        assert response.data["color"] == "#FF0000"
        assert response.data["group"] == "started"
        assert response.data["default"] is False
        assert response.data["is_triage"] is False

        # Verify database creation
        state = State.objects.get(id=response.data["id"])
        assert state.project == base_setup_data["project"]
        assert state.workspace == base_setup_data["workspace"]

    @pytest.mark.django_db
    def test_create_state_minimal_data(self, authenticated_client, list_url):
        """Test state creation with only required fields"""
        data = {
            "name": "Minimal State",
            "color": "#00FF00",
            "group": "backlog",
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Minimal State"
        assert response.data["description"] == ""

    @pytest.mark.django_db
    def test_create_state_with_external_data(self, authenticated_client, list_url):
        """Test state creation with external ID and source"""
        data = {
            "name": "External State",
            "color": "#FFFF00",
            "group": "started",
            "external_id": "ext-123",
            "external_source": "jira",
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["external_id"] == "ext-123"
        assert response.data["external_source"] == "jira"

    @pytest.mark.django_db
    def test_create_default_state_updates_existing(self, authenticated_client, list_url, base_setup_data):
        """Test creating a default state removes default from existing states"""
        # Create existing default state
        existing_default = self.create_state(
            base_setup_data,
            name="Existing Default",
            default=True
        )

        data = {
            "name": "New Default State",
            "color": "#0000FF",
            "group": "started",
            "default": True,
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["default"] is True

        # Verify previous default is no longer default
        existing_default.refresh_from_db()
        assert existing_default.default is False

    # Conflict Tests
    @pytest.mark.django_db
    @pytest.mark.parametrize("conflict_field,conflict_data,expected_message", [
        ("name", {"name": "Duplicate State"}, "State with the same name already exists"),
        ("external_id", {"external_id": "ext-456", "external_source": "github"}, 
         "State with the same external id and external source already exists"),
    ])
    def test_create_state_conflicts(self, authenticated_client, list_url, base_setup_data, 
                                   conflict_field, conflict_data, expected_message):
        """Test state creation conflicts for name and external ID"""
        # Create existing state
        existing_data = {"name": "Existing State", "color": "#FF0000", "group": "backlog"}
        if conflict_field == "external_id":
            existing_data.update(conflict_data)
        else:
            existing_data.update(conflict_data)
        
        self.create_state(base_setup_data, **existing_data)

        # Try to create conflicting state
        new_data = {
            "name": "Another State",
            "color": "#00FF00",
            "group": "started",
        }
        new_data.update(conflict_data)

        response = authenticated_client.post(list_url, new_data, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "error" in response.data
        assert expected_message in response.data["error"]
        assert "id" in response.data

    # Validation Tests
    @pytest.mark.django_db
    @pytest.mark.parametrize("invalid_data", [
        {"name": "", "color": "#FF0000", "group": "started"},  # Empty name
        {"name": "Valid", "color": "", "group": "started"},    # Empty color
        {"name": "Valid", "color": "#FF0000", "group": "invalid"},  # Invalid group
    ])
    def test_create_state_validation_errors(self, authenticated_client, list_url, invalid_data):
        """Test state creation with various invalid data combinations"""
        response = authenticated_client.post(list_url, invalid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # Authorization Tests
    @pytest.mark.django_db
    def test_create_state_unauthorized(self, api_client, list_url):
        """Test state creation without authentication"""
        data = {"name": "Unauthorized State", "color": "#FF0000", "group": "started"}
        response = api_client.post(list_url, data, format="json")
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    @pytest.mark.django_db
    def test_create_state_no_project_permission(self, api_client, unauthorized_user, base_setup_data):
        """Test state creation without project permission"""
        api_client.force_authenticate(user=unauthorized_user)
        url = self.get_list_url(base_setup_data)
        data = {"name": "Forbidden State", "color": "#FF0000", "group": "started"}
        
        response = api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    # List Tests
    @pytest.mark.django_db
    def test_list_states_success(self, authenticated_client, list_url, base_setup_data):
        """Test successful listing of states with proper ordering"""
        # Create states with different sequences
        states_data = [
            {"name": "State 2", "sequence": 1000},
            {"name": "State 1", "sequence": 500},
            {"name": "State 3", "sequence": 1500},
        ]
        
        for state_data in states_data:
            self.create_state(base_setup_data, **state_data)

        response = authenticated_client.get(list_url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 3

        # Verify ordering by sequence
        names = [state["name"] for state in response.data["results"]]
        assert names == ["State 1", "State 2", "State 3"]  # Ordered by sequence

        # Verify response structure
        state_data = response.data["results"][0]
        required_fields = ["id", "name", "color", "group", "sequence"]
        for field in required_fields:
            assert field in state_data

    @pytest.mark.django_db
    def test_list_states_filters_triage(self, authenticated_client, list_url, base_setup_data):
        """Test that triage states are excluded from list"""
        self.create_state(base_setup_data, name="Regular State", is_triage=False)
        self.create_state(base_setup_data, name="Triage State", is_triage=True)

        response = authenticated_client.get(list_url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Regular State"

    @pytest.mark.django_db
    def test_list_states_empty_project(self, authenticated_client, list_url):
        """Test listing states for project with no states"""
        response = authenticated_client.get(list_url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    @pytest.mark.django_db
    def test_list_states_pagination_and_fields(self, authenticated_client, list_url, base_setup_data):
        """Test pagination and field filtering"""
        # Create multiple states
        for i in range(5):
            self.create_state(base_setup_data, name=f"State {i}")

        # Test pagination
        response = authenticated_client.get(list_url, {"per_page": 3})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3
        assert response.data["count"] == 5

        # Test field filtering
        response = authenticated_client.get(list_url, {"fields": "id,name"})
        assert response.status_code == status.HTTP_200_OK
        state_data = response.data["results"][0]
        expected_fields = {"id", "name"}
        actual_fields = set(state_data.keys())
        assert actual_fields <= expected_fields

    # Authorization tests for list
    @pytest.mark.django_db
    def test_list_states_unauthorized(self, api_client, list_url):
        """Test listing states without authentication"""
        response = api_client.get(list_url)
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.contract
class TestStateDetailAPI(BaseStateTestSetup):
    """Test contract for StateDetailAPIEndpoint"""

    @pytest.fixture
    def test_state(self, base_setup_data):
        """Create a test state"""
        return self.create_state(
            base_setup_data,
            name="Test State",
            description="Test description"
        )

    @pytest.fixture
    def detail_url(self, base_setup_data, test_state):
        """Return URL for state detail endpoint"""
        return self.get_detail_url(base_setup_data, test_state.id)

    # Retrieve Tests
    @pytest.mark.django_db
    def test_retrieve_state_success(self, authenticated_client, detail_url, test_state):
        """Test successful state retrieval"""
        response = authenticated_client.get(detail_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(test_state.id)
        assert response.data["name"] == test_state.name
        assert response.data["color"] == test_state.color
        assert response.data["group"] == test_state.group

    @pytest.mark.django_db
    def test_retrieve_state_not_found(self, authenticated_client, base_setup_data):
        """Test retrieving non-existent state"""
        url = self.get_detail_url(base_setup_data, uuid4())
        response = authenticated_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_retrieve_triage_state_filtered(self, authenticated_client, base_setup_data):
        """Test that triage states are not accessible"""
        triage_state = self.create_state(
            base_setup_data,
            name="Triage State",
            is_triage=True
        )
        url = self.get_detail_url(base_setup_data, triage_state.id)
        
        response = authenticated_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # Update Tests
    @pytest.mark.django_db
    def test_update_state_success(self, authenticated_client, detail_url, test_state):
        """Test successful state update"""
        data = {
            "name": "Updated State Name",
            "description": "Updated description",
            "color": "#00FF00",
            "group": "completed",
        }

        response = authenticated_client.patch(detail_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        for key, value in data.items():
            assert response.data[key] == value

        # Verify database update
        test_state.refresh_from_db()
        assert test_state.name == "Updated State Name"

    @pytest.mark.django_db
    def test_update_state_partial(self, authenticated_client, detail_url, test_state):
        """Test partial state update"""
        original_name = test_state.name
        data = {"color": "#FF00FF"}

        response = authenticated_client.patch(detail_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == original_name  # Unchanged
        assert response.data["color"] == "#FF00FF"    # Updated

    @pytest.mark.django_db
    def test_update_state_external_id_conflict(self, authenticated_client, detail_url, base_setup_data):
        """Test updating state with conflicting external ID"""
        # Create conflicting state
        self.create_state(
            base_setup_data,
            name="Conflict State",
            external_id="conflict-id",
            external_source="bitbucket"
        )

        data = {
            "external_id": "conflict-id",
            "external_source": "bitbucket",
        }

        response = authenticated_client.patch(detail_url, data, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "error" in response.data
        assert "State with the same external id and external source already exists" in response.data["error"]

    @pytest.mark.django_db
    def test_update_state_same_external_id(self, authenticated_client, base_setup_data):
        """Test updating state with its own external ID doesn't cause conflict"""
        state = self.create_state(
            base_setup_data,
            name="Same ID State",
            external_id="same-id",
            external_source="same-source"
        )
        url = self.get_detail_url(base_setup_data, state.id)

        data = {
            "external_id": "same-id",  # Same value
            "external_source": "same-source",
            "name": "Updated Name",
        }

        response = authenticated_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Updated Name"

    @pytest.mark.django_db
    def test_update_state_validation_errors(self, authenticated_client, detail_url):
        """Test state update with invalid data"""
        data = {
            "name": "",  # Empty name
            "group": "invalid_group",  # Invalid group
        }

        response = authenticated_client.patch(detail_url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # Delete Tests
    @pytest.mark.django_db
    def test_delete_state_success(self, authenticated_client, detail_url, test_state):
        """Test successful state deletion"""
        response = authenticated_client.delete(detail_url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not State.objects.filter(id=test_state.id).exists()

    @pytest.mark.django_db
    def test_delete_default_state_forbidden(self, authenticated_client, detail_url, test_state):
        """Test deleting default state is forbidden"""
        test_state.default = True
        test_state.save()

        response = authenticated_client.delete(detail_url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "Default state cannot be deleted" in response.data["error"]
        assert State.objects.filter(id=test_state.id).exists()

    @pytest.mark.django_db
    @patch('plane.db.models.Issue.issue_objects')
    def test_delete_state_with_issues_forbidden(self, mock_issue_objects, authenticated_client, 
                                               detail_url, test_state):
        """Test deleting state with issues is forbidden"""
        mock_issue_objects.filter.return_value.exists.return_value = True

        response = authenticated_client.delete(detail_url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "The state is not empty, only empty states can be deleted" in response.data["error"]
        assert State.objects.filter(id=test_state.id).exists()

    @pytest.mark.django_db
    def test_delete_state_not_found(self, authenticated_client, base_setup_data):
        """Test deleting non-existent state"""
        url = self.get_detail_url(base_setup_data, uuid4())
        response = authenticated_client.delete(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # Authorization Tests
    @pytest.mark.django_db
    def test_detail_operations_unauthorized(self, api_client, detail_url):
        """Test all detail operations without authentication"""
        operations = [
            ('get', {}),
            ('patch', {"name": "Update"}),
            ('delete', {})
        ]
        
        for method, data in operations:
            response = getattr(api_client, method)(detail_url, data, format="json")
            assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.contract
class TestStateEndpointsAdvanced(BaseStateTestSetup):
    """Test advanced scenarios and edge cases"""

    @pytest.mark.django_db
    def test_cross_project_access_forbidden(self, authenticated_client, base_setup_data):
        """Test that users cannot access states from projects they don't have access to"""
        # Create another project without user membership
        other_project = Project.objects.create(
            name="Other Project",
            identifier="OTHER",
            workspace=base_setup_data["workspace"],
            created_by=base_setup_data["user"]
        )
        other_state = self.create_state(
            {**base_setup_data, "project": other_project},
            name="Other State"
        )

        url = self.get_detail_url(
            {**base_setup_data, "project": other_project},
            other_state.id
        )
        response = authenticated_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_cross_workspace_access_forbidden(self, authenticated_client, base_setup_data):
        """Test that users cannot access states from different workspaces"""
        other_user = User.objects.create(
            email="other@test.com",
            first_name="Other",
            last_name="User"
        )
        other_workspace = Workspace.objects.create(
            name="Other Workspace",
            slug="other-workspace",
            owner=other_user
        )
        other_project = Project.objects.create(
            name="Other Project",
            identifier="OTHER",
            workspace=other_workspace,
            created_by=other_user
        )
        other_state = self.create_state(
            {"project": other_project, "workspace": other_workspace},
            name="Other State"
        )

        url = f"/api/v1/workspaces/{other_workspace.slug}/projects/{other_project.id}/states/{other_state.id}/"
        response = authenticated_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_state_sequence_and_slug_generation(self, authenticated_client, base_setup_data):
        """Test automatic sequence assignment and slug generation"""
        # Create state with high sequence
        existing_state = self.create_state(
            base_setup_data,
            name="Existing State",
            sequence=50000
        )

        url = self.get_list_url(base_setup_data)
        data = {
            "name": "State With Spaces",
            "color": "#FF0000",
            "group": "started",
        }

        response = authenticated_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["sequence"] > existing_state.sequence

        # Verify slug generation
        state = State.objects.get(id=response.data["id"])
        assert state.slug == "state-with-spaces"

    @pytest.mark.django_db
    def test_state_group_validation(self, authenticated_client, base_setup_data):
        """Test that all valid state groups are accepted"""
        valid_groups = ["backlog", "unstarted", "started", "completed", "cancelled"]
        url = self.get_list_url(base_setup_data)

        for group in valid_groups:
            data = {
                "name": f"State {group.title()}",
                "color": "#FF0000",
                "group": group,
            }

            response = authenticated_client.post(url, data, format="json")
            assert response.status_code == status.HTTP_200_OK
            assert response.data["group"] == group

    @pytest.mark.django_db
    def test_archived_project_filtering(self, authenticated_client, base_setup_data):
        """Test that archived project states are properly handled"""
        from django.utils import timezone
        
        # Archive the project
        base_setup_data["project"].archived_at = timezone.now()
        base_setup_data["project"].save()

        # Create state in archived project
        self.create_state(base_setup_data, name="Archived Project State")

        url = self.get_list_url(base_setup_data)
        response = authenticated_client.get(url)

        # Should return empty results for archived project
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0