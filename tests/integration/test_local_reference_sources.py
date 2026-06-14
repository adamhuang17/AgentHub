from pathlib import Path


REFERENCE_FILES = [
    Path("D:/Public Project/9router-master/open-sse/config/providers.js"),
    Path("D:/Public Project/9router-master/open-sse/handlers/chatCore.js"),
    Path("D:/Public Project/9router-master/open-sse/translator/response/claude-to-openai.js"),
    Path("D:/Public Project/9router-master/open-sse/translator/response/openai-to-claude.js"),
    Path("D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts"),
    Path("D:/Public Project/cline-main/apps/cli/src/runtime/interactive/approvals.ts"),
    Path("D:/Public Project/opencode-dev/packages/opencode/src/session/revert.ts"),
    Path("D:/Public Project/opencode-dev/packages/opencode/src/session/retry.ts"),
    Path("D:/Public Project/opencode-dev/packages/opencode/src/tool/apply_patch.ts"),
    Path("D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts"),
    Path("D:/Public Project/cli-main/skills/lark-im/SKILL.md"),
    Path("D:/Public Project/cli-main/skills/lark-im/references/lark-im-messages-send.md"),
    Path("D:/Public Project/openclaw-main/extensions/feishu/src/streaming-card.ts"),
    Path("D:/Public Project/openclaw-main/extensions/feishu/src") / "pins.ts",
    Path("D:/Public Project/openclaw-main/extensions/feishu/src/docx.ts"),
]


def test_local_reference_sources_exist():
    missing = [str(path) for path in REFERENCE_FILES if not path.exists()]
    assert not missing, f"Acceptance reference source paths are missing: {missing}"
