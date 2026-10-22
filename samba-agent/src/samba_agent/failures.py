"""실패 사유 enum — 진단 표가 안정되도록 코드로 고정한다(스펙 §4.5 3단계)."""

from enum import StrEnum


class FailReason(StrEnum):
    """에이전트가 돌려줄 수 있는 실패 사유. 이 목록 밖의 값은 쓰지 않는다."""

    OUT_OF_STOCK = 'out_of_stock'  # 품절·옵션 없음
    MARGIN = 'margin'  # 마진 미달
    CARD_MISSING = 'card_missing'  # 지정 카드가 결제수단에 없음
    CAPTCHA = 'captcha'  # 캡차·2단계 인증 — 사람에게 넘긴다
    BRIDGE_DOWN = 'bridge_down'  # 앱 꺼짐·연결 실패·계속 busy
    PERMISSION_DENIED = 'permission_denied'  # 허용 목록 밖 도구·토큰 오류·키마스터 잠김
    DUPLICATE = 'duplicate'  # 이미 처리된 주문
    VERIFY_MISMATCH = 'verify_mismatch'  # 대조 불일치
    # 결제 진행 중 재시작·재진입 — 재결제를 막고 사람이 결제 여부를 확인해야 한다
    PAY_INTERRUPTED = 'pay_interrupted'
    # 승인 대기 중 구매가 만든 주문서 탭이 사라졌다(다음 주문 스냅샷이 닫음·재시작 정리) — 결제 전이라 다시 만들면 된다
    ORDER_FORM_GONE = 'order_form_gone'
    # 결제수단 규칙상 사람이 고를 일(폰 결제 할인이 더 크다 등) — 결제하지 않고 사유를 남긴다
    PAY_RULE_STOP = 'pay_rule_stop'
    # 승인 뒤 주문서를 다시 만들었더니 원가가 올랐다(청구할인 한도 소진 등) — 결제 안 함, 새 원가로 승인카드를 다시 띄운다
    COST_CHANGED = 'cost_changed'
    # 무신사머니로 결제해야 하는데 잔액이 모자란다 — 충전은 사람 일, 결제하지 않고 알린다(2026-10-22)
    MONEY_INSUFFICIENT = 'money_insufficient'
    # 결제 직전 마켓 취소요청 확인 — 고객이 취소했다, 결제하지 않는다(삼바가 마켓 취소승인, 사용자 2026-10-23)
    MARKET_CANCELLED = 'market_cancelled'
    UNKNOWN = 'unknown'
