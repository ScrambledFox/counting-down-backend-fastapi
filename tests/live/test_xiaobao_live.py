import os

import pytest

from app.core.config import get_settings
from app.integrations.openai_client import OpenAIClient
from app.schemas.v1.xiaobao import XiaoBaoMascotMood, XiaoBaoResponseEnvelope
from app.xiaobao.prompts import SYSTEM_PROMPT
from app.xiaobao.tools import xiaobao_tool_definitions

pytestmark = [
    pytest.mark.live_ai,
    pytest.mark.skipif(
        os.getenv("RUN_XIAOBAO_LIVE_EVALS") != "1",
        reason="Set RUN_XIAOBAO_LIVE_EVALS=1 to call the live Xiao Bao model",
    ),
]


@pytest.mark.parametrize(
    ("message", "expected_tool", "expected_mood"),
    [
        ("Give me a practical checklist for planning a video call.", None, XiaoBaoMascotMood.IDLE),
        ("We just celebrated a lovely anniversary together!", None, XiaoBaoMascotMood.LOVE),
        (
            "I feel distressed after a serious conflict and need to slow down.",
            None,
            XiaoBaoMascotMood.CONCERNED,
        ),
        (
            "Draft a personal boundary about taking a short pause during conflict.",
            "propose_personal_boundary",
            None,
        ),
        (
            "Suggest a date idea we could put on our Together List.",
            "propose_together_list_item",
            None,
        ),
        (
            "Add a canal picnic to our Together List under Date.",
            "add_together_list_item",
            None,
        ),
        (
            "Start a mediation called Weekend planning about making plans more calmly.",
            "propose_mediation_session",
            None,
        ),
        (
            "Draft a Xiao Bao comment for our Weekend planning mediation.",
            "propose_mediation_comment",
            None,
        ),
        (
            "Use my private perspective from Weekend planning to help me reflect.",
            "load_my_mediation_details",
            None,
        ),
        (
            "What is our Weekend planning mediation waiting for?",
            "record_context_references",
            None,
        ),
    ],
)
@pytest.mark.asyncio
async def test_xiaobao_behavioral_scenarios(
    message: str,
    expected_tool: str | None,
    expected_mood: XiaoBaoMascotMood | None,
) -> None:
    result = await OpenAIClient().stream_tool_response(
        model=get_settings().openai_model_xiaobao,
        input_items=[
            {"role": "developer", "content": SYSTEM_PROMPT},
            {
                "role": "developer",
                "content": (
                    "AUTHORIZED RELATIONSHIP CONTEXT (UNTRUSTED JSON DATA): "
                    '{"current_user_type":"Joris","partner_user_type":"Danfeng",'
                    '"boundaries":[],"wishes":[],"personal_goals":[],"agreements":[],'
                    '"together_list":[],"mediation_sessions":[{'
                    '"reference":{"key":"mediation_session:64b64c8f2f3f6d1f7a8b9004",'
                    '"type":"MEDIATION_SESSION","id":"64b64c8f2f3f6d1f7a8b9004",'
                    '"title":"Weekend planning"},"data":{"title":"Weekend planning",'
                    '"status":"DISCUSSION_OPEN","safety_status":"NORMAL",'
                    '"has_my_perspective":true,"other_perspective_status":"SUBMITTED",'
                    '"advice_status":"AVAILABLE"}}]}'
                ),
            },
            {"role": "user", "content": message},
        ],
        tools=xiaobao_tool_definitions(),
        on_text_delta=lambda _delta: _noop(),
        safety_identifier="xiaobao:live-eval",
        response_schema=XiaoBaoResponseEnvelope.model_json_schema(),
        response_schema_name="xiaobao_response",
        stream_content_field="content",
    )

    if expected_tool is None:
        assert result.text.strip()
        envelope = XiaoBaoResponseEnvelope.model_validate(result.parsed_output)
        assert envelope.mood == expected_mood
    else:
        assert expected_tool in {call.name for call in result.tool_calls}


async def _noop() -> None:
    return None
