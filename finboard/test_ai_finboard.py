from dotenv import load_dotenv

load_dotenv()

from ai.relevance import analyze_message


message = """
삼성전자 HBM3E 12단 제품이 엔비디아의 품질 테스트를
통과한 것으로 알려짐. 관련 반도체 장비주 관심.
"""


result = analyze_message(message)


print("\nFULL RESULT:")
print(result)

print("\n--- ANALYSIS ---")

print("Relevant:", result.relevant)
print("Score:", result.relevance_score)
print("Category:", result.category)
print("Event type:", result.event_type)
print("Information status:", result.information_status)
print("Needs review:", result.needs_review)

print("\nEntities:")

for entity in result.entities:
    print(
        entity.mention,
        "->",
        entity.normalized_name,
        "|",
        entity.entity_type,
        "| ticker:",
        entity.ticker_candidate,
        "| exchange:",
        entity.exchange,
        "| confidence:",
        entity.ticker_confidence
    )