# 구매 에이전트 — 더현대Hi(더현대닷컴)

공통 규칙([buyer_default.md](buyer_default.md))을 잇는다. 여기에는 이 소싱처만의 차이만 적는다.

## 흐름(2026-10-23 초안 — 로그인 뒤 화면은 실측 전)
1. `thehyundai_product_snapshot` — 상품은 원문링크 `hi.thehyundai.com/product/<slitmCd 10자>` 로 연다(sources.yaml product_id).
   선택지·품절은 상품 API(detail·uitmStckList)로 먼저 읽고, 옵션 시트에서 같은 글자를 골라 구매하기로 주문서까지 간다.
   주문서에서 현대백화점카드 간편결제를 눌러 둔 뒤 총액(원가)과 담긴 옵션(selected)을 되읽는다.
2. 배송지 — 전부 고객 직배. `thehyundai_set_shipping`(배송지 변경 → 신규 입력: 이름·주소 검색·상세주소, 전화 칸은 비움)
   → 하네스가 전화 칸에 **키마스터 신원정보(업무폰)** 를 채움 → `thehyundai_confirm_shipping`(저장·주문서 되읽기).
   **고객 전화번호는 절대 쓰지 않는다**(사용자 2026-10-23). 주소록의 옛 항목은 고르지 않는다.
3. `checkout_enter_thehyundai` — 현대백화점카드 간편결제·필수 동의 뒤 '결제하기'. 시험(dryRun)은 그 직전에서 멈춘다.
4. 결제 비밀번호 = 카드 비밀번호 **앞 2자리** — 결제 단계가 키마스터(thehyundai.com 계정 · 결제 비밀번호 제공자 site)로
   앱이 넣는다. 에이전트는 값을 보지도 타이핑하지도 않는다.
5. `thehyundai_order_detail` — 마이페이지 주문내역에서 결제금액·H.Point 사용·결제수단을 읽는다.

## 이 소싱처만의 차이
- 결제수단은 **현대백화점카드 간편결제만**(sources.yaml pay_provider: site). 주문서에 없으면 다른 수단으로 대신 사지 않고 사람에게.
- 품절은 상품 itemSellGbcd '11'(일시품절) 또는 옵션 uitmSellGbcd '11'·재고 0 으로 본다. **재고 숫자만으로 품절이 아니라고 보지 않는다**
  (더현대는 일시품절이어도 재고 숫자를 그대로 준다).
- 원가 = 실제 결제 금액(`paid_is_cost`). 현대카드 청구할인 계수를 곱하지 않고, H.Point 적립은 원가에 넣지 않는다.
- 같은 상품 중복 구매 흔적(최근 주문내역) 확인은 아직 없다 — 주문내역 화면 실측 뒤 스냅샷에 넣는다.
