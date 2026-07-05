import pytest
from pydantic import ValidationError

from app.enums import JobStatus, ModuleType, SaveStatus
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.equipment_config import EquipmentConfig
from app.schemas.flow_recipe_config import FlowRecipeConfig
from app.schemas.job import JobCreate
from app.schemas.module import ModuleCreate
from app.schemas.process_recipe_config import ProcessRecipeConfig
from app.schemas.user import UserCreate


def test_user_create_requires_password_min_length():
    with pytest.raises(ValidationError):
        UserCreate(user_name="Test", user_email="a@b.com", user_password="short")


def test_user_create_requires_valid_email():
    with pytest.raises(ValidationError):
        UserCreate(user_name="Test", user_email="not-an-email", user_password="Password123!")


def test_user_create_rejects_weak_password_no_special_char():
    with pytest.raises(ValidationError):
        UserCreate(user_name="Test", user_email="a@b.com", user_password="password123")


def test_user_create_rejects_weak_password_no_digit():
    with pytest.raises(ValidationError):
        UserCreate(user_name="Test", user_email="a@b.com", user_password="password!!!")


def test_user_create_accepts_strong_password():
    u = UserCreate(user_name="Test", user_email="a@b.com", user_password="Password123!")
    assert u.user_password == "Password123!"


def test_register_request_rejects_weak_password():
    with pytest.raises(ValidationError):
        RegisterRequest(user_name="Test", email="a@b.com", password="password123")


def test_register_request_accepts_strong_password():
    r = RegisterRequest(user_name="Test", email="a@b.com", password="Password123!")
    assert r.password == "Password123!"


def test_job_create_valid():
    import uuid as _uuid
    sim_id = _uuid.uuid4()
    job = JobCreate(simulator_id=sim_id, job_name="My Job")
    assert job.job_name == "My Job"
    assert job.simulator_id == sim_id


def test_module_create_valid_types():
    m = ModuleCreate(
        module_name="PM1", module_type=ModuleType.PROCESS_MODULE, module_subtype=["type_a"]
    )
    assert m.module_type == ModuleType.PROCESS_MODULE


def test_module_create_invalid_type():
    with pytest.raises(ValidationError):
        ModuleCreate(module_name="PM1", module_type="invalid_type", module_subtype=[])


def test_equipment_config_invalid_cluster_type():
    with pytest.raises(ValidationError):
        EquipmentConfig(equipment_name="E1", cluster_type="triple_cluster", modules=[])


def test_equipment_config_valid():
    cfg = EquipmentConfig(
        equipment_name="E1",
        cluster_type="dual_cluster",
        modules=[{"module_id": 0, "cluster": ["cluster_1"]}],
    )
    assert cfg.cluster_type == "dual_cluster"


def test_flow_recipe_config_valid():
    cfg = FlowRecipeConfig(
        flow_recipe_name="FR1",
        num_process_steps=2,
        process_recipe_steps=[
            {"step": 1, "process_recipe_id": "abc"},
            {"step": 2, "process_recipe_id": "def"},
        ],
    )
    assert cfg.num_process_steps == 2


def test_process_recipe_config_valid():
    cfg = ProcessRecipeConfig(
        process_recipe_name="PR1", user_added_process_modules=[1, 2, 3]
    )
    assert cfg.user_added_process_modules == [1, 2, 3]


def test_login_request_requires_valid_email():
    with pytest.raises(ValidationError):
        LoginRequest(email="bad-email", password="pass")
