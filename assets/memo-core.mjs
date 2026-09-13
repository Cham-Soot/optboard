export const FIELDS = ['marks', 'memo1', 'memo2'];
const CELLS = ['cH', 'cL', 'pH', 'pL'];
export const emptyEntry = () => ({marks: {}, memo1: '', memo2: '', rev: 0});
const copy = value => JSON.parse(JSON.stringify(value));
export function validKey(key) {
  if (!/^\d{4}\|\d+(?:\.\d+)?\|\d{4}-\d{2}-\d{2}$/.test(key)) return false;
  const [expiry, strike, date] = key.split('|');
  const parsed = new Date(date + 'T00:00:00Z');
  return +expiry.slice(2) >= 1 && +expiry.slice(2) <= 12 && Number(strike) > 0
    && Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date;
}
export function normalizeEntry(value = emptyEntry()) {
  const out = emptyEntry();
  if (value.marks == null || typeof value.marks !== 'object' || Array.isArray(value.marks)) throw new Error('마킹 형식 오류');
  for (const [cell, shape] of Object.entries(value.marks)) {
    if (!CELLS.includes(cell) || !['box', 'ul'].includes(shape)) throw new Error('마킹 값 오류');
  }
  for (const cell of CELLS) if (value.marks[cell]) out.marks[cell] = value.marks[cell];
  for (const field of ['memo1', 'memo2']) {
    const text = value[field] ?? '';
    if (typeof text !== 'string' || text.length > 4000) throw new Error('메모는 4,000자 이하의 문자열이어야 합니다');
    out[field] = text;
  }
  out.rev = Number.isSafeInteger(value.rev) && value.rev >= 0 ? value.rev : 0;
  return out;
}
export function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
export function decodeBackup(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('개인 메모 백업 파일이 아닙니다');
  const marks = input.marks ?? {}, memos = input.memos ?? {};
  if (!marks || !memos || typeof marks !== 'object' || typeof memos !== 'object'
      || Array.isArray(marks) || Array.isArray(memos)) throw new Error('개인 메모 백업 형식 오류');
  const keys = new Set([...Object.keys(marks), ...Object.keys(memos)]);
  if (keys.size > 20000) throw new Error('한 번에 가져올 수 있는 메모는 20,000행입니다');
  const records = {};
  for (const key of keys) {
    if (!validKey(key)) throw new Error('잘못된 월물·행사가·날짜 키: ' + key);
    const pair = memos[key] ?? ['', ''];
    if (!Array.isArray(pair) || pair.length > 2) throw new Error('메모 배열 형식 오류');
    records[key] = normalizeEntry({marks: marks[key] ?? {}, memo1: pair[0] ?? '', memo2: pair[1] ?? ''});
  }
  return records;
}
export function encodeBackup(records) {
  const marks = {}, memos = {};
  for (const [key, row] of Object.entries(records)) {
    // Retain empty values: they explicitly record a deletion.
    marks[key] = row.marks;
    memos[key] = [row.memo1, row.memo2];
  }
  return {formatVersion: 2, exportedAt: new Date().toISOString(), marks, memos};
}
export function mergeSubmission(remote, submitted) {
  const current = normalizeEntry(remote ?? emptyEntry());
  const conflicts = [];
  for (const [field, change] of Object.entries(submitted)) {
    if (!FIELDS.includes(field)) throw new Error('알 수 없는 메모 필드');
    if (!same(current[field], change.base) && !same(current[field], change.value)) conflicts.push(field);
  }
  if (conflicts.length) return {conflicts, current};
  const next = copy(current);
  for (const [field, change] of Object.entries(submitted)) next[field] = copy(change.value);
  const changed = FIELDS.some(field => !same(next[field], current[field]));
  next.rev = current.rev + (changed ? 1 : 0);
  return {conflicts: [], current, next: normalizeEntry(next), changed};
}

export class MemoStore {
  constructor(storage, storageKey, notify = () => {}) {
    this.storage = storage;
    this.storageKey = storageKey;
    this.notify = notify;
    this.records = {};
    this.pending = {};
    this.conflicts = {};
    this.storageError = null;
    this.sequence = 0;
    const raw = storage.getItem(storageKey);
    if (raw) {
      const data = JSON.parse(raw);
      if (data.version !== 2) throw new Error('저장된 메모 형식이 다릅니다. 백업을 먼저 확인하세요');
      for (const [key, row] of Object.entries(data.records ?? {})) {
        if (!validKey(key)) throw new Error('저장된 메모 키 오류');
        this.records[key] = normalizeEntry(row);
      }
      for (const [key, changes] of Object.entries(data.pending ?? {})) {
        if (!validKey(key)) throw new Error('저장된 수정 기록 오류');
        for (const [field, change] of Object.entries(changes)) {
          if (!FIELDS.includes(field) || !change || typeof change.id !== 'string'
              || !Object.hasOwn(change,'base') || !Object.hasOwn(change,'value')) throw new Error('저장된 수정 필드 오류');
          normalizeEntry({...emptyEntry(), [field]:change.base});
          normalizeEntry({...emptyEntry(), [field]:change.value});
        }
        this.pending[key] = changes;
      }
    }
  }
  persist() {
    try {
      this.storage.setItem(this.storageKey, JSON.stringify({version: 2, records: this.records, pending: this.pending}));
      this.storageError = null;
    } catch (error) { this.storageError = error; }
    this.notify();
  }
  view() {
    const out = copy(this.records);
    for (const [key, changes] of Object.entries(this.pending)) {
      out[key] ??= emptyEntry();
      for (const [field, change] of Object.entries(changes)) out[key][field] = copy(change.value);
    }
    return out;
  }
  edit(key, patch) {
    if (!validKey(key)) throw new Error('메모 키 형식 오류');
    const base = this.records[key] ?? emptyEntry();
    const visible = this.view()[key] ?? emptyEntry();
    const normalized = normalizeEntry({...visible, ...patch});
    for (const field of Object.keys(patch)) {
      if (!FIELDS.includes(field)) throw new Error('메모 필드 오류');
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
      const entry = normalizeEntry(row);
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
      else if (this.pending[key]?.[field]) this.pending[key][field].base = copy((this.records[key] ?? emptyEntry())[field]);
    }
    if (!Object.keys(this.pending[key] ?? {}).length) delete this.pending[key];
    delete this.conflicts[key];
    this.persist();
  }
  importBackup(input, mode = 'merge') {
    const imported = decodeBackup(input), current = this.view();
    if (!['merge', 'replace'].includes(mode)) throw new Error('백업 복원 방식 오류');
    for (const key of new Set([...Object.keys(imported), ...(mode === 'replace' ? Object.keys(current) : [])])) {
      const row = imported[key] ?? emptyEntry();
      this.edit(key, {marks: row.marks, memo1: row.memo1, memo2: row.memo2});
    }
    return Object.keys(imported).length;
  }
}
