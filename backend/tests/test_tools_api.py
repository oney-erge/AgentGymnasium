from fastapi.testclient import TestClient

from agentgymnasium.app import app

client = TestClient(app)

EXPECTED_CATEGORIES = {
    "building",
    "sensors_control",
    "physics_materials",
    "simulation_inspection",
    "evolution_utilities",
}


def test_list_tools_categories():
    r = client.get("/api/tools")
    assert r.status_code == 200
    body = r.json()
    returned_categories = {c["category"] for c in body["categories"]}
    assert returned_categories == EXPECTED_CATEGORIES


def test_tool_counts():
    r = client.get("/api/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 24
    # enabled_total must match the actual number of tools with enabled_by_default=True
    expected_enabled = sum(
        t["enabled_by_default"]
        for cat in body["categories"]
        for t in cat["tools"]
    )
    assert body["enabled_total"] == expected_enabled


def test_add_bin_enabled():
    r = client.get("/api/tools")
    assert r.status_code == 200
    body = r.json()
    all_tools = [t for cat in body["categories"] for t in cat["tools"]]
    add_bin = next((t for t in all_tools if t["name"] == "add_bin"), None)
    assert add_bin is not None, "add_bin tool must be present in the registry"
    # add_bin is enabled by default so Sorter preset passes validation out of the box.
    assert add_bin["enabled_by_default"] is True


def test_create_body_has_input_schema():
    r = client.get("/api/tools")
    assert r.status_code == 200
    body = r.json()
    all_tools = [t for cat in body["categories"] for t in cat["tools"]]
    create_body = next((t for t in all_tools if t["name"] == "create_body"), None)
    assert create_body is not None, "create_body tool must be present in the registry"
    assert create_body["input_schema"], "create_body must have a non-empty input_schema"
