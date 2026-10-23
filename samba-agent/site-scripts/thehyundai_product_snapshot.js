// 더현대Hi 상품 스냅샷 — 주문 옵션을 골라 구매하기로 주문서까지 가서 원가·담긴 옵션을 되읽는다(결제 없음). 2026-10-23 초안.
// 옵션·품절은 상품 API(detail·uitmStckList)로 읽는다. 품절 = 상품 itemSellGbcd '11'(재고 숫자로 판정 안 함)·옵션 '11'·재고 0.
// 로그인 뒤 옵션 시트·주문서는 실측 전 — 글자 대조로만 고르고 못 고르면 note 로 멈춘다. 결제는 현대백화점카드 간편결제만
// args: sku, size, qty, profile · 반환 {options,selected,cost,methods,order_tab,product_no,product_name,note}
const H = 'https://hi.thehyundai.com'
const OF = /thehyundai\.com\/(?!mypage)[^?#]*order/i
const num = s => parseInt(String(s || '').replace(/[^\d]/g, ''), 10) || 0
const tabId = r => (String(r).match(/tab (\S+)/) || [])[1] || null
const pe = t => t.split('PAGE TEXT')[0].split('\n').map(l => l.match(/^\[(\d+)\] (\S+)(?: "([^"]*)")?/)).filter(Boolean).map(m => ({ id: +m[1], role: m[2], t: (m[3] || '').trim() }))
const Q = async q => pe((await page.get({ query: q })).tree)
const text = async () => ((await page.get({})).tree.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const norm = s => String(s || '').toLowerCase().replace(/\[품절\]|일시품절|품절/g, '').replace(/[\s/·,()_:\-]+/g, '')
const P = args.profile ? { profile: args.profile } : {}
const sku = String(args.sku || '').trim()
const want = String(args.size || '').trim()
const qty = Math.max(1, parseInt(args.qty, 10) || 1)
const pno = ((sku.match(/\/product\/([0-9A-Za-z]{10})/) || [])[1] || (/^[0-9A-Za-z]{10}$/.test(sku) ? sku : '')).toUpperCase()
if (!pno) return { options: [], error: 'no_product', note: 'slitmCd 없음: ' + sku.slice(0, 60) }
if (!args.keepOrderTabs) for (const x of await tabs.list()) if (OF.test(x.url || '')) { try { await tabs.close(x.id) } catch (e) {} }
async function api(p) {
  const id = tabId(await tabs.open({ ...P, url: `${H}/proxy/v1/pd/item/${p}?slitmCd=${pno}` }))
  if (!id) return ''
  await tabs.switch(id); await page.waitFor('"result"', 8000)
  const t = (await page.get({})).tree.split('PAGE TEXT:')[1] || ''
  try { await tabs.close(id) } catch (e) {}
  return t
}
const g = (re, s) => (String(s).match(re) || [])[1]
const objs = s => [...String(s).matchAll(/\{[^{}]*"uitmTotNm"\s*:\s*"([^"]*)"[^{}]*\}/g)].map(m => ({ t: m[1].trim(), q: num(g(/"sellPossQty"\s*:\s*"?(\d+)/, m[0])), gb: g(/"uitmSellGbcd"\s*:\s*"(\d+)"/, m[0]) }))
const dt = await api('detail')
const sellGb = g(/"itemSellGbcd"\s*:\s*"(\d+)"/, dt)
const comb = g(/"uitmCombYn"\s*:\s*"(\d)"/, dt)
let opts = []
if (comb === '1') opts = objs(await api('uitm/uitmStckList')).map(o => ({ t: o.t, sold: o.q <= 0 }))
else if (comb === '0') opts = objs(dt).map(o => ({ t: o.t, sold: o.gb === '11' || o.q <= 0 }))
if (comb === '0' && !opts.length && !/"uitmAttrList"\s*:\s*\[\s*\{/.test(dt)) opts = [{ t: '단일', sold: false, single: true }]
const tid = tabId(await tabs.open({ ...P, url: `${H}/product/${pno}` }))
if (tid) await tabs.switch(tid)
await page.waitFor(/구매하기|일시품절|판매종료|품절/, 12000)
await sleep(800)
const product_name = String(await page.title()).replace(/\s*\|\s*더현대\s*Hi\s*$/i, '').trim()
const base = { already_ordered: null, existing_order_no: null, coupons: {}, methods: [], cost: null, product_url: `${H}/product/${pno}`, product_no: pno, product_name, selected: null, product_tab: tid }
const options = opts.map(o => o.sold ? o.t + ' [품절]' : o.t)
const skip = (note, x) => ({ ...base, options, note, ...(x || {}) })
const buyBtn = async () => (await Q('구매하기')).filter(e => e.role === 'button' && /^(바로\s*)?구매하기$/.test(e.t)).pop()
// 일시품절 확정은 두 신호(API '11' 또는 화면 일시품절 + 구매하기 버튼 없음)일 때만 — 한 번 튄 값으로 자동취소되지 않게
if (!(await buyBtn()) && (sellGb === '11' || /일시품절|판매종료/.test(await text())))
  return skip('상품 전체 품절(일시품절)', { sold_out: true, error: 'sold_out' })
const avail = opts.filter(o => !o.sold)
let pick = null
if (!opts.length) return skip('no options (상품 API 를 못 읽음 — 실측 필요)')
{
  if (want) {
    const w = norm(want)
    pick = avail.find(o => o.t === want) || avail.find(o => norm(o.t) === w)
    if (!pick) { const wt = want.toLowerCase().split(/[\s/·,]+/).filter(Boolean); const h = avail.filter(o => { const ot = o.t.toLowerCase().split(/[\s/·,()]+/); return wt.every(x => ot.includes(x)) }); if (h.length === 1) pick = h[0] }
    if (!pick && avail.length === 1 && avail[0].single) pick = avail[0]
  } else if (avail.length === 1) pick = avail[0]
  if (!pick) return skip(avail.length ? `size not available: ${want}` : 'all options sold out')
}
const b0 = await buyBtn()
if (!b0) return skip('buy button not found')
await page.click(b0.id); await sleep(1200)
const loginAsk = async () => /로그인이 필요한|로그인 하시겠습니까/.test((await page.get({})).tree)
if (await loginAsk()) { const c = (await Q('취소')).filter(e => e.role === 'button').pop(); if (c) await page.click(c.id); return { ...skip('로그인 필요(로그인 안내창)'), error: 'login_required' } }
async function choose(label) {
  const L = norm(label); if (!L) return false
  for (let k = 0; k < 3; k++) {
    const es = (await Q(label.split(/[\s/]+/)[0] || label)).filter(e => e.t && norm(e.t).startsWith(L) && norm(e.t).length <= L.length + 14 && !/품절/.test(e.t) && /button|option|radio|listitem|link|clickable|menuitem/.test(e.role))
    if (es.length) { await page.click(es[es.length - 1].id); await sleep(800); return true }
    const dd = (await Q('선택')).filter(e => /옵션.*선택|선택해|사이즈.*선택|색상.*선택|선택하세요/.test(e.t))
    if (!dd.length) return false
    await page.click(dd[dd.length - 1].id); await sleep(800)
  }
  return false
}
if (pick && !pick.single) {
  let ok = await choose(pick.t)
  if (!ok && /[/,]/.test(pick.t)) { ok = true; for (const part of pick.t.split(/\s*[/,]\s*/).filter(Boolean)) ok = ok && await choose(part) }
  if (!ok) return skip(`option not matched: 시트에서 [${pick.t}] 를 못 찾음(실측 필요)`)
}
for (let i = 1; i < qty; i++) {
  const plus = (await Q('수량')).filter(e => /증가|더하기|플러스|올리기|\+/.test(e.t)).pop()
  if (!plus) return skip('qty>1: 수량 증가 버튼 없음(실측 필요)')
  await page.click(plus.id); await sleep(300)
}
const b1 = (await Q('구매')).filter(e => e.role === 'button' && /^(바로\s*구매|바로구매하기|구매하기)$/.test(e.t)).pop()
if (!b1) return skip('sheet buy button not found')
await page.click(b1.id)
let ou = ''
for (let i = 0; i < 40 && !OF.test(ou); i++) { await sleep(400); ou = String(await page.url()); if (i % 5 === 4 && await loginAsk()) return { ...skip('로그인 필요'), error: 'login_required' } }
if (!OF.test(ou)) { const ov = ((await page.get({})).tree.match(/OVERLAY: "([^"]{0,80})/) || [])[1]; return { ...skip('주문서로 못 감: ' + (ov || ou.replace(/^https?:\/\//, '').slice(0, 70))), error: ov && /옵션/.test(ov) ? undefined : 'no_checkout' } }
await page.waitFor(/결제하기|결제 ?금액/, 12000); await sleep(1000)
async function payPick() {
  let c = (await Q('현대백화점카드')).filter(e => /현대백화점\s*카드/.test(e.t))
  if (!c.length) { const tab = (await Q('간편결제')).filter(e => /^간편\s*결제$/.test(e.t)).pop(); if (tab) { await page.click(tab.id); await sleep(800); c = (await Q('현대백화점카드')).filter(e => /현대백화점\s*카드/.test(e.t)) } }
  const hit = c.find(e => /간편/.test(e.t)) || c[c.length - 1]
  if (!hit) return false
  await page.click(hit.id); await sleep(1200); return true
}
const hdc = await payPick()
const t = await text()
const grab = re => { const all = [...t.matchAll(re)]; return all.length ? num(all[all.length - 1][1]) : 0 }
const cost = grab(/(?:최종\s*결제\s*금액|총\s*결제\s*금액|결제\s*예정\s*금액)\s*:?\s*([\d,]+)\s*원/g) || grab(/([\d,]+)\s*원\s*결제하기/g) || null
let selected = null
if (pick && (pick.single || norm(t).includes(norm(pick.t)))) selected = pick.t
else selected = (t.match(/옵션\s*[:：]?\s*(.{1,40}?)\s*(?:\/\s*)?(?:수량|\d+\s*개)/) || [])[1] || null
const q2 = num((t.match(/수량\s*[:：]?\s*(\d+)\s*개?/) || [])[1])
if (q2 && q2 !== qty) return { ...skip(`주문서 불일치: qty ${q2} != ${qty}`), selected, order_tab: tid, product_tab: null, error: 'order_form_mismatch' }
const methods = hdc ? ['현대백화점카드 간편결제'] : []
const points_used = num((t.match(/H\.?\s*Point\s*사용\s*-?\s*([\d,]+)/i) || [])[1])
return { ...base, product_tab: null, options, selected, cost, qty, pay_amount: cost, points_used, reward: 0, methods, order_tab: tid, order_item: product_name, note: (hdc ? '' : '현대백화점카드 간편결제 없음(실측 필요) · ') + 'dup check skipped' }
