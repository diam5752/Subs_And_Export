import json
from unittest.mock import MagicMock, patch

import pytest

from backend.app.core import config
from backend.app.core.errors import ProviderDispatchAlreadyClaimedError
from backend.app.services import fact_checking, social_intelligence
from backend.app.services.usage_ledger import ChargeReservation


@pytest.fixture
def mock_client():
    with patch("backend.app.services.llm_utils.load_openai_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


def _paid_reservation(*, action: str) -> ChargeReservation:
    return ChargeReservation(
        ledger_id=f"ledger-{action}",
        user_id="user-paid",
        job_id="job-paid",
        action=action,
        provider="openai",
        model="gpt-test",
        tier="standard",
        reserved_credits=30,
        min_credits=10,
        idempotency_key=f"reserve-{action}",
        paid_credits_reserved=30,
        estimated_cost_usd=0.01,
    )


def _completion_response(
    content: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    response.choices[0].message.refusal = None
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    response.usage.total_tokens = prompt_tokens + completion_tokens
    return response


def test_hybrid_fact_check_extraction_empty(mock_client):
    """Verify detailed check is skipped if extraction returns no claims."""
    # Mock Extraction response (Stage 1)
    mock_msg = mock_client.chat.completions.create.return_value.choices[0].message
    mock_msg.content = '{"claims": []}'
    mock_msg.refusal = None
    mock_client.chat.completions.create.return_value.usage.prompt_tokens = 10
    mock_client.chat.completions.create.return_value.usage.completion_tokens = 5
    mock_client.chat.completions.create.return_value.usage.total_tokens = 15

    result = fact_checking.generate_fact_check("input text", api_key="sk-test")

    assert result.claims_checked == 0
    assert result.items == []
    # Assert chat completion was called EXACTLY once (for extraction only)
    assert mock_client.chat.completions.create.call_count == 1
    # Verify model used was extraction model
    call_args = mock_client.chat.completions.create.call_args
    assert call_args.kwargs["model"] == config.settings.extraction_llm_model
    assert (
        call_args.kwargs["max_completion_tokens"]
        == config.settings.max_llm_output_tokens_extraction
    )

def test_hybrid_fact_check_extraction_found(mock_client):
    """Verify verification runs if claims are extracted."""
    # We need to mock TWO calls.
    # Call 1: Extraction -> Claims found
    # Call 2: Verification -> Fact Check Result

    mock_response_extract = MagicMock()
    mock_response_extract.choices[0].message.content = '{"claims": ["claim 1"]}'
    mock_response_extract.choices[0].message.refusal = None
    mock_response_extract.usage.prompt_tokens = 10
    mock_response_extract.usage.completion_tokens = 10

    mock_response_verify = MagicMock()
    mock_response_verify.choices[0].message.content = '{"truth_score": 80, "supported_claims_pct": 50, "claims_checked": 1, "items": []}'
    mock_response_verify.choices[0].message.refusal = None
    mock_response_verify.usage.prompt_tokens = 100
    mock_response_verify.usage.completion_tokens = 50

    mock_client.chat.completions.create.side_effect = [mock_response_extract, mock_response_verify]

    result = fact_checking.generate_fact_check("input text", api_key="sk-test")

    assert result.truth_score == 80
    assert mock_client.chat.completions.create.call_count == 2

    # Verify verification model used was smart model
    extract_call_args = mock_client.chat.completions.create.call_args_list[0]
    assert (
        extract_call_args.kwargs["max_completion_tokens"]
        == config.settings.max_llm_output_tokens_extraction
    )
    verify_call_args = mock_client.chat.completions.create.call_args_list[1]
    assert verify_call_args.kwargs["model"] == config.settings.factcheck_llm_model


def test_paid_fact_check_invalid_provider_output_refunds_instead_of_finalizing(
    mock_client: MagicMock,
) -> None:
    # REGRESSION: unusable paid provider output must preserve operator cost
    # evidence while refunding the customer's reserved credits.
    mock_client.chat.completions.create.side_effect = [
        _completion_response(
            '{"claims": ["claim 1"]}',
            prompt_tokens=10,
            completion_tokens=5,
        ),
        _completion_response(
            "not-json",
            prompt_tokens=20,
            completion_tokens=7,
        ),
    ]
    ledger_store = MagicMock()
    reservation = _paid_reservation(action="fact_check")

    with pytest.raises(ValueError, match="Failed to generate fact check"):
        fact_checking.generate_fact_check(
            "input text",
            api_key="sk-test",
            ledger_store=ledger_store,
            charge_reservation=reservation,
        )

    ledger_store.mark_dispatched.assert_called_once_with(reservation)
    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_called_once()
    assert ledger_store.fail.call_args.args == (reservation,)
    assert ledger_store.fail.call_args.kwargs["status"] == "failed"
    assert ledger_store.fail.call_args.kwargs["actual_cost_usd"] > 0
    assert ledger_store.fail.call_args.kwargs["units"]["total_tokens"] == 42


def test_paid_fact_check_persists_validated_replay_before_response(
    mock_client: MagicMock,
) -> None:
    mock_client.chat.completions.create.return_value = _completion_response(
        '{"claims": []}',
        prompt_tokens=10,
        completion_tokens=5,
    )
    ledger_store = MagicMock()
    ledger_store.mark_dispatched.return_value = True
    reservation = _paid_reservation(action="fact_check")

    result = fact_checking.generate_fact_check(
        "input text",
        api_key="sk-test",
        ledger_store=ledger_store,
        charge_reservation=reservation,
    )

    assert result.truth_score == 100
    replay = ledger_store.finalize.call_args.kwargs["result"]
    assert replay == {
        "items": [],
        "truth_score": 100,
        "supported_claims_pct": 100,
        "claims_checked": 0,
    }


@pytest.mark.parametrize(
    ("content", "refusal"),
    [
        ("", None),
        ("{}", None),
        ('{"unrelated": []}', None),
        ('{"claims": null}', None),
        ('{"claims": ["   "]}', None),
        ('{"claims": [42]}', None),
        (json.dumps({"claims": ["x" * 2_001]}), None),
        (json.dumps({"claims": ["claim"] * 101}), None),
        ('{"claims": []}', "I cannot process this request."),
    ],
    ids=[
        "empty-content",
        "empty-object",
        "missing-claims",
        "null-claims",
        "blank-claim",
        "non-string-claim",
        "oversized-claim",
        "too-many-claims",
        "provider-refusal",
    ],
)
def test_paid_fact_check_invalid_extraction_refunds_before_short_circuit(
    mock_client: MagicMock,
    content: str,
    refusal: str | None,
) -> None:
    # REGRESSION: malformed or refused extraction output was treated as an
    # honest empty claim list, so the paid flow finalized instead of refunding.
    response = _completion_response(
        content,
        prompt_tokens=10,
        completion_tokens=5,
    )
    response.choices[0].message.refusal = refusal
    mock_client.chat.completions.create.return_value = response
    ledger_store = MagicMock()
    ledger_store.mark_dispatched.return_value = True
    reservation = _paid_reservation(action="fact_check")

    with pytest.raises(
        ValueError,
        match="Fact-check extraction failed after provider dispatch",
    ):
        fact_checking.generate_fact_check(
            "input text",
            api_key="sk-test",
            ledger_store=ledger_store,
            charge_reservation=reservation,
        )

    assert mock_client.chat.completions.create.call_count == 1
    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_called_once()
    assert ledger_store.fail.call_args.args == (reservation,)
    assert ledger_store.fail.call_args.kwargs["status"] == "failed"


def test_paid_fact_check_duplicate_dispatch_never_calls_provider(
    mock_client: MagicMock,
) -> None:
    ledger_store = MagicMock()
    ledger_store.mark_dispatched.return_value = False
    reservation = _paid_reservation(action="fact_check")

    with pytest.raises(ProviderDispatchAlreadyClaimedError):
        fact_checking.generate_fact_check(
            "input text",
            api_key="sk-test",
            ledger_store=ledger_store,
            charge_reservation=reservation,
        )

    mock_client.chat.completions.create.assert_not_called()
    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_not_called()


def test_paid_fact_check_replays_finalized_result_without_provider_call(
    mock_client: MagicMock,
) -> None:
    ledger_store = MagicMock()
    ledger_store.mark_dispatched.return_value = False
    ledger_store.get_finalized_result.return_value = {
        "truth_score": 91,
        "supported_claims_pct": 87,
        "claims_checked": 3,
        "items": [],
    }
    reservation = _paid_reservation(action="fact_check")

    result = fact_checking.generate_fact_check(
        "input text",
        ledger_store=ledger_store,
        charge_reservation=reservation,
    )

    assert result.truth_score == 91
    ledger_store.get_finalized_result.assert_called_once_with(reservation)
    mock_client.chat.completions.create.assert_not_called()
    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_not_called()


def test_paid_fact_check_validates_response_before_finalizing(
    mock_client: MagicMock,
) -> None:
    mock_client.chat.completions.create.side_effect = [
        _completion_response(
            '{"claims": ["claim 1"]}',
            prompt_tokens=10,
            completion_tokens=5,
        ),
        _completion_response(
            (
                '{"truth_score": {"invalid": true}, '
                '"supported_claims_pct": 50, "claims_checked": 1, '
                '"items": []}'
            ),
            prompt_tokens=20,
            completion_tokens=7,
        ),
    ]
    ledger_store = MagicMock()
    reservation = _paid_reservation(action="fact_check")

    with pytest.raises(ValueError, match="Failed to generate fact check"):
        fact_checking.generate_fact_check(
            "input text",
            api_key="sk-test",
            ledger_store=ledger_store,
            charge_reservation=reservation,
        )

    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_called_once()


def test_social_copy_truncates_input(mock_client):
    """Verify input is truncated to MAX_LLM_INPUT_CHARS."""
    long_text = "a" * (config.settings.max_llm_input_chars + 1000)

    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"title": "t", "description": "d", "hashtags": []}'
    mock_response.choices[0].message.refusal = None
    mock_response.usage.prompt_tokens = 200
    mock_response.usage.completion_tokens = 100
    mock_response.usage.total_tokens = 300

    mock_client.chat.completions.create.return_value = mock_response

    social_intelligence.build_social_copy_llm(long_text, api_key="sk-test")

    # Check that the sent message content length is truncated
    call_args = mock_client.chat.completions.create.call_args
    sent_messages = call_args.kwargs["messages"]
    user_content = sent_messages[1]["content"]

    assert len(user_content) <= config.settings.max_llm_input_chars
    assert len(user_content) < len(long_text)


def test_paid_social_copy_invalid_provider_output_refunds_and_raises(
    mock_client: MagicMock,
) -> None:
    # REGRESSION: an invalid paid provider response must refund and fail closed;
    # returning deterministic copy would misrepresent local output as paid AI.
    mock_client.chat.completions.create.return_value = _completion_response(
        "not-json",
        prompt_tokens=12,
        completion_tokens=4,
    )
    ledger_store = MagicMock()
    reservation = _paid_reservation(action="social_copy")

    with pytest.raises(ValueError, match="valid paid social copy"):
        social_intelligence.build_social_copy_llm(
            "input transcript",
            api_key="sk-test",
            ledger_store=ledger_store,
            charge_reservation=reservation,
        )

    ledger_store.mark_dispatched.assert_called_once_with(reservation)
    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_called_once()
    assert ledger_store.fail.call_args.args == (reservation,)
    assert ledger_store.fail.call_args.kwargs["status"] == "failed"
    assert ledger_store.fail.call_args.kwargs["actual_cost_usd"] > 0
    assert ledger_store.fail.call_args.kwargs["units"]["total_tokens"] == 16
    assert ledger_store.fail.call_args.kwargs["units"]["failed"] is True


def test_paid_social_copy_semantically_invalid_output_never_finalizes(
    mock_client: MagicMock,
) -> None:
    # REGRESSION: JSON with the right keys but invalid customer-facing content
    # (blank text and a malformed hashtag) used to be accepted and charged.
    mock_client.chat.completions.create.return_value = _completion_response(
        (
            '{"title_el": "   ", "title_en": "Title", '
            '"description_el": "Περιγραφή", '
            '"description_en": "Description", '
            '"hashtags": ["not-a-hashtag"]}'
        ),
        prompt_tokens=12,
        completion_tokens=4,
    )
    ledger_store = MagicMock()
    reservation = _paid_reservation(action="social_copy")

    with pytest.raises(ValueError, match="valid paid social copy"):
        social_intelligence.build_social_copy_llm(
            "input transcript",
            api_key="sk-test",
            ledger_store=ledger_store,
            charge_reservation=reservation,
        )

    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_called_once()


def test_paid_fact_check_semantically_invalid_output_never_finalizes(
    mock_client: MagicMock,
) -> None:
    # REGRESSION: a provider cannot report an error while claiming it checked
    # zero claims; cross-field invalid output must be rejected before charging.
    mock_client.chat.completions.create.side_effect = [
        _completion_response(
            '{"claims": ["claim 1"]}',
            prompt_tokens=10,
            completion_tokens=5,
        ),
        _completion_response(
            (
                '{"truth_score": 75, "supported_claims_pct": 50, '
                '"claims_checked": 0, "items": [{'
                '"mistake_el": "Λάθος", "mistake_en": "Wrong", '
                '"correction_el": "Σωστό", "correction_en": "Correct", '
                '"explanation_el": "Εξήγηση", '
                '"explanation_en": "Explanation", '
                '"severity": "major", "confidence": 90, '
                '"real_life_example_el": "Παράδειγμα", '
                '"real_life_example_en": "Example", '
                '"scientific_evidence_el": "Τεκμήριο", '
                '"scientific_evidence_en": "Evidence"}]}'
            ),
            prompt_tokens=20,
            completion_tokens=7,
        ),
    ]
    ledger_store = MagicMock()
    reservation = _paid_reservation(action="fact_check")

    with pytest.raises(ValueError, match="Failed to generate fact check"):
        fact_checking.generate_fact_check(
            "input transcript",
            api_key="sk-test",
            ledger_store=ledger_store,
            charge_reservation=reservation,
        )

    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_called_once()


def test_paid_social_copy_persists_validated_replay_before_response(
    mock_client: MagicMock,
) -> None:
    mock_client.chat.completions.create.return_value = (
        _completion_response(
            (
                '{"title_el": "Τίτλος", "title_en": "Title", '
                '"description_el": "Περιγραφή", '
                '"description_en": "Description", '
                '"hashtags": ["#gsubs"]}'
            ),
            prompt_tokens=12,
            completion_tokens=4,
        )
    )
    ledger_store = MagicMock()
    ledger_store.mark_dispatched.return_value = True
    reservation = _paid_reservation(action="social_copy")

    result = social_intelligence.build_social_copy_llm(
        "input transcript",
        api_key="sk-test",
        ledger_store=ledger_store,
        charge_reservation=reservation,
    )

    assert result.generic.title_el == "Τίτλος"
    replay = ledger_store.finalize.call_args.kwargs["result"]
    assert replay["description_en"] == "Description"
    assert replay["hashtags"] == ["#gsubs"]


def test_paid_social_copy_duplicate_dispatch_never_calls_provider(
    mock_client: MagicMock,
) -> None:
    ledger_store = MagicMock()
    ledger_store.mark_dispatched.return_value = False
    reservation = _paid_reservation(action="social_copy")

    with pytest.raises(ProviderDispatchAlreadyClaimedError):
        social_intelligence.build_social_copy_llm(
            "input transcript",
            api_key="sk-test",
            ledger_store=ledger_store,
            charge_reservation=reservation,
        )

    mock_client.chat.completions.create.assert_not_called()
    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_not_called()


def test_paid_social_copy_replays_finalized_result_without_provider_call(
    mock_client: MagicMock,
) -> None:
    ledger_store = MagicMock()
    ledger_store.mark_dispatched.return_value = False
    ledger_store.get_finalized_result.return_value = {
        "title_el": "Τίτλος",
        "title_en": "Title",
        "description_el": "Περιγραφή",
        "description_en": "Description",
        "hashtags": ["#gsubs"],
    }
    reservation = _paid_reservation(action="social_copy")

    result = social_intelligence.build_social_copy_llm(
        "input transcript",
        ledger_store=ledger_store,
        charge_reservation=reservation,
    )

    assert result.generic.title_el == "Τίτλος"
    ledger_store.get_finalized_result.assert_called_once_with(reservation)
    mock_client.chat.completions.create.assert_not_called()
    ledger_store.finalize.assert_not_called()
    ledger_store.fail.assert_not_called()
