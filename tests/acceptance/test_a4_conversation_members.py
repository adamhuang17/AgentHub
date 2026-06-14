from tests.support import create_conversation, enabled_agents, item_list


def test_a4_conversation_members(api_request, unique_id):
    agents = enabled_agents(api_request, minimum=2)
    selected = agents[:2]
    conversation = create_conversation(
        api_request,
        f"{unique_id} group members",
        mode="group_agent",
        agent_ids=[agent["id"] for agent in selected],
    )

    _, payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/members", expected=200)
    members = item_list(payload)
    member_types = {member["member_type"] for member in members}
    agent_ids = {member["member_id"] for member in members if member["member_type"] == "agent"}

    assert "user" in member_types
    assert "orchestrator" in member_types
    assert {agent["id"] for agent in selected}.issubset(agent_ids)
    for member in members:
        if member["member_type"] == "agent":
            assert member.get("name")
            assert member.get("provider")
            assert isinstance(member.get("capability_tags", []), list)
