"""소싱처 자동취소 실행기 — 삼바가 내준 취소 행을 소싱처 주문 화면에서 누르고 결과를 회신한다.

흐름(5분 주기 스레드): 삼바 `GET /robot-cancels`(호출이 곧 선점) → 건마다 `<key>_order_cancel`
스크립트(mode=check 는 읽기만, cancel 은 누르고 되읽기) → `decide()` 순수 판정 → `POST …/result`
→ 반영된 회신(done·wait_confirm)에만 텔레그램 카드 1통.

원칙("확신 없으면 누르지 않는다"): 묶음(같은 발주번호 주문 2건 이상·화면 상품행 2개 이상)은 안 누른다.
mode=check(접수 재확인·claimed 방치 재선점)는 상태만 읽고 **절대 누르지 않는다** — 다시 취소 가능 상태면
failed 로 회신해 삼바가 30분 뒤 cancel 모드로 다시 내주거나(attempts<2) 사람에게 넘긴다.
한 사이클에 한 건당 스크립트 호출은 1번이다. 마켓 취소승인 API 는 여기서 절대 부르지 않는다.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from samba_agent.sources import Source, Sources, default_sources
from samba_agent.wave.client import RobotCancelItem, WaveError

if TYPE_CHECKING:
    from samba_agent.ops.telegram import Level, TelegramNotifier
    from samba_agent.wave.client import WaveClient

_log = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 300.0
DEFAULT_LIMIT = 20
# 스크립트 args.reason_text 로 넘기는 취소 사유 글자. 사이트마다 선택지가 달라 스크립트(Task 6)가
# 자기 사이트의 가장 가까운 항목(무신사 '단순 변심', ABC '고객 변심' 식)으로 옮겨 고른다 — 그대로 찾지 않는다
DEFAULT_REASON_TEXT = '단순 변심'
# 텔레그램을 보내는 회신 state. retry(30분 뒤 다시)·pending·skipped·claimed(반영 안 됨)는 조용히
_ANNOUNCE_STATES = frozenset({'done', 'wait_confirm'})
# 접수(accepted) 회신이 done 으로 닫히면 삼바가 72시간 만료로 failed 처리한 것 — 사람에게 넘긴다
EXPIRED_REASON = '취소 접수 후 72시간 확정 안 됨'

# outcome → (level, 결론, 할일). failed 의 결론은 사유를 붙인다
_CARDS: dict[str, tuple[Level, str, str]] = {
    'cancelled': ('ok', '소싱처 취소 완료', '마켓 취소승인 눌러주세요'),
    'already_cancelled': ('ok', '소싱처 취소 완료', '마켓 취소승인 눌러주세요'),
    'accepted': ('warn', '소싱처 취소 접수(판매자 확인 대기)', '확정되면 다시 알림'),
    'shipped': ('warn', '이미 발송돼 취소 못 함', '반품 처리 필요'),
    'bundle': ('warn', '묶음 주문이라 손대지 않음', '직접 확인'),
    'failed': ('bad', '자동취소 실패', '직접 취소'),
}


def card_for(outcome: str, reason: str = '') -> tuple[Level, str, str]:
    """텔레그램 문구표(설계서 표 그대로). failed 는 `자동취소 실패: {사유}`."""
    level, conclusion, todo = _CARDS.get(outcome, _CARDS['failed'])
    if outcome == 'failed':
        conclusion = f'{conclusion}: {reason or "사유 미상"}'
    return level, conclusion, todo


def order_no_token_match(text: str, no: str) -> bool:
    """화면 글자에 주문번호가 숫자 경계 토큰으로 정확히 있는가.

    `2026102812345` 안의 `02810` 같은 부분 문자열은 일치로 보지 않는다. 스크립트(Task 6)의 판정과
    같은 규칙을 파이썬 테스트로 고정하는 용도다.
    """
    no = str(no or '').strip()
    if not no or not text:
        return False
    return re.search(rf'(?<![0-9A-Za-z]){re.escape(no)}(?![0-9A-Za-z])', text) is not None


def resolve_profile(
    src: Source,
    account_username: str | None,
    keymaster_labels: list[str],
    ledger_account: str | None = None,
) -> str | None:
    """스크립트에 넘길 키마스터 프로필(계정 라벨).

    순서: (a) 교차검증 장부에 적힌 이 소싱주문의 구매 계정(발주 때 실제 쓴 키마스터 라벨 — crosscheck 의
    `_source_status` 도 이 값을 profile 로 쓴다) → (b) 삼바 주문계정 아이디가 알려진 라벨과 정확히 같으면 그 라벨
    → (c) `buy_accounts` 가 정확히 1개면 그 계정. 셋 다 아니면 None(→ failed `구매 계정을 정하지 못함`).
    """
    ledger = (ledger_account or '').strip()
    if ledger:
        return ledger
    username = (account_username or '').strip()
    if username and username in keymaster_labels:
        return username
    if len(src.buy_accounts) == 1:
        return src.buy_accounts[0]
    return None


def _flag(screen: dict[str, object], key: str) -> bool:
    return bool(screen.get(key))


def _int(screen: dict[str, object], key: str) -> int:
    try:
        return int(screen.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def decide(item: RobotCancelItem, screen: dict[str, object] | None) -> tuple[str, str]:
    """스크립트 출력 → (outcome, reason). 순수함수이고 규칙은 적힌 순서대로 적용한다.

    outcome 은 삼바 회신값(cancelled·already_cancelled·accepted·shipped·bundle·failed)뿐이다.
    """
    # 1) 같은 발주번호 주문이 2건 이상이면 화면을 보기 전에 묶음 — 삼바가 걸렀어도 한 번 더 본다
    if item.bundle_count >= 2:
        return 'bundle', f'같은 발주번호 주문 {item.bundle_count}건'
    # 2) 화면을 못 읽었거나 로그인·주문번호 확인이 안 되면 실패
    if screen is None:
        return 'failed', '화면을 읽지 못함'
    if not _flag(screen, 'login'):
        return 'failed', '로그인 안 됨'
    if not _flag(screen, 'found'):
        return 'failed', '주문번호를 찾지 못함'
    # 3) 화면 상품행이 2개 이상이면 부분취소가 될 수 있다 — 안 누른다
    items = _int(screen, 'items')
    if items >= 2:
        return 'bundle', f'화면 상품행 {items}개'
    # 4) 이미 끝난 상태는 그대로 옮긴다
    state = str(screen.get('state') or '')
    if state == 'shipped':
        return 'shipped', ''
    if state == 'already_cancelled':
        return 'already_cancelled', ''
    if state == 'cancel_pending':
        return 'accepted', ''
    # 5) check 는 읽기 전용 — 다시 취소 가능 상태면 누르지 않고 사람(또는 삼바의 cancel 재선점)에게 넘긴다
    #    (접수 재확인에서 판매자가 되돌렸거나, 클릭 도중 로봇이 죽어 claimed 로 남았던 건)
    if item.mode == 'check' and state == 'cancellable':
        return 'failed', '재확인 중 다시 취소 가능 상태 — 사람 확인'
    # 6) 눌렀으면 되읽은 상태로만 성공을 친다
    if item.mode == 'cancel' and _flag(screen, 'clicked'):
        after = str(screen.get('after_state') or '')
        if after == 'already_cancelled':
            return 'cancelled', ''
        if after == 'cancel_pending':
            return 'accepted', ''
        return 'failed', '클릭 후 확인 안 됨'
    # 7) 상태를 못 가리거나 취소 버튼 후보가 정확히 1개가 아니면 실패
    if state == 'unknown' or not state:
        return 'failed', '화면 상태를 가리지 못함'
    buttons = _int(screen, 'buttons')
    if buttons != 1:
        return 'failed', f'취소 버튼 후보 {buttons}개'
    return 'failed', '클릭하지 않음'


class SourceCanceller:
    """취소 행을 받아 소싱처에서 누르고 회신·알림까지 한 바퀴 도는 실행기."""

    def __init__(
        self,
        wave: WaveClient,
        run_script: Callable[[str, dict[str, object]], dict[str, object] | None],
        notify: TelegramNotifier,
        enabled: Callable[[str], bool],
        idle: Callable[[], bool],
        profiles: Callable[[str], list[str]],
        *,
        ledger_account: Callable[[str], str | None] = lambda source_order_no: None,
        sites: set[str] | None = None,
        sources: Sources | None = None,
        limit: int = DEFAULT_LIMIT,
        reason_text: str = DEFAULT_REASON_TEXT,
    ) -> None:
        self._wave = wave
        self._run_script = run_script
        self._notify = notify
        self._enabled = enabled
        self._idle = idle
        self._profiles = profiles
        self._ledger_account = ledger_account
        self._sites = sites
        self._sources = sources or default_sources()
        self._limit = limit
        self._reason_text = reason_text

    # ── 한 바퀴 ─────────────────────────────────────────────────────────────────

    def run_once(self) -> list[str]:
        """목록을 받아 건마다 처리한다. 회신까지 간 건의 outcome 목록을 돌려준다.

        꺼진 사이트는 회신하지 않고 둔다(15분 뒤 삼바가 다시 내준다). `idle()` 이 False 면 즉시 멈춘다.
        """
        try:
            items = self._wave.robot_cancels(limit=self._limit, sites=self._sites)
        except WaveError as e:
            _log.warning('취소 목록을 받지 못했다: %s', e)
            return []
        done: list[str] = []
        for item in items:
            if not self._idle():
                _log.info(
                    '주문 작업이 돌고 있어 자동취소를 멈춘다 — 남은 %d건은 다음 바퀴',
                    len(items) - len(done),
                )
                break
            if not self._enabled(item.source_site):
                continue
            outcome, reason = self._handle(item)
            try:
                state = self._wave.post_robot_cancel_result(item.id, outcome, reason)
            except WaveError as e:
                _log.warning('취소 결과 회신 실패 %s %s: %s', item.id, outcome, e)
                continue
            done.append(outcome)
            _log.info(
                '취소 회신 %s %s %s → %s (%s) state=%s',
                item.source_site, item.order_number, item.sourcing_order_number, outcome, reason, state,
            )  # fmt: skip
            self._announce(item, outcome, reason, state)
        return done

    def _handle(self, item: RobotCancelItem) -> tuple[str, str]:
        """한 건의 판정 — 스크립트는 1번만 부른다(check 는 읽기만, cancel 은 누르고 되읽기)."""
        if item.bundle_count >= 2:
            return decide(item, None)
        src = self._sources.by_id(item.source_site)
        if src is None:
            return 'failed', '소싱처 설정 없음'
        profile = resolve_profile(
            src,
            item.account_username,
            self._profiles(src.id),
            self._ledger_account(item.sourcing_order_number),
        )
        if profile is None:
            return 'failed', '구매 계정을 정하지 못함'
        return decide(item, self._screen(src, item, profile, item.mode))

    def _screen(
        self, src: Source, item: RobotCancelItem, profile: str, mode: str
    ) -> dict[str, object] | None:
        args: dict[str, object] = {
            'source_order_no': item.sourcing_order_number,
            'profile': profile,
            'mode': mode,
            'reason_text': self._reason_text,
        }
        screen = self._run_script(f'{src.key}_order_cancel', args)
        # 설계서 §6.7 증거 — 스크립트 출력 전체(note 에 클릭 전후 화면 글자 300자)를 로그에 남긴다
        _log.info(
            '취소 화면 %s %s %s mode=%s %s',
            src.id, item.order_number, item.sourcing_order_number, mode,
            json.dumps(screen, ensure_ascii=False) if screen is not None else 'null',
        )  # fmt: skip
        return screen if isinstance(screen, dict) else None

    def _announce(self, item: RobotCancelItem, outcome: str, reason: str, state: str) -> None:
        """카드는 (회신 outcome, 돌아온 state) 로 고른다 — 반영된 회신에만 1통.

        retry(30분 뒤 다시)·반영 안 됨은 조용히. accepted 가 wait_confirm 이면 처음(cancel)만 알리고
        재확인(check)에서 또 접수면 조용히. accepted 인데 done 으로 닫혔으면 삼바가 72시간 만료로
        failed 처리한 것 — mode 와 상관없이 실패 카드로 사람에게 넘긴다.
        """
        if state not in _ANNOUNCE_STATES:
            return
        if outcome == 'accepted':
            if state == 'done':
                outcome, reason = 'failed', EXPIRED_REASON
            elif item.mode != 'cancel':
                return
        src = self._sources.by_id(item.source_site)
        title = f'{item.order_number} · {src.label if src else item.source_site}'
        level, conclusion, todo = card_for(outcome, reason)
        if not self._notify.card(level, title, conclusion, todo):
            _log.warning('텔레그램 카드 전송 실패 %s %s', item.order_number, outcome)

    # ── 상주 고리 ────────────────────────────────────────────────────────────────

    def run_forever(
        self, should_stop: Callable[[], bool], interval_s: float = DEFAULT_INTERVAL_S
    ) -> None:
        while not should_stop():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — 취소 고리는 죽지 않는다
                _log.exception('소싱처 자동취소 주기 실패')
            waited = 0.0
            while waited < interval_s and not should_stop():
                time.sleep(2.0)
                waited += 2.0
