import pytest
from apps.accounts.models import Tenant, User


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Test Pharma", slug="test-pharma")


@pytest.fixture
def medical_user(db, tenant):
    user = User.objects.create_user(
        username="msl@test.com",
        email="msl@test.com",
        password="testpass123",
        tenant=tenant,
        role=User.Role.MEDICAL_AFFAIRS,
    )
    return user


@pytest.fixture
def commercial_user(db, tenant):
    user = User.objects.create_user(
        username="commercial@test.com",
        email="commercial@test.com",
        password="testpass123",
        tenant=tenant,
        role=User.Role.COMMERCIAL,
    )
    return user
