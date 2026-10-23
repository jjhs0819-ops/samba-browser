// 더현대Hi 주문 상세 읽기 — 마이페이지 주문내역에서 소싱 주문번호의 주문을 열어 결제금액·사용 포인트·결제수단을 읽는다(변경 없음).
// 상세 주소 /mypage/order/detail?ordNo=<번호>(송장 수집과 같은 주소). 2026-10-23 초안 — 상세 글자 모양은 실측 필요.
// source_order_no 가 없으면 주문내역 맨 위(가장 최근) 주문을 읽고 note 에 남긴다.
// 적립(H.Point)은 원가에 넣지 않는다(reward 0). 원가 = 실결제액(sources.yaml paid_is_cost)
// args: source_order_no, orderNo, site, profile · 반환 {source_order_no,status,paid,points_used,reward,card,note}
const H = 'https://hi.thehyundai.com'
const num = s => parseInt(String(s || '').replace(/[^\d]/g, ''), 10) || 0
const tabId = r => (String(r).match(/tab (\S+)/) || [])[1] || null
const P = args.profile ? { profile: args.profile } : {}
function pe(t) { return t.split('PAGE TEXT')[0].split('\n').map(l => l.match(/^\[(\d+)\] (\S+)(?: "([^"]*)")?(.*)$/)).filter(Boolean).map(m => ({ id: +m[1], role: m[2], t: (m[3] || '').trim(), rest: m[4] || '' })) }
const Q = async q => pe((await page.get({ query: q })).tree)
const text = async () => ((await page.get({})).tree.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
let no = String(args.source_order_no || '').replace(/[^0-9A-Za-z]/g, '')
let note = null
const opened = []
const done = async r => { for (const id of opened) { try { await tabs.close(id) } catch (e) {} } return r }
const open = async url => { const id = tabId(await tabs.open({ ...P, url })); if (id) { opened.push(id); await tabs.switch(id) } return id }
if (!no) {
  // 소싱 주문번호를 모르면 마이페이지 주문내역의 맨 위 주문(실측 필요)
  await open(`${H}/mypage`)
  await page.waitFor(/주문내역|로그인/, 10000); await sleep(800)
  if (/로그인하시면/.test(await text())) return done({ source_order_no: null, paid: null, error: 'login_required', note: '로그인 필요' })
  const ol = (await Q('주문내역')).filter(e => /button|link|clickable/.test(e.role) && /주문\s*내역/.test(e.t)).shift()
  if (!ol) return done({ source_order_no: null, paid: null, note: 'order list button not found(실측 필요)' })
  await page.click(ol.id)
  await page.waitFor(/주문번호|내역이 없/, 10000); await sleep(800)
  no = ((await text()).match(/주문\s*번호\s*:?\s*([0-9A-Za-z-]{6,})/) || [])[1] || ''
  if (!no) return done({ source_order_no: null, paid: null, note: 'no orders' })
  note = 'source_order_no 없음 — 가장 최근 주문을 읽음'
}
// 주문 상세 주소는 송장 수집(content-tracking-thehyundai)이 쓰는 것과 같다
await open(`${H}/mypage/order/detail?ordNo=${encodeURIComponent(no)}`)
if (/\/login/.test(String(await page.url()))) return done({ source_order_no: no, paid: null, error: 'login_required', note: '로그인 필요' })
await page.waitFor(/결제\s*(정보|금액|수단)/, 10000); await sleep(800)
const t = await text()
if (!t.includes(no)) return done({ source_order_no: null, paid: null, note: '상세 화면에 주문번호가 없다' })
const pick = re => { const a = [...t.matchAll(re)]; return a.length ? a[a.length - 1][1] : null }
const paid = num(pick(/(?:최종\s*결제\s*금액|총\s*결제\s*금액|결제\s*금액)\s*:?\s*([\d,]+)\s*원/g)) || null
const points_used = num(pick(/H\.?\s*Point\s*(?:사용)?\s*-?\s*([\d,]+)\s*(?:P|원)/gi))
const card = ((t.match(/결제\s*수단\s*:?\s*(.{2,30}?)(?:\s+\d|\s+결제|\s+할부|$)/) || [])[1] || '').trim() || null
const status = (t.match(/(결제완료|주문완료|상품준비중|배송준비중|배송중|배송완료|구매확정|취소신청|취소완료|반품\S*|교환\S*)/) || [])[1] || null
return done({ source_order_no: no, status, paid, points_used, reward: 0, card, note })
