// 더현대Hi 주문서 결제수단 견적 — 사용자 2026-10-28: 현대백화점카드(등록 카드 4625) 간편결제만 쓴다. 결제하기는 누르지 않는다.
// 스냅샷이 즉시할인·결제수단·카드를 맞춰 둔 주문서에서 '결제 금액'을 읽는다(꺼져 있으면 다시 켠다).
// args: profile, tab, card_suffix · 반환 {quotes:[{method,card,cost,reward,points_used}],base_cost,order_tab,note}
const OF = /thehyundai\.com\/shop\/order(?:[?#]|$)/
const num = s => parseInt(String(s || '').replace(/[^\d]/g, ''), 10) || 0
const tree = async () => String((await page.get({})).tree || '')
const linesOf = tr => tr.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const textOf = tr => (tr.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const out = note => ({ quotes: [], base_cost: null, note })
const cardSuffix = String(args.card_suffix || '4625')
const cand = (await tabs.list()).filter(t => OF.test(t.url || '') && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return out(cand.length ? `order form ambiguous: ${cand.length} tabs` : 'no order tab')
const tab = cand[0].id
await tabs.switch(tab)
if (!(await page.waitFor('결제하기', 8000))) return out('order form not loaded')
let tr = await tree()
const t1 = textOf(tr)
if (/체크박스 현대백화점카드/.test(t1) && !/즉시할인 현대백화점카드/.test(t1)) {
  const cb = linesOf(tr).filter(l => /\] clickable "체크박스"$/.test(l))[0]
  if (cb) { await page.click(parseInt(cb.slice(1))); await sleep(1200); tr = await tree() }
}
let radio = linesOf(tr).find(l => /\] radio "현대백화점 카드"/.test(l))
if (!radio) return { ...out('현대백화점 카드 결제수단 없음'), order_tab: tab }
if (!/value="on"/.test(radio)) {
  const lab = linesOf(tr).find(l => /\] label "현대백화점 카드"/.test(l))
  await page.click(parseInt((lab || radio).slice(1))); await sleep(1200); tr = await tree()
  const cardBtn = linesOf(tr).find(l => new RegExp(`\\] button "${cardSuffix}\\(`).test(l))
  if (cardBtn) { await page.click(parseInt(cardBtn.slice(1))); await sleep(800); tr = await tree() }
}
radio = linesOf(tr).find(l => /\] radio "현대백화점 카드"/.test(l))
if (!/value="on"/.test(radio || '')) return { ...out('현대백화점 카드 선택 안 됨'), order_tab: tab }
if (!linesOf(tr).some(l => new RegExp(`\\] button "${cardSuffix}\\(`).test(l))) return { ...out(`등록 카드 ${cardSuffix} 없음`), order_tab: tab }
const t = textOf(tr)
const cost = num((t.match(/결제 금액 ([\d,]+)원/) || [])[1]) || null
const discounted = /즉시할인 현대백화점카드/.test(t)
return {
  quotes: [{ method: '현대백화점카드 간편결제', card: `현대백화점카드 ${cardSuffix}`, cost, reward: 0, points_used: 0, registered: true, allowed: true }],
  base_cost: cost,
  order_tab: tab,
  methods_seen: ['현대백화점카드 간편결제'],
  note: discounted ? null : '현대백화점카드 즉시할인 미적용'
}
