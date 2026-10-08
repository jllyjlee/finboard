from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai.relevance import MessageAnalysis, analyze_message_with_usage


def test_analyze_message_with_usage_smoke():
    payload = MessageAnalysis(
        relevant=True,
        relevance_score=76,
        category="market",
        news_field="business_finance",
        event_type="price_movement",
        information_status="analysis",
        entities=[
            {
                "mention": "현대차",
                "normalized_name": "Hyundai Motor",
                "entity_type": "company",
                "ticker_candidate": None,
                "exchange": None,
                "ticker_confidence": 0,
            }
        ],
        needs_review=False,
        summary_ko="현대차가 시장에서 주목받고 있다는 분석이다.",
        summary_en="The analysis says Hyundai Motor is drawing market attention.",
        event_date_kst=None,
    )

    usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=40,
        total_tokens=160,
        input_tokens_details=SimpleNamespace(cached_tokens=25),
    )
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=MagicMock(return_value=SimpleNamespace(output_parsed=payload, usage=usage))
        )
    )

    with patch("ai.relevance.get_client", return_value=fake_client) as mock_get_client:
        result, usage_data = analyze_message_with_usage("현대차가 시장에서 주목받는다고 보도됐다.")

    assert result == payload
    assert usage_data["input_tokens"] == 120
    assert usage_data["cached_input_tokens"] == 25
    assert usage_data["output_tokens"] == 40
    assert usage_data["total_tokens"] == 160
    mock_get_client.assert_called_once()
    fake_client.responses.parse.assert_called_once()


if __name__ == "__main__":
    print("Running AI usage smoke check...")
    test_analyze_message_with_usage_smoke()
    print("OK")