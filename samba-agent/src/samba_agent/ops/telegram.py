"""텔레그램 카드 알림 — 소싱처 자동취소 결과 1건 1통(AI 비서 B안 형식).

형식: ``🟢|🟡|🔴 <b>제목</b>`` + ``<blockquote>결론\\n👉 할일</blockquote>`` (parse_mode=HTML).
제목·결론·할일은 HTML 이스케이프한다 — 상품명에 '<' 가 섞여도 텔레그램이 거부하지 않는다.

지키는 것:
1. 실패해도 예외를 던지지 않고 False 를 돌려준다 — 알림 실패가 결과 회신을 막으면 안 된다.
2. 봇 토큰은 URL 에만 쓰고 로그·repr·예외 메시지에 옮기지 않는다.
3. 고객 이름·전화·주소를 넣지 않는다(호출부 책임 — 여기는 받은 글자를 그대로 싣는다).
"""

import html
import logging
import re
from typing import Literal

import httpx

log = logging.getLogger(__name__)

TELEGRAM_API = 'https://api.telegram.org'
DEFAULT_TIMEOUT_S = 10.0

# httpx 는 INFO 로 'HTTP Request: POST https://api.telegram.org/bot<토큰>/sendMessage …' 를 찍는다(__main__ 이 INFO 로 켠다).
# 로거 레벨은 올리지 않고(다른 코드가 httpx INFO 줄을 본다) 토큰 조각만 가린다
_TOKEN_IN_URL = re.compile(r'/bot[^/\s"\']+/')
_REDACTED = '/bot***/'
_REDACT_LOGGERS = ('httpx', 'httpcore')


class _TokenRedactFilter(logging.Filter):
    """로그 레코드의 메시지·인자에서 `/bot<토큰>/` 을 `/bot***/` 로 바꾼다. 레코드는 버리지 않는다."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and '/bot' in record.msg:
            record.msg = _TOKEN_IN_URL.sub(_REDACTED, record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(self._clean(a) for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: self._clean(v) for k, v in record.args.items()}
        return True

    @staticmethod
    def _clean(value: object) -> object:
        # httpx 는 URL 객체를 인자로 넘긴다 — 문자열로 바꿔 가린다(가릴 게 없으면 원래 값 유지)
        text = str(value)
        return _TOKEN_IN_URL.sub(_REDACTED, text) if '/bot' in text else value


def install_token_redaction() -> None:
    """httpx·httpcore 로거에 토큰 가림 필터를 한 번만 단다(프로세스당 멱등)."""
    for name in _REDACT_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, _TokenRedactFilter) for f in logger.filters):
            logger.addFilter(_TokenRedactFilter())


Level = Literal['ok', 'warn', 'bad']
_EMOJI: dict[str, str] = {'ok': '🟢', 'warn': '🟡', 'bad': '🔴'}


def card_text(level: Level, title: str, conclusion: str, todo: str) -> str:
    """카드 본문(HTML). 이모지 + 굵은 제목 한 줄, 인용 블록 안에 결론과 👉 할일."""
    emoji = _EMOJI.get(level, _EMOJI['warn'])
    return (
        f'{emoji} <b>{html.escape(title)}</b>\n'
        f'<blockquote>{html.escape(conclusion)}\n👉 {html.escape(todo)}</blockquote>'
    )


class TelegramNotifier:
    """봇 API ``sendMessage`` 로 카드 1통을 보낸다."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        install_token_redaction()
        self._url = f'{TELEGRAM_API}/bot{token}/sendMessage'
        self._chat_id = chat_id
        self._timeout_s = timeout_s
        self._client = client or httpx.Client(timeout=timeout_s)

    def __repr__(self) -> str:
        # 토큰이 든 URL 은 보여주지 않는다
        return f'TelegramNotifier(chat_id={self._chat_id!r})'

    def card(self, level: Level, title: str, conclusion: str, todo: str) -> bool:
        """카드를 보낸다. 보냈으면 True, 어떤 이유로든 못 보냈으면 False(예외 없음)."""
        payload = {
            'chat_id': self._chat_id,
            'text': card_text(level, title, conclusion, todo),
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }
        try:
            r = self._client.post(self._url, json=payload, timeout=self._timeout_s)
        except httpx.HTTPError as e:
            log.warning('텔레그램 전송 실패: %s', type(e).__name__)
            return False
        if r.status_code >= 400:
            log.warning('텔레그램 전송 실패: HTTP %s', r.status_code)
            return False
        try:
            ok = bool(r.json().get('ok'))
        except (ValueError, AttributeError):
            ok = False
        if not ok:
            log.warning('텔레그램 전송 실패: 응답 ok=false')
        return ok

    def close(self) -> None:
        self._client.close()
