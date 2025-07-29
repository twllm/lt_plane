import pytest
from django.urls import reverse
from rest_framework import status
from unittest.mock import patch

from plane.db.models import State, Issue, Workspace, WorkspaceMember, Project, ProjectMember, User


@pytest.mark.contract
class TestStateListCreateAPIEndpoint:
    """Test contract for StateListCreateAPIEndpoint"""

    @pytest.fixture
    def setup_data(self, create_user):
        """Set up test data with user, workspace, and project"""
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
    def authenticated_client(self, api_client, setup_data):
        """Return authenticated API client"""
        api_client.force_authenticate(user=setup_data["user"])
        return api_client

    @pytest.fixture
    def list_url(self, setup_data):
        """Return URL for state list/create endpoint"""
        return f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"

    @pytest.mark.django_db
    def test_create_state_success(self, authenticated_client, list_url, setup_data):
        """Test successful state creation"""
        data = {
            "name": "New State",
            "description": "Test state description",
            "color": "#FF0000",
            "group": "started",
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "New State"
        assert response.data["description"] == "Test state description"
        assert response.data["color"] == "#FF0000"
        assert response.data["group"] == "started"
        assert response.data["default"] is False
        assert response.data["is_triage"] is False

        # Verify state was created in database
        state = State.objects.get(id=response.data["id"])
        assert state.name == "New State"
        assert state.project == setup_data["project"]
        assert state.workspace == setup_data["workspace"]

    @pytest.mark.django_db
    def test_create_state_minimal_data(self, authenticated_client, list_url, setup_data):
        """Test state creation with minimal required data"""
        data = {
            "name": "Minimal State",
            "color": "#00FF00",
            "group": "backlog",
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Minimal State"
        assert response.data["color"] == "#00FF00"
        assert response.data["group"] == "backlog"
        assert response.data["description"] == ""

    @pytest.mark.django_db
    def test_create_state_with_default_flag(self, authenticated_client, list_url, setup_data):
        """Test creating a default state updates other states"""
        # Create an existing default state
        existing_default = State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Existing Default",
            color="#FF0000",
            group="backlog",
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

        # Verify the previous default state is no longer default
        existing_default.refresh_from_db()
        assert existing_default.default is False

    @pytest.mark.django_db
    def test_create_state_with_external_id(self, authenticated_client, list_url, setup_data):
        """Test state creation with external ID"""
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
    def test_create_state_duplicate_name_conflict(self, authenticated_client, list_url, setup_data):
        """Test creating state with duplicate name returns 409"""
        # Create existing state
        State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Duplicate State",
            color="#FF0000",
            group="backlog"
        )

        data = {
            "name": "Duplicate State",
            "color": "#FF0000",
            "group": "started",
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "error" in response.data
        assert "State with the same name already exists" in response.data["error"]
        assert "id" in response.data

    @pytest.mark.django_db
    def test_create_state_duplicate_external_id_conflict(self, authenticated_client, list_url, setup_data):
        """Test creating state with duplicate external ID returns 409"""
        # Create existing state with external ID
        State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Existing State",
            color="#FF0000",
            group="backlog",
            external_id="ext-456",
            external_source="github"
        )

        data = {
            "name": "Another State",
            "color": "#FF0000",
            "group": "started",
            "external_id": "ext-456",
            "external_source": "github",
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "error" in response.data
        assert "State with the same external id and external source already exists" in response.data["error"]
        assert "id" in response.data

    @pytest.mark.django_db
    def test_create_state_validation_errors(self, authenticated_client, list_url, setup_data):
        """Test state creation with invalid data returns 400"""
        data = {
            "name": "",  # Empty name
            "color": "",  # Empty color
            "group": "invalid_group",  # Invalid group
        }

        response = authenticated_client.post(list_url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "name" in response.data or "color" in response.data or "group" in response.data

    @pytest.mark.django_db
    def test_create_state_unauthorized(self, api_client, list_url):
        """Test state creation without authentication returns 401"""
        data = {
            "name": "Unauthorized State",
            "color": "#FF0000",
            "group": "started",
        }

        response = api_client.post(list_url, data, format="json")

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    @pytest.mark.django_db
    def test_create_state_no_project_permission(self, api_client, setup_data):
        """Test state creation without project permission returns 403"""
        # Create user without project membership
        unauthorized_user = User.objects.create(
            email="unauthorized@test.com",
            first_name="Unauthorized",
            last_name="User"
        )
        api_client.force_authenticate(user=unauthorized_user)

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"
        data = {
            "name": "Forbidden State",
            "color": "#FF0000",
            "group": "started",
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_list_states_success(self, authenticated_client, list_url, setup_data):
        """Test successful listing of states"""
        # Create test states
        states = [
            State.objects.create(
                project=setup_data["project"],
                workspace=setup_data["workspace"],
                name=f"State {i}",
                color="#FF0000",
                group="backlog"
            ) for i in range(3)
        ]

        response = authenticated_client.get(list_url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 3

        # Verify state data structure
        state_data = response.data["results"][0]
        assert "id" in state_data
        assert "name" in state_data
        assert "color" in state_data
        assert "group" in state_data
        assert "sequence" in state_data

    @pytest.mark.django_db
    def test_list_states_filters_triage(self, authenticated_client, list_url, setup_data):
        """Test that triage states are filtered out"""
        # Create regular state and triage state
        State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Regular State",
            color="#FF0000",
            group="backlog",
            is_triage=False
        )
        State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Triage State",
            color="#FF0000",
            group="backlog",
            is_triage=True
        )

        response = authenticated_client.get(list_url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Regular State"

    @pytest.mark.django_db
    def test_list_states_empty_project(self, authenticated_client, list_url, setup_data):
        """Test listing states for project with no states"""
        response = authenticated_client.get(list_url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 0

    @pytest.mark.django_db
    def test_list_states_unauthorized(self, api_client, list_url):
        """Test listing states without authentication returns 401"""
        response = api_client.get(list_url)

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    @pytest.mark.django_db
    def test_list_states_no_project_permission(self, api_client, setup_data):
        """Test listing states without project permission returns 403"""
        # Create user without project membership
        unauthorized_user = User.objects.create(
            email="unauthorized2@test.com",
            first_name="Unauthorized",
            last_name="User"
        )
        api_client.force_authenticate(user=unauthorized_user)

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"

        response = api_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.contract
class TestStateDetailAPIEndpoint:
    """Test contract for StateDetailAPIEndpoint"""

    @pytest.fixture
    def setup_data(self, create_user):
        """Set up test data with user, workspace, project, and state"""
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
        state = State.objects.create(
            project=project,
            workspace=workspace,
            name="Test State",
            color="#FF0000",
            group="backlog"
        )
        return {
            "user": user,
            "workspace": workspace,
            "project": project,
            "state": state,
        }

    @pytest.fixture
    def authenticated_client(self, api_client, setup_data):
        """Return authenticated API client"""
        api_client.force_authenticate(user=setup_data["user"])
        return api_client

    @pytest.fixture
    def detail_url(self, setup_data):
        """Return URL for state detail endpoint"""
        return f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/{setup_data['state'].id}/"

    @pytest.mark.django_db
    def test_retrieve_state_success(self, authenticated_client, detail_url, setup_data):
        """Test successful state retrieval"""
        response = authenticated_client.get(detail_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(setup_data["state"].id)
        assert response.data["name"] == setup_data["state"].name
        assert response.data["color"] == setup_data["state"].color
        assert response.data["group"] == setup_data["state"].group

    @pytest.mark.django_db
    def test_retrieve_state_not_found(self, authenticated_client, setup_data):
        """Test retrieving non-existent state returns 404"""
        from uuid import uuid4
        non_existent_id = uuid4()
        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/{non_existent_id}/"

        response = authenticated_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_retrieve_state_unauthorized(self, api_client, detail_url):
        """Test retrieving state without authentication returns 401"""
        response = api_client.get(detail_url)

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    @pytest.mark.django_db
    def test_update_state_success(self, authenticated_client, detail_url, setup_data):
        """Test successful state update"""
        data = {
            "name": "Updated State Name",
            "description": "Updated description",
            "color": "#00FF00",
            "group": "completed",
        }

        response = authenticated_client.patch(detail_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Updated State Name"
        assert response.data["description"] == "Updated description"
        assert response.data["color"] == "#00FF00"
        assert response.data["group"] == "completed"

        # Verify database was updated
        setup_data["state"].refresh_from_db()
        assert setup_data["state"].name == "Updated State Name"

    @pytest.mark.django_db
    def test_update_state_partial(self, authenticated_client, detail_url, setup_data):
        """Test partial state update"""
        original_name = setup_data["state"].name
        data = {"color": "#FF00FF"}

        response = authenticated_client.patch(detail_url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == original_name  # Unchanged
        assert response.data["color"] == "#FF00FF"  # Updated

    @pytest.mark.django_db
    def test_update_state_external_id_conflict(self, authenticated_client, detail_url, setup_data):
        """Test updating state with conflicting external ID returns 409"""
        # Create another state with external ID
        State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Conflict State",
            color="#FF0000",
            group="backlog",
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
    def test_update_state_validation_errors(self, authenticated_client, detail_url, setup_data):
        """Test state update with invalid data returns 400"""
        data = {
            "name": "",  # Empty name
            "group": "invalid_group",  # Invalid group
        }

        response = authenticated_client.patch(detail_url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_update_state_unauthorized(self, api_client, detail_url):
        """Test updating state without authentication returns 401"""
        data = {"name": "Unauthorized Update"}

        response = api_client.patch(detail_url, data, format="json")

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    @pytest.mark.django_db
    def test_delete_state_success(self, authenticated_client, detail_url, setup_data):
        """Test successful state deletion"""
        response = authenticated_client.delete(detail_url)

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify state was deleted
        assert not State.objects.filter(id=setup_data["state"].id).exists()

    @pytest.mark.django_db
    def test_delete_default_state_forbidden(self, authenticated_client, detail_url, setup_data):
        """Test deleting default state returns 400"""
        # Make the state default
        setup_data["state"].default = True
        setup_data["state"].save()

        response = authenticated_client.delete(detail_url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "Default state cannot be deleted" in response.data["error"]

        # Verify state still exists
        assert State.objects.filter(id=setup_data["state"].id).exists()

    @pytest.mark.django_db
    @patch('plane.db.models.Issue.issue_objects')
    def test_delete_state_with_issues_forbidden(self, mock_issue_objects, authenticated_client, detail_url, setup_data):
        """Test deleting state with issues returns 400"""
        # Mock that issues exist for this state
        mock_issue_objects.filter.return_value.exists.return_value = True

        response = authenticated_client.delete(detail_url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "The state is not empty, only empty states can be deleted" in response.data["error"]

        # Verify state still exists
        assert State.objects.filter(id=setup_data["state"].id).exists()

    @pytest.mark.django_db
    def test_delete_state_not_found(self, authenticated_client, setup_data):
        """Test deleting non-existent state returns 404"""
        from uuid import uuid4
        non_existent_id = uuid4()
        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/{non_existent_id}/"

        response = authenticated_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_delete_state_unauthorized(self, api_client, detail_url):
        """Test deleting state without authentication returns 401"""
        response = api_client.delete(detail_url)

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    @pytest.mark.django_db
    def test_delete_triage_state_filtered(self, authenticated_client, setup_data):
        """Test that triage states are not accessible for deletion"""
        # Create a triage state
        triage_state = State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Triage State",
            color="#FF0000",
            group="backlog",
            is_triage=True
        )

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/{triage_state.id}/"

        response = authenticated_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_permissions_different_project(self, authenticated_client, setup_data):
        """Test that users cannot access states from different projects"""
        # Create another project and state
        other_project = Project.objects.create(
            name="Other Project",
            identifier="OTHER",
            workspace=setup_data["workspace"],
            created_by=setup_data["user"]
        )
        other_state = State.objects.create(
            project=other_project,
            workspace=setup_data["workspace"],
            name="Other State",
            color="#FF0000",
            group="backlog"
        )

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{other_project.id}/states/{other_state.id}/"

        response = authenticated_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_permissions_different_workspace(self, authenticated_client, setup_data):
        """Test that users cannot access states from different workspaces"""
        # Create another workspace, project, and state
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
        other_state = State.objects.create(
            project=other_project,
            workspace=other_workspace,
            name="Other State",
            color="#FF0000",
            group="backlog"
        )

        url = f"/api/v1/workspaces/{other_workspace.slug}/projects/{other_project.id}/states/{other_state.id}/"

        response = authenticated_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.contract
class TestStateEndpointsEdgeCases:
    """Test edge cases and advanced scenarios for state endpoints"""

    @pytest.fixture
    def setup_data(self, create_user):
        """Set up complex test data"""
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
    def authenticated_client(self, api_client, setup_data):
        """Return authenticated API client"""
        api_client.force_authenticate(user=setup_data["user"])
        return api_client

    @pytest.mark.django_db
    def test_state_sequence_ordering(self, authenticated_client, setup_data):
        """Test that states are ordered by sequence"""
        # Create states with different sequences
        state1 = State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="First",
            color="#FF0000",
            group="backlog",
            sequence=1000
        )
        state2 = State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Second",
            color="#FF0000",
            group="backlog",
            sequence=500
        )
        state3 = State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Third",
            color="#FF0000",
            group="backlog",
            sequence=1500
        )

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"
        response = authenticated_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3

        # Check ordering by sequence
        names = [state["name"] for state in response.data["results"]]
        assert names == ["Second", "First", "Third"]  # Ordered by sequence: 500, 1000, 1500

    @pytest.mark.django_db
    def test_create_state_auto_sequence(self, authenticated_client, setup_data):
        """Test that new states get automatic sequence values"""
        # Create a state with high sequence
        existing_state = State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Existing State",
            color="#FF0000",
            group="backlog",
            sequence=50000
        )

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"
        data = {
            "name": "Auto Sequence State",
            "color": "#FF0000",
            "group": "started",
        }

        response = authenticated_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        # New state should have sequence > existing_state.sequence
        assert response.data["sequence"] > existing_state.sequence

    @pytest.mark.django_db
    def test_state_slug_generation(self, authenticated_client, setup_data):
        """Test that state slug is automatically generated from name"""
        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"
        data = {
            "name": "State With Spaces",
            "color": "#FF0000",
            "group": "started",
        }

        response = authenticated_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        
        # Verify slug was generated
        state = State.objects.get(id=response.data["id"])
        assert state.slug == "state-with-spaces"

    @pytest.mark.django_db
    def test_state_group_choices_validation(self, authenticated_client, setup_data):
        """Test that only valid group choices are accepted"""
        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"
        valid_groups = ["backlog", "unstarted", "started", "completed", "cancelled"]

        for group in valid_groups:
            data = {
                "name": f"State {group}",
                "color": "#FF0000",
                "group": group,
            }

            response = authenticated_client.post(url, data, format="json")
            assert response.status_code == status.HTTP_200_OK
            assert response.data["group"] == group

    @pytest.mark.django_db
    def test_archived_project_states_filtered(self, authenticated_client, setup_data):
        """Test that states from archived projects are filtered out"""
        # Archive the project
        from django.utils import timezone
        setup_data["project"].archived_at = timezone.now()
        setup_data["project"].save()

        # Create a state in the archived project
        State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Archived Project State",
            color="#FF0000",
            group="backlog"
        )

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"
        response = authenticated_client.get(url)

        # Should return empty results for archived project
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    @pytest.mark.django_db
    def test_external_id_update_same_value(self, authenticated_client, setup_data):
        """Test updating state with same external ID doesn't cause conflict"""
        state = State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Same ID State",
            color="#FF0000",
            group="backlog",
            external_id="same-id",
            external_source="same-source"
        )

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/{state.id}/"
        data = {
            "external_id": "same-id",  # Same value
            "external_source": "same-source",
            "name": "Updated Name",
        }

        response = authenticated_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Updated Name"
        assert response.data["external_id"] == "same-id"

    @pytest.mark.django_db
    def test_pagination_parameters(self, authenticated_client, setup_data):
        """Test that pagination parameters work correctly"""
        # Create multiple states
        for i in range(10):
            State.objects.create(
                project=setup_data["project"],
                workspace=setup_data["workspace"],
                name=f"State {i}",
                color="#FF0000",
                group="backlog"
            )

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"
        
        # Test with per_page parameter
        response = authenticated_client.get(url, {"per_page": 5})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 5
        assert "next" in response.data
        assert response.data["count"] == 10

    @pytest.mark.django_db
    def test_fields_parameter(self, authenticated_client, setup_data):
        """Test that fields parameter filters response fields"""
        State.objects.create(
            project=setup_data["project"],
            workspace=setup_data["workspace"],
            name="Test State",
            color="#FF0000",
            group="backlog"
        )

        url = f"/api/v1/workspaces/{setup_data['workspace'].slug}/projects/{setup_data['project'].id}/states/"
        
        # Test with fields parameter to only get id and name
        response = authenticated_client.get(url, {"fields": "id,name"})

        assert response.status_code == status.HTTP_200_OK
        state_data = response.data["results"][0]
        
        # Should only have requested fields
        assert "id" in state_data
        assert "name" in state_data
        # Should not have other fields like description, color, etc.
        expected_fields = set(["id", "name"])
        actual_fields = set(state_data.keys())
        assert actual_fields <= expected_fields  # actual should be subset of expected