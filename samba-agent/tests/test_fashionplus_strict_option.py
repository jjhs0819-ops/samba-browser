"""패션플러스 옵션 정확 일치(2026-10-22) — 비슷한 글자·AI 짐작 없이 정확히 같은 옵션만 산다.

실주문(최근 120일 패션플러스 543건) 시뮬레이션에서 기존 규칙이 'C8' 주문에 남은 선택지 'C7' 을,
'FREE W8' 주문에 'FREE W7' 을 맞는 옵션으로 봤다. 주문서 되읽기 검사도 같은 규칙이라 그대로 결제될 수 있었다.
"""

import pytest

from samba_agent.agents.buyer import (
    BuyerAgent,
    matching_options,
    sold_out_option_matches,
    strict_matching_options,
    strict_option_key,
)
from samba_agent.agents.registry import Registry
from samba_agent.bridge.client import BridgeClient
from samba_agent.settings import DEFAULT_ROOT
from samba_agent.sources import Sources
from samba_agent.wave.client import WaveSourceOption, registered_source_option

URL = 'http://127.0.0.1:47811'


@pytest.fixture()
def buyer() -> BuyerAgent:
    reg = Registry.load(DEFAULT_ROOT)
    spec = reg['buyer.fashionplus']
    agent = BuyerAgent(
        spec,
        BridgeClient(URL, 'a' * 64, allowed=spec.tools, busy_wait_s=0.0),
        lambda p, m: None,  # type: ignore[arg-type,return-value]
    )
    agent.evidence = []

    def no_ai(*args: object, **kwargs: object) -> object:
        raise AssertionError('패션플러스는 옵션을 AI 로 짐작하지 않는다')

    agent.decide_once = no_ai  # type: ignore[method-assign]
    return agent


def test_패션플러스_행은_정확일치_직배_넥슨현대_원가실결제() -> None:
    fp = Sources.load(DEFAULT_ROOT).by_id('FashionPlus')
    assert fp is not None
    assert fp.strict_option is True
    assert fp.order_type == 'direct'
    assert fp.pay_provider == 'naver'
    assert fp.naverpay_cards == ['넥슨 현대카드']
    assert fp.paid_is_cost is True
    assert fp.customer_phone is False
    # 다른 소싱처는 그대로(기존 매칭)
    musinsa = Sources.load(DEFAULT_ROOT).by_id('MUSINSA')
    assert musinsa is not None and musinsa.strict_option is False


def test_기존_규칙은_한글자_다른_옵션을_맞춘다_정확일치는_안_맞춘다() -> None:
    # 실주문 412068~ 크록스: 남은 선택지가 C7 하나뿐인데 C8 주문
    assert matching_options(['BLUE BOLT(Z4KZ) C7'], 'BLUE BOLT(Z4KZ) C8')  # 기존 규칙의 함정
    assert strict_matching_options(['BLUE BOLT(Z4KZ) C7'], 'BLUE BOLT(Z4KZ) C8') == []
    # 프리사이즈 표기 묶음(FREE W6·W7·W8)
    assert matching_options(['FREE W7'], 'FREE W8')
    assert strict_matching_options(['FREE W6', 'FREE W7'], 'FREE W8') == []
    assert strict_matching_options(['FREE W6', 'FREE W7', 'FREE W8'], 'FREE W8') == ['FREE W8']


@pytest.mark.parametrize(
    ('options', 'wanted', 'expected'),
    [
        # 실주문 옵션 글자 ↔ 패션플러스 선택지
        (['블랙 M(28)', '블랙 S(27)', '블랙 XS(26)'], '블랙 S(27)', ['블랙 S(27)']),
        (['오트밀 베이지 100', '오트밀 베이지 95'], '옵션:오트밀 베이지 95', ['오트밀 베이지 95']),
        (['블랙 2XL', '블랙 3XL', '블랙 XL'], '블랙 XL', ['블랙 XL']),
        (['M5W7(240mm)', 'M6W8(250mm)'], 'M5W7(240mm)', ['M5W7(240mm)']),
        (
            ['1)BLACK(Z001) M4W6(230)', '1)BLACK(Z001) M5W7(240)'],
            '1)BLACK(Z001) M4W6(230)',
            ['1)BLACK(Z001) M4W6(230)'],
        ),
        (['01_705913-03:L .', '01_705913-03:M .'], '01_705913-03:M .', ['01_705913-03:M .']),
        (
            ['단일색상 JQ06s30／270', '단일색상 JQ06s30／275'],
            '단일색상 JQ06s30/275',
            ['단일색상 JQ06s30／275'],
        ),
        (['001 7', '001 9', '001 9.5'], '001 9.5', ['001 9.5']),
        # 없는 사이즈는 가까운 값으로 대신하지 않는다
        (['225', '230', '235'], '220', []),
        (['001 7', '001 9'], '001 9.5', []),
        (['1)WHITE(Z100) C11', '1)WHITE(Z100) C12'], '1)WHITE(Z100) J3', []),
        (['블랙 255', '블랙 265'], '블랙 260', []),
        # 품절 표시가 붙은 선택지는 사지 않는다
        (['블랙 255 [품절]', '블랙 260'], '블랙 255', []),
    ],
)
def test_정확일치_매칭(options: list[str], wanted: str, expected: list[str]) -> None:
    assert strict_matching_options(options, wanted) == expected


def test_정확일치_키는_표기차이만_무시한다() -> None:
    assert strict_option_key('옵션:BLK 96') == strict_option_key('BLK 96')
    assert strict_option_key('Off White XS(85)') == strict_option_key('off white xs 85')
    assert strict_option_key('C7') != strict_option_key('C8')
    assert strict_option_key('W6(230mm)') != strict_option_key('W6(230)')


def test_하네스_옵션매칭은_정확일치만_AI_안씀(buyer: BuyerAgent) -> None:
    assert buyer._match_options(['BLUE BOLT(Z4KZ) C7'], 'BLUE BOLT(Z4KZ) C8') == []
    assert buyer._match_options(['블랙 2XL', '블랙 XL'], '블랙 XL') == ['블랙 XL']


def test_주문서_되읽기도_정확일치만_통과(buyer: BuyerAgent) -> None:
    assert buyer._selected_matches('FREE W8', 'FREE W8')
    assert buyer._selected_matches('BLK 96', '옵션:BLK 96')
    assert not buyer._selected_matches('FREE W7', 'FREE W8')
    assert not buyer._selected_matches('BLUE BOLT(Z4KZ) C7', 'BLUE BOLT(Z4KZ) C8')
    assert not buyer._selected_matches('블랙 2XL', '블랙 XL')
    assert not buyer._selected_matches('', '블랙 XL')


def test_비슷한_옵션의_품절을_주문_옵션_품절로_확정하지_않는다() -> None:
    options = ['FREE W6', 'FREE W7 [품절]']
    assert sold_out_option_matches(options, 'FREE W8')  # 기존 규칙은 W7 품절을 W8 품절로 본다
    assert sold_out_option_matches(options, 'FREE W8', strict=True) == []
    assert sold_out_option_matches(options, 'FREE W7', strict=True) == ['FREE W7 [품절]']


def test_등록옵션_되짚기는_전각_빗금도_같게_본다() -> None:
    src = [
        WaveSourceOption(name='단일색상 JQ06s30／275'),
        WaveSourceOption(name='단일색상 JQ06s30／270'),
    ]
    assert registered_source_option('단일색상 JQ06s30/275', src) == '단일색상 JQ06s30／275'
