from tests.support import item_list


def test_agent_profiles_are_not_executable_adapters(api_request):
    _, payload, _ = api_request("GET", "/api/agents?enabled=true", expected=200)
    agents = item_list(payload)
    assert agents
    for agent in agents:
        assert "execution_enabled" in agent
        assert "configured" in agent
        assert "health_status" in agent
        if agent["health_status"] == "profile_only":
            assert agent["execution_enabled"] is False
            assert agent["configured"] is False
