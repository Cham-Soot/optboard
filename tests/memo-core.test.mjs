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

const PLAN='2610|plan|2026-09-11';
test('v3 backup roundtrips colors and active or cleared shared starts',()=>{
  const rows={[KEY]:{...emptyEntry(),colors:{cH:'green',pL:'yellow'}},[PLAN]:{anchor:'cH',rev:0},'2611|plan|2026-09-11':{anchor:'',rev:0}};
  assert.deepEqual(decodeBackup(encodeBackup(rows)),rows);
});
test('old backup import preserves new colors and unrelated start points',()=>{
  const a=new MemoStore(memory(),'a');a.edit(KEY,{colors:{cH:'blue'},memo1:'before'});a.edit(PLAN,{anchor:'pL'});
  a.importBackup({marks:{[KEY]:{cH:'box'}},memos:{[KEY]:['old','']}});
  assert.deepEqual(a.view()[KEY].colors,{cH:'blue'});assert.equal(a.view()[PLAN].anchor,'pL');
});
test('v2 cache migration preserves pending edits without modifying the original cache',()=>{
  const disk=memory(),old=JSON.stringify({version:2,records:{[KEY]:{marks:{},memo1:'saved',memo2:'',rev:1}},pending:{[KEY]:{memo1:{base:'saved',value:'offline',id:'old'}}}});
  disk.setItem('v2',old);const a=new MemoStore(disk,'v3',()=>{},'v2');a.edit(PLAN,{anchor:'cL'});
  assert.equal(a.view()[KEY].memo1,'offline');assert.equal(disk.getItem('v2'),old);
  assert.equal(new MemoStore(disk,'v3').view()[PLAN].anchor,'cL');
});
test('competing start edits preserve both choices and resolve with revision checks',()=>{
  const a=new MemoStore(memory(),'a');a.edit(PLAN,{anchor:'cH'});
  const result=mergeSubmission({anchor:'pL',rev:1},a.submission(PLAN));a.setConflict(PLAN,result);
  assert.deepEqual(result.conflicts,['anchor']);assert.equal(a.view()[PLAN].anchor,'cH');
  a.resolve(PLAN,'mine');assert.equal(mergeSubmission(a.records[PLAN],a.submission(PLAN)).next.rev,2);
});
test('color changes merge with independent memo edits',()=>{
  const a=new MemoStore(memory(),'a');a.edit(KEY,{colors:{cL:'red'}});
  const result=mergeSubmission({...emptyEntry(),memo1:'phone',rev:1},a.submission(KEY));
  assert.equal(result.next.memo1,'phone');assert.deepEqual(result.next.colors,{cL:'red'});
});
test('invalid colors and mixed plan shapes fail before changing stored data',()=>{
  const a=new MemoStore(memory(),'a');a.edit(KEY,{memo1:'keep'});const before=JSON.stringify(a.view());
  assert.throws(()=>a.edit(KEY,{memo1:'bad',colors:{cH:'purple'}}));
  assert.throws(()=>a.edit(PLAN,{marks:{}}));assert.throws(()=>a.edit(KEY,{anchor:'cH'}));
  assert.throws(()=>a.importBackup({plans:{[PLAN]:'other'}}));
  assert.equal(JSON.stringify(a.view()),before);
});
