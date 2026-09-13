import {CELLS, COLORS, isPlanKey} from './marking-core.mjs';
export {isPlanKey};
export const FIELDS = ['marks', 'colors', 'memo1', 'memo2', 'anchor'];
export const fieldsForKey = key => isPlanKey(key) ? ['anchor'] : ['marks', 'colors', 'memo1', 'memo2'];
export const emptyEntry = () => ({marks: {}, colors:{}, memo1: '', memo2: '', rev: 0});
export const emptyForKey = key => isPlanKey(key) ? {anchor:'', rev:0} : emptyEntry();
const copy = value => JSON.parse(JSON.stringify(value));
export function validKey(key) {
  if (typeof key !== 'string' || !/^\d{4}\|(?:\d+(?:\.\d+)?|plan)\|\d{4}-\d{2}-\d{2}$/.test(key)) return false;
  const [expiry, strike, date] = key.split('|');
  const parsed = new Date(date + 'T00:00:00Z');
  return +expiry.slice(2) >= 1 && +expiry.slice(2) <= 12 && (strike === 'plan' || Number(strike) > 0)
    && Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date;
}
export function normalizeEntry(value = emptyEntry()) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('저장 형식 오류');
  if (Object.hasOwn(value, 'anchor')) {
    if (!['', ...CELLS].includes(value.anchor) || ['marks','colors','memo1','memo2'].some(f=>Object.hasOwn(value,f))) throw new Error('자동 마킹 시작점 형식 오류');
    return {anchor:value.anchor, rev:Number.isSafeInteger(value.rev) && value.rev >= 0 ? value.rev : 0};
  }
  const out = emptyEntry();
  if (value.marks == null || typeof value.marks !== 'object' || Array.isArray(value.marks)) throw new Error('마킹 형식 오류');
  for (const [cell, shape] of Object.entries(value.marks)) {
    if (!CELLS.includes(cell) || !['box', 'ul'].includes(shape)) throw new Error('마킹 값 오류');
  }
  for (const cell of CELLS) if (value.marks[cell]) out.marks[cell] = value.marks[cell];
  const colors = value.colors ?? {};
  if (!colors || typeof colors !== 'object' || Array.isArray(colors)) throw new Error('네모 배경색 형식 오류');
  for (const [cell, color] of Object.entries(colors)) {
    if (!CELLS.includes(cell) || !COLORS.includes(color)) throw new Error('네모 배경색 값 오류');
  }
  for (const cell of CELLS) if (colors[cell]) out.colors[cell] = colors[cell];
  for (const field of ['memo1', 'memo2']) {
    const text = value[field] ?? '';
    if (typeof text !== 'string' || text.length > 4000) throw new Error('메모는 4,000자 이하의 문자열이어야 합니다');
    out[field] = text;
  }
  out.rev = Number.isSafeInteger(value.rev) && value.rev >= 0 ? value.rev : 0;
  return out;
}
function normalizeForKey(key, value) {
  if (isPlanKey(key) !== Object.hasOwn(value, 'anchor')) throw new Error('저장 위치와 자료 형식이 다릅니다');
  return normalizeEntry(value);
}
export function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
export function decodeBackup(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('개인 메모 백업 파일이 아닙니다');
  const marks = input.marks ?? {}, memos = input.memos ?? {}, colors = input.colors ?? {}, plans = input.plans ?? {};
  if ([marks,memos,colors,plans].some(v=>!v || typeof v !== 'object' || Array.isArray(v))) throw new Error('개인 메모 백업 형식 오류');
  const keys = new Set([...Object.keys(marks), ...Object.keys(memos), ...Object.keys(colors)]);
  if (keys.size + Object.keys(plans).length > 20000) throw new Error('한 번에 가져올 수 있는 자료는 20,000개입니다');
  const records = {};
  for (const key of keys) {
    if (!validKey(key) || isPlanKey(key)) throw new Error('잘못된 월물·행사가·날짜 키: ' + key);
    const pair = memos[key] ?? ['', ''];
    if (!Array.isArray(pair) || pair.length > 2) throw new Error('메모 배열 형식 오류');
    records[key] = normalizeEntry({marks: marks[key] ?? {}, colors:colors[key] ?? {}, memo1: pair[0] ?? '', memo2: pair[1] ?? ''});
  }
  for (const [key, anchor] of Object.entries(plans)) {
    if (!validKey(key) || !isPlanKey(key)) throw new Error('자동 마킹 시작점의 월물·날짜 오류');
    records[key] = normalizeEntry({anchor});
  }
  return records;
}
export function encodeBackup(records) {
  const marks = {}, memos = {}, colors = {}, plans = {};
  for (const [key, row] of Object.entries(records)) {
    if (isPlanKey(key)) { plans[key] = row.anchor; continue; }
    // Retain empty values: they explicitly record a deletion.
    marks[key] = row.marks;
    memos[key] = [row.memo1, row.memo2];
    colors[key] = row.colors ?? {};
  }
  return {formatVersion: 3, exportedAt: new Date().toISOString(), marks, memos, colors, plans};
}
export function mergeSubmission(remote, submitted) {
  const plan = Object.hasOwn(submitted,'anchor') || (remote && Object.hasOwn(remote,'anchor'));
  const current = normalizeEntry(remote ?? (plan ? {anchor:'',rev:0} : emptyEntry()));
  const fields = plan ? ['anchor'] : ['marks','colors','memo1','memo2'];
  const conflicts = [];
  for (const [field, change] of Object.entries(submitted)) {
    if (!fields.includes(field)) throw new Error('알 수 없는 메모 필드');
    if (!same(current[field], change.base) && !same(current[field], change.value)) conflicts.push(field);
  }
  if (conflicts.length) return {conflicts, current};
  const next = copy(current);
  for (const [field, change] of Object.entries(submitted)) next[field] = copy(change.value);
  const changed = fields.some(field => !same(next[field], current[field]));
  next.rev = current.rev + (changed ? 1 : 0);
  return {conflicts: [], current, next: normalizeEntry(next), changed};
}

export class MemoStore {
  constructor(storage, storageKey, notify = () => {}, legacyKey = null) {
    this.storage = storage;
    this.storageKey = storageKey;
    this.notify = notify;
    this.records = {};
    this.pending = {};
    this.conflicts = {};
    this.storageError = null;
    this.sequence = 0;
    const raw = storage.getItem(storageKey) ?? (legacyKey ? storage.getItem(legacyKey) : null);
    if (raw) {
      const data = JSON.parse(raw);
      if (![2,3].includes(data.version)) throw new Error('저장된 메모 형식이 다릅니다. 백업을 먼저 확인하세요');
      for (const [key, row] of Object.entries(data.records ?? {})) {
        if (!validKey(key)) throw new Error('저장된 메모 키 오류');
        this.records[key] = normalizeForKey(key, row);
      }
      for (const [key, changes] of Object.entries(data.pending ?? {})) {
        if (!validKey(key)) throw new Error('저장된 수정 기록 오류');
        for (const [field, change] of Object.entries(changes)) {
          if (!fieldsForKey(key).includes(field) || !change || typeof change.id !== 'string'
              || !Object.hasOwn(change,'base') || !Object.hasOwn(change,'value')) throw new Error('저장된 수정 필드 오류');
          normalizeEntry({...emptyForKey(key), [field]:change.base});
          normalizeEntry({...emptyForKey(key), [field]:change.value});
        }
        this.pending[key] = changes;
      }
    }
  }
  persist() {
    try {
      this.storage.setItem(this.storageKey, JSON.stringify({version: 3, records: this.records, pending: this.pending}));
      this.storageError = null;
    } catch (error) { this.storageError = error; }
    this.notify();
  }
  view() {
    const out = copy(this.records);
    for (const [key, changes] of Object.entries(this.pending)) {
      out[key] ??= emptyForKey(key);
      for (const [field, change] of Object.entries(changes)) out[key][field] = copy(change.value);
    }
    return out;
  }
  edit(key, patch) {
    if (!validKey(key)) throw new Error('메모 키 형식 오류');
    if (Object.keys(patch).some(field=>!fieldsForKey(key).includes(field))) throw new Error('메모 필드 오류');
    const base = this.records[key] ?? emptyForKey(key);
    const visible = this.view()[key] ?? emptyForKey(key);
    const normalized = normalizeForKey(key, {...visible, ...patch});
    for (const field of Object.keys(patch)) {
      const original = this.pending[key]?.[field]?.base ?? base[field];
      this.pending[key] ??= {};
      this.pending[key][field] = {base: copy(original), value: copy(normalized[field]),
        id: `${Date.now()}-${++this.sequence}`};
    }
    delete this.conflicts[key];
    this.persist();
  }
  receive(records) {
    for (const [key, row] of Object.entries(records)) {
      if (!validKey(key)) throw new Error('서버 메모 키 오류');
      const entry = normalizeForKey(key, row);
      if (!this.records[key] || entry.rev >= this.records[key].rev) this.records[key] = entry;
    }
    this.persist();
  }
  submission(key) { return copy(this.pending[key]); }
  acknowledge(key, submitted, row) {
    this.receive({[key]: row});
    for (const [field, sent] of Object.entries(submitted)) {
      const remaining = this.pending[key]?.[field];
      if (!remaining) continue;
      if (remaining.id === sent.id) delete this.pending[key][field];
      else remaining.base = copy(row[field]);
    }
    if (!Object.keys(this.pending[key] ?? {}).length) delete this.pending[key];
    delete this.conflicts[key];
    this.persist();
  }
  setConflict(key, result) {
    this.receive({[key]: result.current});
    this.conflicts[key] = result.conflicts;
    this.persist();
  }
  resolve(key, choice) {
    if (!['mine', 'remote'].includes(choice)) throw new Error('충돌 처리 선택 오류');
    for (const field of this.conflicts[key] ?? []) {
      if (choice === 'remote') delete this.pending[key][field];
      else if (this.pending[key]?.[field]) this.pending[key][field].base = copy((this.records[key] ?? emptyForKey(key))[field]);
    }
    if (!Object.keys(this.pending[key] ?? {}).length) delete this.pending[key];
    delete this.conflicts[key];
    this.persist();
  }
  importBackup(input, mode = 'merge') {
    const imported = decodeBackup(input), current = this.view();
    if (!['merge', 'replace'].includes(mode)) throw new Error('백업 복원 방식 오류');
    for (const key of new Set([...Object.keys(imported), ...(mode === 'replace' ? Object.keys(current) : [])])) {
      const row = imported[key] ?? emptyForKey(key);
      const patch = Object.fromEntries(fieldsForKey(key).map(field=>[field,row[field]]));
      // Old backups do not know about colors; importing them must not erase new colors.
      if (!isPlanKey(key) && input.formatVersion !== 3 && !Object.hasOwn(input,'colors') && mode === 'merge') delete patch.colors;
      this.edit(key, patch);
    }
    return Object.keys(imported).length;
  }
}
