from app.monitoring import before_send


def test_before_send_scrubs_sensitive_fields():
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret-token",
            },
            "data": {
                "password": "super-secret",
                "nested": {"license_key": "license-secret"},
            },
        },
        "extra": {
            "token": "abc",
            "safe": "value",
        },
    }

    cleaned = before_send(event, None)

    assert cleaned["request"]["headers"]["Authorization"] == "[Filtered]"
    assert cleaned["request"]["data"]["password"] == "[Filtered]"
    assert cleaned["request"]["data"]["nested"]["license_key"] == "[Filtered]"
    assert cleaned["extra"]["token"] == "[Filtered]"
    assert cleaned["extra"]["safe"] == "value"
