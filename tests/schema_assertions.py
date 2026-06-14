def assert_keys(payload, required):
    missing = [key for key in required if key not in payload]
    assert not missing, f"Missing keys {missing} in {payload}"


def assert_non_empty_string(value, label):
    assert isinstance(value, str) and value.strip(), f"{label} must be a non-empty string"


def assert_list(value, label):
    assert isinstance(value, list), f"{label} must be a list"
