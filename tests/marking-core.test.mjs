import test from 'node:test';
import assert from 'node:assert/strict';
import {deriveMarks, boxPair, planKey} from '../assets/marking-core.mjs';
const dates=['2026-09-07','2026-09-08','2026-09-09','2026-09-10','2026-09-11'];
const key=(s,d)=>`2610|${s}|${dates[d]}`;
const plans=(cell='cH')=>({[planKey('2610',dates[0])]:{anchor:cell}});
const make=(lows=[10,9,8,8.5,9],highs=[15,14,13,14,13])=>({expiry:'2610',dates,strikes:[1000],rows:dates.map((date,i)=>({date,strike:1000,c:[11,highs[i],lows[i],11],p:[12,20-i,10+i,12]}))});
test('rebound boxes the previous trading row, never the confirmation row',()=>{
  const result=deriveMarks(make(),plans());
  assert.deepEqual(result.marks[key(1000,2)],boxPair('cL'));
  assert.equal(result.marks[key(1000,3)].cH,'box'); // next session confirms a high turn here
  assert.deepEqual(result.events[key(1000,2)],{cell:'cL',confirmedOn:dates[3]});
  assert.equal(result.marks[key(1000,4)].cL,'ul');
  assert.equal(result.marks[key(1000,4)].cH,undefined);
});
test('alternates low and high turns and mirrors the opposite option side',()=>{
  const result=deriveMarks(make(),plans());
  assert.deepEqual(result.marks[key(1000,3)],boxPair('cH'));
  assert.deepEqual(result.events[key(1000,3)],{cell:'cH',confirmedOn:dates[4]});
  assert.equal(result.marks[key(1000,2)].pH,'box');
  assert.equal(result.marks[key(1000,3)].pL,'box');
});
test('each strike computes its own turning date from one shared start',()=>{
  const doc=make();doc.strikes.push(1002.5);
  doc.rows.push(...make([10,9,9.5,9.6,9.7],[15,16,17,18,19]).rows.map(r=>({...r,strike:1002.5})));
  const result=deriveMarks(doc,plans());
  assert.equal(result.events[key(1000,2)].confirmedOn,dates[3]);
  assert.equal(result.events[key(1002.5,1)].confirmedOn,dates[2]);
  assert.deepEqual(result.marks[key(1002.5,0)],boxPair('cH'));
});
test('equal prices do not reverse; the last tied row is the pivot',()=>{
  const result=deriveMarks(make([10,9,9,9,9.5],[15,15,15,15,15]),plans());
  assert.deepEqual(Object.keys(result.events),[key(1000,3)]);
});
test('put start tracks put prices instead of the call signal',()=>{
  const doc=make();const highs=[20,21,22,21,20];
  doc.rows.forEach((r,i)=>{r.p=[15,highs[i],12+i,15];});
  const result=deriveMarks(doc,plans('pL'));
  assert.deepEqual(result.events[key(1000,2)],{cell:'pH',confirmedOn:dates[3]});
  assert.deepEqual(result.marks[key(1000,2)],boxPair('pH'));
});
test('missing and known invalid prices do not produce a comparison across the gap',()=>{
  const doc=make([10,9,null,11,10],[15,15,15,15,15]);
  assert.deepEqual(deriveMarks(doc,plans()).events,{});
  doc.rows[2].c[2]=8;doc.collection={[dates[2]]:{contracts:{'1000|c':{status:'invalid'}}}};
  assert.deepEqual(deriveMarks(doc,plans()).events,{});
});
test('no-trade prices and missing opposite prices remain unmarked',()=>{
  const doc=make();doc.rows[0].p=[null,null,null,null];
  doc.collection={[dates[1]]:{contracts:{'1000|c':{status:'no_trade'}}}};
  const result=deriveMarks(doc,plans());
  assert.equal(result.marks[key(1000,0)].pL,undefined);
  assert.deepEqual(result.marks[key(1000,1)],{});
});
test('later manual start resets that date without rewriting the earlier segment',()=>{
  const doc=make(),input={...plans(),[planKey('2610',dates[3])]:{anchor:'pH'}};
  doc.rows[4].p[2]=doc.rows[3].p[2];
  const result=deriveMarks(doc,input);
  assert.equal(result.events[key(1000,2)],undefined);
  assert.deepEqual(result.marks[key(1000,3)],boxPair('pH'));
});
test('cleared starts, other months and dates outside the visible range do not leak',()=>{
  const doc=make();const input={[planKey('2610',dates[0])]:{anchor:''},[planKey('2611',dates[0])]:{anchor:'cH'}};
  assert.equal(deriveMarks(doc,input).covered.size,0);
  const later={[planKey('2610',dates[2])]:{anchor:'cL'}};
  assert.equal(deriveMarks(doc,later).covered.has(key(1000,1)),false);
});
test('a last row cannot become a confirmed pivot without a following quote',()=>{
  const result=deriveMarks(make([10,9,8,7,6],[15,15,15,15,15]),plans());
  assert.deepEqual(result.events,{});assert.equal(result.marks[key(1000,4)].cL,'ul');
});
