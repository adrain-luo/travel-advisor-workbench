"""Business planning vocabulary must not masquerade as a concrete tour offer."""
import pytest
from backend.background.relevance import decide


@pytest.mark.parametrize('text', [
    '业务方向：开发旅行社软件平台。功能包括旅游线路、团期报价、出发计划和客户需求管理。',
    '创业项目商业计划：软件服务平台，提供自动化旅游报价和行程管理功能，开发费用5000元。',
    'Business plan: software service platform for itinerary and departure features. Price 5000 USD.',
    '需求：AI 整理旅游行程和团期报价，AI 理解客户需求与出发安排。',
    'AI 软件：根据需求生成行程，查询出发安排，报价功能和取消提醒。需求由 AI 分析。',
    'AI理解需求，AI整理旅游行程和出发安排，AI生成需求清单。',
])
def test_planning_is_not_a_travel_product(text):
    row = {'event_key': 'planning', 'text': text, 'attachments': []}
    assert decide(row)['outcome'] == 'SKIP_IRRELEVANT'
    row['attachments'] = [{'sha256': 'a' * 64, 'type': 'image'}]
    row['text'] = ''
    evidence = {'event_key': 'planning', 'images': [{'sha256': 'a' * 64, 'state': 'RECOGNIZED',
        'trusted_for_rules': True, 'text': text}], 'status': 'RECOGNIZED', 'metrics': {}}
    assert decide(row, inspection=evidence)['outcome'] == 'SKIP_IRRELEVANT'


@pytest.mark.parametrize('text', [
    '通过软件平台报名：大连双飞5日游，6月20日出发，含酒店住宿。',
    '旅行社管理系统导出的旅游产品：北京3天2晚，入住四星酒店，含早餐。',
    '旅游线路：第一天：北京故宫。第二天：长城。无需软件服务。',
])
def test_concrete_offer_remains_relevant_even_with_software_word(text):
    assert decide({'event_key': 'offer', 'text': text})['outcome'] == 'KEEP_PRODUCT_RELEVANT'


def test_partial_planning_ocr_does_not_discard_unknown_second_image():
    row = {'event_key': 'mixed', 'text': '', 'attachments': [{'sha256': 'a' * 64}, {'sha256': 'b' * 64}]}
    evidence = {'event_key': 'mixed', 'images': [{'sha256': 'a' * 64, 'state': 'RECOGNIZED', 'trusted_for_rules': True,
        'text': '业务规划：软件平台开发，功能包括团期报价和旅游线路。'}], 'status': 'PARTIAL', 'metrics': {}}
    assert decide(row, inspection=evidence)['outcome'] == 'PENDING_RELEVANCE'
