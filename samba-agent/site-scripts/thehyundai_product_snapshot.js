// 더현대Hi 스냅샷 — 주문서까지 가서 결제액(결제 없음)
const OF = /thehyundai\.com\/shop\/order(?:[?#]|$)/
const num = s => parseInt(String(s || '').replace(/[^\d]/g, ''), 10) || 0
const tabId = r => (String(r).match(/tab (\S+)/) || [])[1] || null
const tree = async q => String((await page.get(q || {})).tree || '')
const linesOf = tr => tr.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const textOf = tr => (tr.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const idOfLine = l => parseInt(l.slice(1))
const norm = s => String(s || '').toLowerCase().replace(/\[품절\]|품절/g, '').replace(/[\s/·,()_-]+/g, '')
const P = args.profile ? { profile: args.profile } : {}
const sku = String(args.sku || '').trim()
const want = String(args.size || '').trim()
const qty = Math.max(1, parseInt(args.qty, 10) || 1)
const cardSuffix = String(args.card_suffix || '4625')
const find = async q => linesOf(String(await page.find(q)))

if (!args.keepOrderTabs) for (const x of await tabs.list()) if (OF.test(x.url || '')) { try { await tabs.close(x.id) } catch (e) {} }
const pno = (sku.match(/product\/([0-9A-Z]+)/) || [])[1] || (/^[0-9A-Z]{8,}$/.test(sku) ? sku : null)
if (!pno) return { options: [], error: 'no_product', note: 'no product number' }
const product_url = `https://hi.thehyundai.com/product/${pno}`
const tid = tabId(await tabs.open({ ...P, url: product_url }))
if (tid) await tabs.switch(tid)
if (!(await page.waitFor('구매하기', 12000))) return { options: [], error: 'no_product', note: '상품 화면 안 열림', product_tab: tid, product_url }
const product_name = String(await page.title()).replace(/\s*\|\s*더현대Hi\s*$/, '').trim()
const base = { coupons: {}, methods: [], cost: null, product_url, product_no: pno, product_name, product_tab: tid }
let tr = await tree()
if (linesOf(tr).some(l => /link "로그인" href=\/login/.test(l))) return { ...base, options: [], error: 'login_required', note: '로그인 안 됨' }
const t0 = textOf(tr)
if (/일시품절|품절된 상품|판매종료|판매 종료/.test(t0.split('상세정보')[0])) return { ...base, options: [], sold_out: true, error: 'sold_out', note: '전체 품절' }

if (!linesOf(tr).some(l => /\] button "구매하기"$/.test(l))) return { ...base, options: [], note: 'buy button not found' }

const combo = async name => (await find(name)).find(l => new RegExp(`\\] combobox "${name}"`).test(l))
const optionsOf = async () => linesOf(await tree({ selector: '[role=listbox], [class*=option]' })).filter(l => /\] option "/.test(l)).map(l => ({ id: idOfLine(l), t: l.match(/option "([^"]*)"/)[1].trim() }))
const pickBy = (opts, w) => {
  const live = opts.filter(o => !/품절/.test(o.t)), part = live.filter(o => norm(o.t).includes(norm(w)) || norm(w).includes(norm(o.t)))
  return live.find(o => norm(o.t) === norm(w)) || (part.length === 1 ? part[0] : null)
}
const wantParts = want.split('/').map(s => s.trim()).filter(Boolean)
// 옵션 창이 안 뜨면 '구매하기' 다시(10-29)
let boxes = [], open = false
for (let i = 0; i < 20 && !boxes.length; i++) {
  if (!open && i % 5 === 0) { const b = linesOf(await tree()).filter(l => /\] button "구매하기"$/.test(l)).pop(); if (b) await page.click(idOfLine(b)); await sleep(1200) }
  for (const n of ['컬러', '사이즈', '옵션을 선택해 주세요.']) if (await combo(n)) boxes.push(n)
  if (!boxes.length) { open = open || (await find('바로구매')).some(l => /\] button "바로구매"$/.test(l)); await sleep(500) }
}
if (boxes.length > 1) boxes = boxes.filter(n => n !== '옵션을 선택해 주세요.')
if (!boxes.length && !open) return { ...base, options: [], error: 'no_checkout', note: '옵션 창 안 열림' }
let options = [], picked = []
if (!boxes.length) {
  options = ['단일']
  if (want && !/단일|free|one/i.test(want)) return { ...base, options, note: 'size not available: ' + want }
} else {
  if (boxes.length !== wantParts.length && boxes.length !== 1) return { ...base, options: [], note: `option shape ${boxes.length} boxes vs '${want}'` }
  const parts = boxes[0] === '옵션을 선택해 주세요.' ? [want] : boxes.length === 1 ? [wantParts[wantParts.length - 1]] : wantParts
  for (let i = 0; i < boxes.length; i++) {
    const box = await combo(boxes[i])
    if (!box) return { ...base, options, note: 'option box missing' }
    await page.click(idOfLine(box)); await sleep(700)
    let opts = await optionsOf()
    for (let k = 0; k < 6 && !opts.length; k++) { await sleep(500); opts = await optionsOf() }
    const prefix = picked.length ? picked.join('/') + '/' : ''
    options = opts.map(o => prefix + o.t)
    if (!opts.length) return { ...base, options: [], note: 'no options' }
    const hit = pickBy(opts, parts[i])
    if (!hit) return { ...base, options, note: opts.every(o => /품절/.test(o.t)) ? 'all options sold out' : `size not available: ${want}` }
    await page.click(hit.id); await sleep(900)
    picked.push(hit.t)
  }
}
for (let i = 1; i < qty; i++) { const plus = (await find('증가')).find(l => /\] button "증가"$/.test(l)); if (!plus) break; await page.click(idOfLine(plus)); await sleep(300) }
const sheet = await tree()
if (boxes.length && !/총 [\d,]+원/.test(sheet.match(/^OVERLAY: "([^"]*)"/m)?.[1] || textOf(sheet))) return { ...base, options, note: '옵션 선택 미반영' }
const direct = (await find('바로구매')).find(l => /\] button "바로구매"$/.test(l))
if (!direct) return { ...base, options, note: 'buy button not found' }
await page.click(idOfLine(direct))
let ou = ''
for (let i = 0; i < 40 && !OF.test(ou) && !/login/.test(ou); i++) { await sleep(300); ou = await page.url() }
if (/login/.test(ou)) return { ...base, options, error: 'login_required', note: '로그인 필요' }
if (!OF.test(ou)) return { ...base, options, error: 'no_checkout', note: '주문서로 못 감: ' + ou.slice(0, 80) }
if (!(await page.waitFor('결제하기', 10000))) return { ...base, options, error: 'no_checkout', note: '주문서 로딩 실패', order_tab: tid }

let items = []
for (let i = 0; i < 20 && !items.length; i++) { await sleep(500); tr = await tree(); items = linesOf(tr).filter(l => /\] checkbox ".* [\d,]+원 \d+개[ "]/.test(l)).map(l => l.match(/checkbox "([^"]*)"/)[1]) }
if (items.length !== 1) return { ...base, options, order_tab: tid, product_tab: null, error: 'order_form_mismatch', note: `주문서 불일치: order items ${items.length}` }
const it = items[0]
const optTxt = boxes.length ? picked.join(' / ') : ''
const selected = boxes.length ? optTxt : '단일'
const itQty = num((it.match(/ (\d+)개( |$)/) || [])[1])
const bad = boxes.length && !norm(it).includes(norm(optTxt)) ? `option ${optTxt} not in ${it.slice(0, 80)}` : itQty !== qty ? `qty ${itQty} != ${qty}` : null
if (bad) return { ...base, options, selected, order_tab: tid, product_tab: null, error: 'order_form_mismatch', note: '주문서 불일치: ' + bad }

// 즉시할인: 첫 '체크박스' = 현대백화점카드
const notes = []
const t1 = textOf(tr)
if (/체크박스 현대백화점카드/.test(t1) && !/즉시할인 현대백화점카드/.test(t1)) {
  const cb = linesOf(tr).filter(l => /\] clickable "체크박스"$/.test(l))[0]
  if (cb) { await page.click(idOfLine(cb)); await sleep(1200) }
  tr = await tree()
  if (!/즉시할인 현대백화점카드/.test(textOf(tr))) notes.push('현대백화점카드 즉시할인 체크 못함')
} else if (!/체크박스 현대백화점카드/.test(t1)) notes.push('현대백화점카드 즉시할인 없음')

let radio = linesOf(tr).find(l => /\] radio "현대백화점 카드"/.test(l))
const methods = radio ? ['현대백화점카드 간편결제'] : []
if (radio && !/value="on"/.test(radio)) {
  const lab = linesOf(tr).find(l => /\] label "현대백화점 카드"/.test(l))
  await page.click(idOfLine(lab || radio)); await sleep(1200)
  tr = await tree()
}
radio = linesOf(tr).find(l => /\] radio "현대백화점 카드"/.test(l))
const cardBtn = linesOf(tr).find(l => new RegExp(`\\] button "${cardSuffix}\\(`).test(l))
if (radio && /value="on"/.test(radio) && cardBtn) { await page.click(idOfLine(cardBtn)); await sleep(800); tr = await tree() }
else if (radio) notes.push(cardBtn ? '현대백화점 카드 선택 안 됨' : `등록 카드 ${cardSuffix} 없음`)
const t2 = textOf(tr)
const cost = num((t2.match(/결제 금액 ([\d,]+)원/) || [])[1]) || null
return { ...base, product_tab: null, options, selected, cost, qty: itQty, pay_amount: cost, reward: 0, points_used: 0, coupon: 0, methods, card: methods.length ? `현대백화점카드 ${cardSuffix}` : null, order_tab: tid, order_item: it.slice(0, 120), note: notes.join('; ') || 'dup check skipped' }
