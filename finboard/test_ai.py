from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai.relevance import MessageAnalysis, analyze_message


def test_analyze_message_smoke():
    payload = MessageAnalysis(
        relevant=True,
        relevance_score=88,
        category="company_event",
        news_field="business_finance",
        event_type="production_update",
        information_status="reported",
        entities=[
            {
                "mention": "삼성전자",
                "normalized_name": "Samsung Electronics",
                "entity_type": "company",
                "ticker_candidate": "005930",
                "exchange": "KRX",
                "ticker_confidence": 95,
            }
        ],
        needs_review=False,
        summary_ko="삼성전자가 제품 품질 검증을 통과한 것으로 보도됐다.",
        summary_en="Samsung Electronics was reported to have passed a product quality test.",
        event_date_kst=None,
    )
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=MagicMock(return_value=SimpleNamespace(output_parsed=payload))
        )
    )

    with patch("ai.relevance.get_client", return_value=fake_client) as mock_get_client:
        result = analyze_message("삼성전자 HBM3E 12단 제품이 품질 테스트를 통과했다.")

    assert result == payload
    assert result.relevant is True
    assert result.entities[0].ticker_candidate == "005930"
    mock_get_client.assert_called_once()
    fake_client.responses.parse.assert_called_once()


if __name__ == "__main__":
    print("Running AI relevance smoke check...")
    test_analyze_message_smoke()
    print("OK")