import qraft.api as api


def test_previous_controller_owner_is_additive_public_api():
    from qraft.api import previous_controller_owner

    assert api.API_VERSION == "1.0"
    assert "previous_controller_owner" in api.__all__
    assert previous_controller_owner is api.previous_controller_owner
