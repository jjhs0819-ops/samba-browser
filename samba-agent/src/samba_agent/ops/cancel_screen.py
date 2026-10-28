"""소싱처 주문상세 화면 판정 — `<key>_order_cancel.js` 와 같은 규칙으로 found/items/state/buttons 를 낸다.

JS 는 운영 브라우저에서 이 판정으로 누를지 말지를 정하고, 파이썬은 같은 규칙을 fixture(실제 화면, 개인정보 가림)로
고정한다. 규칙표 `SITE_RULES` 의 값은 JS 안의 RULES 와 글자 그대로 같아야 한다 — 바꿀 때 둘 다 바꾼다.

입력 `text` 는 앱 `page.get({})` 의 tree 전체(`URL:` 줄 · INTERACTIVE ELEMENTS · `PAGE TEXT:`)다.

판정 규칙(2026-10-28 운영 화면 실측 — 사이트별 실측 범위는 규칙표 주석):
- login   : 주소가 /login 이거나 화면에 로그인 폼('아이디 저장')이 있으면 False
- found   : 주문번호가 PAGE TEXT 에 영숫자 경계 토큰으로 있다(부분 일치 아님)
- items   : 상품행 수(사이트별 정규식, 수량이 아니라 행)
- state   : 상품 구간 안의 상태 글자. 우선순위 shipped > already_cancelled > cancel_pending > cancellable > unknown
            (하나라도 출고·배송 흔적이 있으면 전체 취소를 못 하므로 shipped 가 먼저다)
- buttons : 정확한 글자의 취소 버튼(button·link) 수. button+clickable 중복은 한 번만 센다
"""

from __future__ import annotations

import re

State = str  # cancellable | shipped | already_cancelled | cancel_pending | unknown

# 사이트별 규칙 — JS RULES 와 동일 값. '미확인' 표시는 2026-10-28 실측에서 그 화면을 못 본 것(보수적으로 둔다)
SITE_RULES: dict[str, dict[str, object]] = {
    # 실측: 결제 완료(주문 취소 버튼)·배송중·배송 완료(3상품)·취소 완료. 확인창 문구 미확인
    'musinsa': {
        'segment': (r'주문 상품 \d+개', r'결제 정보'),
        'items': r'주문 상품 (\d+)개',
        'buttons': ['주문 취소'],
        'shipped': [
            '배송 완료',
            '배송중',
            '배송 중',
            '배송 준비 중',
            '상품 준비 중',
            '구매 확정',
            '반품',
            '교환',
            '환불 완료',
        ],
        'already_cancelled': ['취소 완료'],
        'cancel_pending': ['취소 요청', '취소 접수'],
        'cancellable': ['결제 완료'],
    },
    # 실측: 상품준비중(취소하기 버튼 — 롯데온은 상품준비중도 즉시 취소 가능)·배송진행중·배송완료(2상품)·취소완료. 확인창 미확인
    'lotteon': {
        'segment': (r'주문 상세 \d{4}\.\d{2}\.\d{2}', r'배송정보'),
        'items': r'수량 \d+',
        'buttons': ['취소하기'],
        'shipped': ['배송진행중', '배송중', '배송완료', '구매확정', '반품하기', '교환하기', '출고'],
        'already_cancelled': ['취소완료'],
        'cancel_pending': ['취소요청', '취소접수', '취소신청'],
        'cancellable': ['결제완료', '상품준비중'],
    },
    # 미확인: 2026-10-28 구매 프로필(jjhs0819)이 로그인 풀려 상세를 못 봤다. 상태 글자는 abc_order_detail 의 목록, 버튼 글자는 추정
    'abc': {
        'segment': (r'', r'결제 정보'),
        'items': r'(?:입금대기|결제완료|상품준비중|배송준비중|배송중|배송완료|수령완료|취소완료|취소접수)',
        'buttons': ['주문취소', '주문 취소'],
        'shipped': [
            '상품준비중',
            '배송준비중',
            '배송중',
            '배송완료',
            '수령완료',
            '픽업준비완료',
            '구매확정',
            '교환접수',
            '반품접수',
            '반품완료',
        ],
        'already_cancelled': ['취소완료'],
        'cancel_pending': ['취소접수', '취소요청'],
        'cancellable': ['결제완료'],
    },
    # 실측: 결제완료('주문 취소' 링크 → 상품 선택 화면)·배송중·배송완료(2상품)·환불완료. 사유·확인 화면 미확인
    'fashionplus': {
        'segment': (r'상품 정보', r'최종 결제금액'),
        'items': r'\s\d+개\s',
        'buttons': ['주문 취소'],
        'shipped': [
            '배송준비중',
            '상품준비중',
            '배송중',
            '배송완료',
            '구매확정',
            '반품 신청',
            '교환 신청',
            '수취 확인',
        ],
        'already_cancelled': ['취소완료', '환불완료'],
        'cancel_pending': ['취소신청', '취소접수', '취소요청'],
        'cancellable': ['결제완료'],
    },
    # 미확인: 로그인된 프로필이 없어(키마스터 계정 없음) 상세를 못 봤다. 전부 추정 — 자동취소 대상에서 뺄 것
    'gsshop': {
        'segment': (r'', r'결제정보|결제 정보'),
        'items': r'(?:주문접수|결제완료|상품준비중|배송준비중|배송중|배송완료|취소완료|취소접수)',
        'buttons': ['주문취소', '주문 취소'],
        'shipped': ['상품준비중', '배송준비중', '배송중', '배송완료', '구매확정', '반품', '교환'],
        'already_cancelled': ['취소완료'],
        'cancel_pending': ['취소접수', '취소요청', '취소신청'],
        'cancellable': ['결제완료', '주문접수'],
    },
    # 실측(profile buy-1): 배송완료 2건뿐. 결제완료·취소 화면과 버튼 글자 미확인 — 자동취소 대상에서 뺄 것
    'thehyundai': {
        'segment': (r'주문상품', r'배송지'),
        'items': r'원\s*\d+개',
        'buttons': ['주문취소', '주문 취소'],
        'shipped': ['배송완료', '배송중', '배송준비중', '상품준비중', '구매확정', '반품', '교환'],
        'already_cancelled': ['취소완료'],
        'cancel_pending': ['취소접수', '취소요청', '취소신청'],
        'cancellable': ['결제완료', '주문완료', '주문접수'],
    },
}
SITE_KEYS: tuple[str, ...] = tuple(SITE_RULES)
# 공제·수수료 글자 — 첫 클릭 뒤 전체 본문에서 이 글자의 개수가 클릭 전보다 늘면 더 가지 않는다(리뷰 2차 판정 B)
DEDUCTION_PATTERNS: tuple[str, ...] = ('공제', '취소 수수료', '위약금', '차감')
# 실측으로 취소 가능 화면·버튼 글자를 확인한 사이트만 True — False 면 mode=cancel 이어도 절대 누르지 않는다(리뷰 1차 판정 1)
SITE_VERIFIED: dict[str, bool] = {
    'musinsa': True,
    'lotteon': True,
    'abc': False,
    'fashionplus': False,
    'gsshop': False,
    'thehyundai': False,
}
# 첫 클릭 뒤 '새로 나타난' 요소 중 정확한 글자로 1개일 때만 누르는 최종 확인 버튼 후보(전부 미확인 추정).
# 첫 버튼 자신의 글자('주문 취소'·'취소하기')와 '다음' 같은 일반 글자는 넣지 않는다(리뷰 1차 판정 2)
SITE_CONFIRM: dict[str, list[str]] = {
    'musinsa': ['취소 신청', '신청하기', '취소 요청'],
    'lotteon': ['취소 신청', '취소신청', '신청하기'],
    'abc': ['취소신청', '취소 신청', '신청하기'],
    'fashionplus': ['취소 신청', '취소신청', '신청하기'],
    'gsshop': ['취소신청', '취소 신청', '신청하기'],
    'thehyundai': ['취소신청', '취소 신청', '신청하기'],
}
_STATE_ORDER: tuple[str, ...] = ('shipped', 'already_cancelled', 'cancel_pending', 'cancellable')
_ELEMENT = re.compile(r'^\[\d+\] (button|link|clickable) "([^"]*)"', re.MULTILINE)
_LOGIN_FORM = re.compile(r'아이디 저장|로그인하시면')


def _split(text: str) -> tuple[str, str, str]:
    """tree → (url, 요소 부분, PAGE TEXT 부분). PAGE TEXT 가 없으면 전체를 본문으로 본다."""
    url = (re.match(r'URL: (\S+)', text) or [None, ''])[1] or ''
    head, sep, body = text.partition('PAGE TEXT')
    if not sep:
        return url, '', re.sub(r'\s+', ' ', text)
    return url, head, re.sub(r'\s+', ' ', body.lstrip(':'))


def order_no_found(text: str, no: str) -> bool:
    """영숫자 경계 토큰 일치 — source_cancel.order_no_token_match 와 같은 규칙."""
    if not no:
        return False
    return re.search(r'(?<![0-9A-Za-z])' + re.escape(no) + r'(?![0-9A-Za-z])', text) is not None


def count_buttons(elements: str, labels: list[str]) -> int:
    """정확히 같은 글자의 button·link 수. 없으면 clickable 만 센다(앱이 한 버튼을 button+clickable 로 두 번 보여 준다)."""
    strong = 0
    weak = 0
    for role, label in _ELEMENT.findall(elements):
        if label.strip() not in labels:
            continue
        if role == 'clickable':
            weak += 1
        else:
            strong += 1
    return strong or weak


def count_items(pattern: str, segment: str) -> int:
    """상품행 수. 정규식에 그룹이 있으면 첫 일치의 숫자('주문 상품 N개'), 없으면 일치 횟수(행마다 한 번 나오는 글자)."""
    rx = re.compile(pattern)
    if rx.groups:
        m = rx.search(segment)
        return int(m.group(1)) if m else 0
    return len(rx.findall(segment))


def deduction_counts(text: str) -> list[int]:
    """공제 글자별 등장 횟수(JS dedCounts 와 같다)."""
    # 정규식이 아니라 글자 그대로 센다(JS dedCounts 의 split 과 같다)
    return [text.count(p) for p in DEDUCTION_PATTERNS]


def deduction_increased(before: str, after: str) -> bool:
    """클릭 뒤 본문에서 공제 글자가 하나라도 늘었는가 — '취소 수수료' 처럼 전부터 있던 낱말은 늘지 않으면 무시한다."""
    return any(
        z > a for a, z in zip(deduction_counts(before), deduction_counts(after), strict=True)
    )


def may_click(key: str, screen: dict[str, object]) -> bool:
    """mode=cancel 에서 첫 취소 버튼을 눌러도 되는가 — JS 의 전체 가드와 같다(검증 사이트 · 로그인 · 주문번호 · 상품행 1 · cancellable · 버튼 1)."""
    return bool(
        SITE_VERIFIED.get(key)
        and screen.get('login')
        and screen.get('found')
        and screen.get('items') == 1
        and screen.get('state') == 'cancellable'
        and screen.get('buttons') == 1
    )


def classify_screen(key: str, text: str, no: str) -> dict[str, object]:
    """한 화면을 판정한다. 모르는 사이트·빈 화면은 unknown 으로."""
    url, elements, body = _split(text or '')
    rules = SITE_RULES.get(key)
    out: dict[str, object] = {
        'login': not (re.search(r'/login', url, re.IGNORECASE) or _LOGIN_FORM.search(body)),
        'found': order_no_found(body, no),
        'items': 0,
        'state': 'unknown',
        'buttons': 0,
    }
    if rules is None or not body:
        return out
    start_re, end_re = rules['segment']  # type: ignore[misc]
    seg = body
    if start_re:
        m = re.search(str(start_re), seg)
        if m:
            seg = seg[m.start() :]
    if end_re:
        m = re.search(str(end_re), seg)
        if m:
            seg = seg[: m.start()]
    out['items'] = count_items(str(rules['items']), seg)
    for state in _STATE_ORDER:
        if any(w in seg for w in rules[state]):  # type: ignore[operator]
            out['state'] = state
            break
    out['buttons'] = count_buttons(elements, list(rules['buttons']))  # type: ignore[arg-type]
    return out
