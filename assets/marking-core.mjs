// Automatic marks are derived from public prices and private start points.
// A reversal is confirmed on the following session; its box belongs to the prior row.
export const CELLS = ['cH', 'cL', 'pH', 'pL'];
export const COLORS = ['green', 'red', 'blue', 'yellow'];
export const CROSS = {cH:'pL', cL:'pH', pH:'cL', pL:'cH'};
export const SAME_SIDE = {cH:'cL', cL:'cH', pH:'pL', pL:'pH'};
export const planKey = (expiry, date) => `${expiry}|plan|${date}`;
export const isPlanKey = key => typeof key === 'string' && /^\d{4}\|plan\|\d{4}-\d{2}-\d{2}$/.test(key);
export function boxPair(cell) {
  if (!CELLS.includes(cell)) throw new Error('마킹 시작 칸 오류');
  return Object.fromEntries(CELLS.map(c => [c, c === cell || c === CROSS[cell] ? 'box' : 'ul']));
}
export function priceAt(doc, strike, date, cell) {
  const status = doc.collection?.[date]?.contracts?.[`${strike}|${cell[0]}`]?.status;
  if (status && status !== 'ok') return null;
  const row = doc.index?.[`${strike}|${date}`] ?? doc.rows?.find(r => Number(r.strike) === Number(strike) && r.date === date);
  const value = row?.[cell[0]]?.[cell[1] === 'H' ? 1 : 2];
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}
export function deriveMarks(doc, plans) {
  const marks = {}, events = {}, covered = new Set();
  const dates = [...new Set(doc.dates ?? [])].sort();
  const starts = new Map(dates.map(date => [date, plans[planKey(doc.expiry, date)]?.anchor]).filter(([,cell]) => CELLS.includes(cell)));
  if (!starts.size) return {marks, events, covered};
  // Build once; do not search the whole price history for every cell.
  const indexed = doc.index ? doc : {...doc, index:Object.fromEntries((doc.rows ?? []).map(r => [`${Number(r.strike)}|${r.date}`, r]))};
  for (const rawStrike of doc.strikes ?? []) {
    const strike = String(Number(rawStrike));
    let anchor = null, watched = null, previous = null;
    const putMarks = (date, values) => {
      const key = `${doc.expiry}|${strike}|${date}`;
      marks[key] = Object.fromEntries(Object.entries(values).filter(([cell]) => priceAt(indexed, strike, date, cell) !== null));
    };
    for (const date of dates) {
      const key = `${doc.expiry}|${strike}|${date}`;
      if (starts.has(date)) {
        anchor = starts.get(date);
        watched = SAME_SIDE[anchor];
        previous = null;
        covered.add(key);
        putMarks(date, boxPair(anchor));
        const value = priceAt(indexed, strike, date, watched);
        if (value !== null) previous = {date, value};
        continue;
      }
      if (!anchor) continue;
      covered.add(key);
      const value = priceAt(indexed, strike, date, watched);
      if (value === null) {
        previous = null; // Never bridge a known missing/invalid quote.
        putMarks(date, {});
        continue;
      }
      const reversed = previous && (watched[1] === 'L' ? value > previous.value : value < previous.value);
      if (reversed) {
        const pivot = `${doc.expiry}|${strike}|${previous.date}`;
        putMarks(previous.date, boxPair(watched));
        events[pivot] = {cell:watched, confirmedOn:date};
        watched = SAME_SIDE[watched];
      }
      putMarks(date, {[watched]:'ul', [CROSS[watched]]:'ul'});
      const nextValue = priceAt(indexed, strike, date, watched);
      previous = nextValue === null ? null : {date, value:nextValue};
    }
  }
  return {marks, events, covered};
}
