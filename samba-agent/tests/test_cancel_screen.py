"""소싱처 주문취소 화면 판정 — 실제 주문상세(개인정보 가림) fixture 로 `classify_screen` 을 고정한다.

fixture 는 앱 `page.get({})` 의 tree 전체(URL 줄 · INTERACTIVE ELEMENTS · PAGE TEXT)다. JS `<key>_order_cancel.js` 와
같은 규칙표(`SITE_RULES`)를 쓰므로, 여기서 고정한 found/items/state/buttons 가 곧 스크립트의 판정이다.
"""

import json
from pathlib import Path

import pytest

from samba_agent.ops.cancel_screen import (
    SITE_CONFIRM,
    SITE_KEYS,
    SITE_RULES,
    SITE_VERIFIED,
    classify_screen,
    deduction_increased,
    may_click,
)

FIX = Path(__file__).parent / 'fixtures' / 'order_cancel'
SCRIPTS = Path(__file__).parent.parent / 'site-scripts'


def _fixture(name: str) -> str:
    return (FIX / f'{name}.txt').read_text(encoding='utf-8')


# (fixture, key, 주문번호, 기대 login, found, items, state, buttons)
CASES = [
    ('musinsa_cancellable', 'musinsa', '202610281401230003', True, True, 1, 'cancellable', 1),
    ('musinsa_shipped', 'musinsa', '202610271702330004', True, True, 1, 'shipped', 0),
    ('musinsa_cancelled', 'musinsa', '202610222201170001', True, True, 1, 'already_cancelled', 0),
    ('musinsa_multi', 'musinsa', '202610231522280001', True, True, 3, 'shipped', 0),
    ('fashionplus_cancellable', 'fashionplus', '142874265', True, True, 1, 'cancellable', 1),
    ('fashionplus_shipped', 'fashionplus', '142844116', True, True, 1, 'shipped', 0),
    ('fashionplus_cancelled', 'fashionplus', '142799733', True, True, 1, 'already_cancelled', 0),
    ('fashionplus_multi', 'fashionplus', '142690249', True, True, 2, 'shipped', 0),
    ('abc_login', 'abc', '2026102803957', False, False, 0, 'unknown', 0),
    ('lotteon_cancellable', 'lotteon', '2026102715291305', True, True, 1, 'cancellable', 1),
    ('lotteon_shipped', 'lotteon', '2026102615016205', True, True, 1, 'shipped', 0),
    ('lotteon_cancelled', 'lotteon', '2026101411100934', True, True, 1, 'already_cancelled', 0),
    ('lotteon_multi', 'lotteon', '2026102314077420', True, True, 2, 'shipped', 0),
    # GS샵: 로그인된 프로필이 없어 상세 화면을 못 봤다 — 로그인 화면만 고정(login False → 로봇은 사람에게)
    ('gsshop_login', 'gsshop', '3479617427', False, False, 0, 'unknown', 0),
    ('thehyundai_shipped', 'thehyundai', '261023002632141', True, True, 1, 'shipped', 0),
    # 마켓에서는 취소된 주문이지만 더현대 쪽은 배송완료(수량 2개 1행) — items 는 수량이 아니라 행 수
    ('thehyundai_delivered', 'thehyundai', '260827001846595', True, True, 1, 'shipped', 0),
    ('thehyundai_login', 'thehyundai', '261023002632141', False, False, 0, 'unknown', 0),
]


def _available() -> list[tuple[str, str, str, bool, bool, int, str, int]]:
    return [c for c in CASES if (FIX / f'{c[0]}.txt').exists()]


@pytest.mark.parametrize('case', _available(), ids=lambda c: c[0])
def test_fixture_판정(case: tuple[str, str, str, bool, bool, int, str, int]) -> None:
    name, key, no, login, found, items, state, buttons = case
    out = classify_screen(key, _fixture(name), no)
    assert (out['login'], out['found'], out['items'], out['state'], out['buttons']) == (
        login,
        found,
        items,
        state,
        buttons,
    )


@pytest.mark.parametrize('case', _available(), ids=lambda c: c[0])
def test_다른_주문번호면_found_false(case: tuple[str, str, str, bool, bool, int, str, int]) -> None:
    name, key, no, *_ = case
    other = no[:-1] + ('1' if no[-1] != '1' else '2')
    out = classify_screen(key, _fixture(name), other)
    assert out['found'] is False


def test_주문번호_부분일치는_found_아님() -> None:
    # 화면에 2026102812345 가 있고 대상이 그 안의 부분 문자열이면 찾은 게 아니다(영숫자 경계 토큰 일치)
    text = 'URL: https://x/\nINTERACTIVE ELEMENTS:\n\nPAGE TEXT:\n로그아웃 주문번호 2026102812345 주문 상품 1개 결제 완료'
    assert classify_screen('musinsa', text, '20261028123').get('found') is False
    assert classify_screen('musinsa', text, '2026102812345').get('found') is True


def test_빈_화면은_unknown() -> None:
    out = classify_screen('musinsa', '', '202610281401230003')
    assert out['found'] is False
    assert out['state'] == 'unknown'
    assert out['buttons'] == 0


def test_취소_버튼은_정확한_글자만_센다() -> None:
    # '주문 취소' 는 세고 '주문 취소 안내'·'취소 상세' 는 세지 않는다. button+clickable 중복은 1개
    text = (
        'URL: https://www.musinsa.com/order/order-detail/1\nINTERACTIVE ELEMENTS:\n'
        '[1] button "주문 취소"\n[2] clickable "주문 취소"\n[3] button "주문 취소 안내"\n[4] button "취소 상세"\n'
        '\nPAGE TEXT:\n로그아웃 주문번호 202610281401230003 주문 상품 1개 결제 완료 주문 취소'
    )
    out = classify_screen('musinsa', text, '202610281401230003')
    assert out['buttons'] == 1
    assert out['state'] == 'cancellable'


def test_모르는_사이트는_unknown() -> None:
    out = classify_screen('nosuch', 'PAGE TEXT:\n주문번호 1', '1')
    assert out['state'] == 'unknown'
    assert out['buttons'] == 0


def test_규칙표는_6사이트() -> None:
    assert set(SITE_KEYS) == {'musinsa', 'lotteon', 'abc', 'fashionplus', 'gsshop', 'thehyundai'}
    for key in SITE_KEYS:
        r = SITE_RULES[key]
        assert r['buttons'], (
            key
        )  # 취소 버튼 글자 목록은 비어 있으면 안 된다(없으면 어떤 화면도 안 누른다)


def test_검증된_사이트는_무신사_롯데온뿐() -> None:
    assert {k for k, v in SITE_VERIFIED.items() if v} == {'musinsa', 'lotteon'}
    assert set(SITE_VERIFIED) == set(SITE_KEYS)


def test_미검증_사이트는_취소_가능_화면이어도_누르지_않는다() -> None:
    screen = {'login': True, 'found': True, 'items': 1, 'state': 'cancellable', 'buttons': 1}
    assert may_click('musinsa', screen) is True
    for key in ('abc', 'fashionplus', 'gsshop', 'thehyundai'):
        assert may_click(key, screen) is False, key
    # 검증 사이트도 조건 하나라도 빠지면 안 누른다
    for bad in (
        {'items': 2},
        {'buttons': 0},
        {'buttons': 2},
        {'state': 'shipped'},
        {'found': False},
        {'login': False},
    ):
        assert may_click('musinsa', {**screen, **bad}) is False, bad


def test_확인_버튼_후보에_첫_버튼_글자와_일반_글자가_없다() -> None:
    for key in SITE_KEYS:
        for label in SITE_CONFIRM[key]:
            assert label not in SITE_RULES[key]['buttons'], (key, label)  # type: ignore[operator]
            assert label not in ('다음', '확인', '취소'), (key, label)


def _js_const(code: str, name: str) -> object:
    line = next(ln for ln in code.splitlines() if ln.startswith(f'const {name} = '))
    return json.loads(line[len(f'const {name} = ') :])


@pytest.mark.parametrize('key', SITE_KEYS)
def test_JS_규칙표가_파이썬과_같다(key: str) -> None:
    code = (SCRIPTS / f'{key}_order_cancel.js').read_text(encoding='utf-8')
    rules = {
        k: SITE_RULES[key][k]
        for k in (
            'segment',
            'items',
            'buttons',
            'shipped',
            'already_cancelled',
            'cancel_pending',
            'cancellable',
        )
    }
    rules['segment'] = list(rules['segment'])  # type: ignore[arg-type]
    assert _js_const(code, 'RULES') == rules
    assert _js_const(code, 'CONFIRM') == SITE_CONFIRM[key]
    assert _js_const(code, 'VERIFIED') is SITE_VERIFIED[key]
    assert code.index('const VERIFIED') < code.index('page.click(')  # 가드가 클릭보다 앞
    assert 'if (!VERIFIED) return done(' in code


def test_공제_글자는_클릭_전보다_늘었을_때만_잡는다() -> None:
    before = '주문 상세 취소 수수료 안내 차감 없음 주문 취소'
    assert deduction_increased(before, before) is False
    # 전부터 있던 '차감' 은 그대로, 새로 '공제' 가 생기면 잡는다
    assert deduction_increased(before, before + ' 환불 시 공제 금액 3,000원') is True
    # 전부터 있던 낱말이 한 번 더 나와도(횟수 증가) 잡는다
    assert deduction_increased(before, before + ' 취소 수수료 2,500원') is True
    # 글자가 줄어드는 건 공제가 아니다
    assert deduction_increased(before, '주문 상세') is False
    assert deduction_increased('', '') is False
