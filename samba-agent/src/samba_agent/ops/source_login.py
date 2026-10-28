"""소싱처 자동취소 전 키마스터 로그인 — 결제(Buyer._login_check)와 같은 순서를 브릿지 도구로 되풀이한다.

취소 스크립트는 `profile` 세션에서 주문 화면을 여는데, 그 세션이 로그인돼 있지 않으면 주문 대신 로그인
페이지가 떠 `login=false` 로 실패한다(결제 실기와 같은 함정). 그래서 스크립트 전에 홈 탭을 프로필로 열어
앱 `login` 도구로 로그인 상태를 만들고, 연 탭은 전부 닫는다.

Buyer 와 다른 점: 계정 전환 간격(_ACCOUNT_SWITCH_GAP_S)·`<key>_signed_in` 보조 스크립트는 쓰지 않는다 —
취소는 한 건에 한 계정이고 검증 사이트(무신사·롯데온)는 앱 공통 판정으로 충분하다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from samba_agent.agents.buyer import (
    _LOGIN_BUSY_WORDS,
    _LOGIN_SETTLE_MS,
    ALREADY_SIGNED_IN,
    LOGIN_FIELDS_NOT_FOUND,
    LOGIN_SUBMITTED,
)
from samba_agent.bridge.client import BridgeError
from samba_agent.ops.masking import mask_text
from samba_agent.sources import Source

_log = logging.getLogger(__name__)

# 브릿지 도구 1건을 부르고 결과 본문을 돌려주는 호출자(`BridgeClient.call(...).result`). 실패는 BridgeError
ToolCaller = Callable[..., str]
# 로그인 도우미가 부르는 도구 — __main__ 의 cancel 레인 허용 목록에 그대로 넣는다
LOGIN_TOOLS: tuple[str, ...] = ('new_tab', 'switch_tab', 'wait', 'login', 'close_tab')
# 앱 new_tab 출력('ok: tab <id>')에서 탭 id — Buyer._open_home 과 같은 규칙
_TAB_ID = re.compile(r'tab ([0-9a-fA-F-]{8,})')
# 도구 출력에 아이디·비밀번호 꼴(`id=…`, `password: …`)이 섞여 나와도 로그·사유에 남기지 않는다
_CREDENTIAL = re.compile(r'(?i)\b(id|user(?:name)?|pw|pass(?:word)?)\s*[:=]\s*\S+')


def mask_login_output(out: str) -> str:
    """로그인 도구 출력을 로그에 남길 수 있게 가린다(개인정보 + 자격증명 꼴). 120자까지만."""
    return mask_text(_CREDENTIAL.sub(r'\1=***', out[:120]))


def _open_home(tool: ToolCaller, home: str, label: str, opened: list[str]) -> None:
    """계정 프로필로 홈 탭을 열어 작업 대상으로 잡고 id 를 적어 둔다(끝나면 닫는다)."""
    m = _TAB_ID.search(tool('new_tab', url=home, profile=label))
    if m:
        opened.append(m.group(1))
        # 다른 레인의 팝업이 떠 있으면 앱은 그 창을 대상으로 보고 로그인 칸을 못 찾는다(결제 실기 2026-10-14)
        try:
            tool('switch_tab', id=m.group(1))
        except BridgeError:
            pass


def _login_check(tool: ToolCaller, home: str, label: str, opened: list[str]) -> tuple[bool, str]:
    _open_home(tool, home, label, opened)
    tool('wait', ms=_LOGIN_SETTLE_MS)
    out = tool('login', accountLabel=label).strip()
    # 앱이 바빠 홈이 덜 떴으면 로그인 상태도 입력칸도 못 본다 — 홈을 다시 열고 기다림을 늘려 두 번까지
    for retry in (1, 2):
        if not (out.startswith(LOGIN_FIELDS_NOT_FOUND) or any(w in out for w in _LOGIN_BUSY_WORDS)):
            break
        _log.info('소싱처 로그인 %s: 페이지가 덜 떠 다시 시도(%d/2)', label, retry)
        # 응답이 없던 탭은 떠 가는 중이니 그대로 다시 부르고, 그 밖에는 새로 연다
        if not out.startswith('error: page did not respond'):
            _open_home(tool, home, label, opened)
        tool('wait', ms=_LOGIN_SETTLE_MS * 2 * retry)
        out = tool('login', accountLabel=label).strip()
    if out.startswith(ALREADY_SIGNED_IN):
        return True, '이미 로그인돼 있음'
    if out.startswith(LOGIN_SUBMITTED):
        tool('wait', ms=_LOGIN_SETTLE_MS)
        out = tool('login', accountLabel=label).strip()
        if out.startswith(ALREADY_SIGNED_IN):
            return True, '로그인 완료'
    return False, mask_login_output(out)


def ensure_bridge_login(tool: ToolCaller, src: Source, label: str) -> tuple[bool, str]:
    """`label` 계정으로 `src` 에 로그인돼 있게 한다. (성공 여부, 가린 설명) — 예외는 던지지 않는다.

    연 탭은 성공·실패와 상관없이 전부 닫는다(같은 사이트·계정 탭이 쌓이면 리소스를 먹는다).
    """
    if not src.home:
        return False, f'소싱처 첫 페이지 주소가 표에 없다: {src.id}'
    opened: list[str] = []
    try:
        return _login_check(tool, src.home, label, opened)
    except BridgeError as e:
        return False, mask_login_output(str(e))
    finally:
        for tab_id in opened:
            try:
                tool('close_tab', id=tab_id)
            except BridgeError:
                pass  # 이미 닫혔거나 못 닫아도 로그인 결과는 바꾸지 않는다
