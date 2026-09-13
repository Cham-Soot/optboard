import test from 'node:test';
import assert from 'node:assert/strict';
import {MemoStore, emptyEntry, encodeBackup, decodeBackup, mergeSubmission} from '../assets/memo-core.mjs';
const KEY='2610|1100|2026-09-11';
const memory=()=>{const data=new Map();return {getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)};};
test('different fields from two devices merge',()=>{
  const a=new MemoStore(memory(),'a');a.edit(KEY,{memo1:'PC'});
  const result=mergeSubmission({...emptyEntry(),memo2:'Phone',rev:1},a.submission(KEY));
  assert.deepEqual(result.conflicts,[]);assert.equal(result.next.memo1,'PC');assert.equal(result.next.memo2,'Phone');
});
test('same field conflict preserves both values',()=>{
  const a=new MemoStore(memory(),'a');a.edit(KEY,{memo1:'PC'});
  const result=mergeSubmission({...emptyEntry(),memo1:'Phone',rev:1},a.submission(KEY));a.setConflict(KEY,result);
  assert.deepEqual(result.conflicts,['memo1']);assert.equal(a.view()[KEY].memo1,'PC');assert.equal(a.records[KEY].memo1,'Phone');
  a.resolve(KEY,'remote');assert.equal(a.view()[KEY].memo1,'Phone');assert.equal(Object.keys(a.pending).length,0);
});
test('typing while a write is in flight is retained and rebased',()=>{
  const a=new MemoStore(memory(),'a');a.edit(KEY,{memo1:'P'});const sent=a.submission(KEY);
  a.edit(KEY,{memo1:'PC'});a.acknowledge(KEY,sent,{...emptyEntry(),memo1:'P',rev:1});
  assert.equal(a.view()[KEY].memo1,'PC');assert.equal(a.pending[KEY].memo1.base,'P');
  assert.deepEqual(mergeSubmission(a.records[KEY],a.submission(KEY)).conflicts,[]);
});
test('empty deletion survives export and restore',()=>{
  const data={[KEY]:emptyEntry()};assert.deepEqual(decodeBackup(encodeBackup(data)),data);
  const a=new MemoStore(memory(),'a');a.receive({[KEY]:{...emptyEntry(),memo1:'old',rev:1}});a.importBackup(encodeBackup(data));
  assert.equal(a.view()[KEY].memo1,'');
});
test('offline changes survive reopening',()=>{
  const disk=memory(),a=new MemoStore(disk,'owner');a.edit(KEY,{memo1:'offline'});
  const b=new MemoStore(disk,'owner');assert.equal(b.view()[KEY].memo1,'offline');assert.equal(Object.keys(b.pending).length,1);
});
test('different account cache is isolated',()=>{
  const disk=memory();new MemoStore(disk,'owner').edit(KEY,{memo1:'private'});
  assert.deepEqual(new MemoStore(disk,'other').view(),{});
});
test('storage failure is visible and in-memory value survives for export',()=>{
  const a=new MemoStore({getItem:()=>null,setItem:()=>{throw Error('quota');}},'owner');a.edit(KEY,{memo1:'unsaved'});
  assert.ok(a.storageError);assert.equal(encodeBackup(a.view()).memos[KEY][0],'unsaved');
});
test('invalid backup rejected before mutation',()=>{
  const a=new MemoStore(memory(),'a');a.edit(KEY,{memo1:'safe'});
  assert.throws(()=>a.importBackup({marks:{'__proto__|x':{}}}));assert.equal(a.view()[KEY].memo1,'safe');
  assert.throws(()=>decodeBackup({memos:{[KEY]:['x'.repeat(4001),'']}}));
});
test('choosing mine rebases against server and can be written',()=>{
  const a=new MemoStore(memory(),'a');a.edit(KEY,{memo1:'PC'});
  a.setConflict(KEY,mergeSubmission({...emptyEntry(),memo1:'Phone',rev:1},a.submission(KEY)));
  a.resolve(KEY,'mine');const result=mergeSubmission(a.records[KEY],a.submission(KEY));
  assert.deepEqual(result.conflicts,[]);assert.equal(result.next.memo1,'PC');
});
test('marking pairs are stored as one atomic field',()=>{
  const a=new MemoStore(memory(),'a');const marks={cH:'box',pL:'box',cL:'ul',pH:'ul'};a.edit(KEY,{marks});
  assert.deepEqual(a.view()[KEY].marks,marks);assert.deepEqual(Object.keys(a.submission(KEY)),['marks']);
});
