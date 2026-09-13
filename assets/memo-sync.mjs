import {MemoStore, emptyEntry, encodeBackup, decodeBackup, mergeSubmission, FIELDS} from './memo-core.mjs';
import {syncConfig} from './firebase-config.mjs';

const ui = window.optboardMemo;
await ui.ready;
const button = document.getElementById('btnLogin');
const status = document.getElementById('syncStatus');
const conflictButton = document.getElementById('btnConflicts');
let store = null, currentUser = null, auth = null, db = null, sdk = null, stopListening = null;
let ready = false, busy = false, timer = null, lastError = '', retryDelay = 2000;
const legacy = ui.captureLegacy();
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fieldLabel = {marks:'마킹', memo1:'메모 1', memo2:'메모 2'};

function draw() {
  button.textContent = currentUser ? '로그아웃' : '개인 메모 로그인';
  const count = store ? Object.keys(store.pending).length : 0;
  const conflicts = store ? Object.keys(store.conflicts).length : 0;
  conflictButton.hidden = !conflicts;
  conflictButton.textContent = `수정 충돌 ${conflicts}건`;
  let text = '로그인 전 · 메모는 이 기기에 저장';
  if (!syncConfig.enabled) text = '이 기기에 저장 · 동기화 설정 전';
  else if (currentUser && !store) text = lastError || '본인 계정 확인 중';
  else if (store) {
    if (store.storageError) text = '기기 저장 실패 · 백업 파일을 저장해 주세요';
    else if (conflicts) text = '다른 기기의 수정과 충돌 · 내용 선택 필요';
    else if (lastError) text = lastError;
    else if (!navigator.onLine) text = `오프라인 · 전송 대기 ${count}건`;
    else if (!ready) text = '개인 메모 불러오는 중';
    else if (count) text = `동기화 대기 ${count}건`;
    else text = '개인 메모 동기화 완료';
    ui.showRecords(store.view(), true);
  }
  status.textContent = text;
  status.dataset.state = lastError || store?.storageError || conflicts ? 'error' : count ? 'pending' : 'ok';
}

function schedule(delay = 800) {
  clearTimeout(timer);
  timer = setTimeout(flush, delay);
}

async function flush() {
  if (!store || !ready || busy || !navigator.onLine || !currentUser) return;
  const activeStore = store, uid = currentUser.uid;
  busy = true;
  try {
    for (const key of Object.keys(activeStore.pending)) {
      if (activeStore !== store || uid !== currentUser?.uid) break;
      if (activeStore.conflicts[key]) continue;
      const sent = activeStore.submission(key);
      const ref = sdk.doc(db, 'users', uid, 'entries', key);
      const historyRef = sdk.doc(sdk.collection(db, 'users', uid, 'history'));
      const result = await sdk.runTransaction(db, async tx => {
        const snapshot = await tx.get(ref);
        const result = mergeSubmission(snapshot.exists() ? snapshot.data() : emptyEntry(), sent);
        if (!result.conflicts.length && result.changed) {
          if (snapshot.exists()) tx.set(historyRef, {entryKey:key, previous:result.current, savedAt:sdk.serverTimestamp()});
          tx.set(ref, {...result.next, updatedAt:sdk.serverTimestamp()});
        }
        return result;
      });
      if (result.conflicts.length) activeStore.setConflict(key, result);
      else activeStore.acknowledge(key, sent, result.next);
    }
    lastError = '';
    retryDelay = 2000;
  } catch (error) {
    lastError = error.code === 'permission-denied'
      ? '메모 접근 권한을 확인해 주세요 · 수정 내용은 기기에 보관'
      : '서버 연결 실패 · 수정 내용은 기기에 보관하고 재시도';
    retryDelay = Math.min(30000, retryDelay * 2);
  } finally {
    busy = false;
    draw();
    if (store && Object.keys(store.pending).some(key => !store.conflicts[key])) schedule(retryDelay);
  }
}

async function login() {
  if (!auth) return ui.toast('동기화 설정을 아직 불러오지 못했습니다');
  if (currentUser) {
    if (store && Object.keys(store.pending).length) {
      ui.toast('전송 대기 메모가 있습니다. 동기화하거나 백업한 뒤 로그아웃하세요');
      return;
    }
    await sdk.signOut(auth);
    return;
  }
  try {
    lastError = '';
    const provider = new sdk.GoogleAuthProvider();
    provider.setCustomParameters({prompt:'select_account'});
    await sdk.signInWithPopup(auth, provider);
  } catch (error) {
    if (!['auth/popup-closed-by-user', 'auth/cancelled-popup-request'].includes(error.code)) {
      lastError = error.code === 'auth/popup-blocked' ? '로그인 팝업을 허용해 주세요' : '로그인하지 못했습니다. 네트워크와 허용 도메인을 확인하세요';
      ui.toast(lastError);
    }
    draw();
  }
}

function downloadBackup() {
  const data = store ? encodeBackup(store.view()) : {...ui.captureLegacy(), formatVersion:2, exportedAt:new Date().toISOString()};
  const link = document.createElement('a');
  const url = URL.createObjectURL(new Blob([JSON.stringify(data)], {type:'application/json'}));
  link.href = url;
  link.download = `optboard-memos-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function importPreview(input, title = '메모 백업 불러오기') {
  let records;
  try { records = decodeBackup(input); } catch (error) { ui.toast(error.message); return; }
  const count = Object.keys(records).length;
  const place = store ? '본인 계정에 저장하고 다른 기기에도 반영합니다.' : '이 브라우저에 저장합니다.';
  ui.openCard(`<h2>${esc(title)}</h2><p>${count}개 행의 마킹·메모를 ${place}</p>
    <p>같은 행의 마킹·메모는 불러온 내용으로 바뀝니다. 다른 행은 유지됩니다.</p>
    <div class="row"><button class="btn" id="importCancel">취소</button><button class="btn primary" id="importApply">${count}개 행 가져오기</button></div>`);
  document.getElementById('importCancel').onclick = ui.closeCard;
  document.getElementById('importApply').onclick = () => {
    if (store) { store.importBackup(input); schedule(0); }
    else ui.importLocal(input);
    ui.closeCard();
    ui.toast('가져왔습니다. 원본 백업 파일은 보관해 주세요');
  };
}

function backupDialog() {
  const count = Object.keys(store ? store.view() : decodeBackup(ui.captureLegacy())).length;
  const legacyCount = Object.keys(decodeBackup(legacy)).length;
  ui.openCard(`<h2>개인 메모 보관</h2><p>현재 ${count}개 행의 마킹·메모가 있습니다. 백업 파일은 개인 폴더에 보관하세요.</p>
    <div class="row"><button class="btn primary" id="backupDownload">백업 파일 저장</button><button class="btn" id="backupImport">백업 파일 불러오기</button></div>
    ${store && legacyCount ? `<p>이 브라우저의 이전 메모 ${legacyCount}개 행도 가져올 수 있습니다.</p><button class="btn" id="legacyImport">이전 메모 가져오기</button>` : ''}
    ${store ? '<div class="row"><button class="btn" id="historyOpen">최근 수정 전 내용 보기</button></div>' : ''}
    <div class="row"><button class="btn" id="backupClose">닫기</button></div>`);
  document.getElementById('backupDownload').onclick = downloadBackup;
  document.getElementById('backupImport').onclick = () => document.getElementById('memoFilePick').click();
  document.getElementById('backupClose').onclick = ui.closeCard;
  const old = document.getElementById('legacyImport');
  if (old) old.onclick = () => importPreview(legacy, '이 브라우저의 이전 메모 가져오기');
  const history = document.getElementById('historyOpen');
  if (history) history.onclick = historyDialog;
}

async function historyDialog() {
  if (!store || !navigator.onLine) return ui.toast('로그인과 인터넷 연결이 필요합니다');
  try {
    const history = await sdk.getDocs(sdk.query(sdk.collection(db, 'users', currentUser.uid, 'history'),
      sdk.orderBy('savedAt', 'desc'), sdk.limit(20)));
    const rows = history.docs.map(item => item.data());
    ui.openCard(`<h2>최근 수정 전 내용</h2><p>최근 20건입니다. 복원도 새 수정으로 저장됩니다.</p>
      ${rows.length ? rows.map((row,i) => `<div class="history-item"><b>${esc(row.entryKey.replaceAll('|',' · '))}</b>
      <p>${esc(row.previous.memo1 || '(메모 1 없음)')}<br>${esc(row.previous.memo2 || '(메모 2 없음)')}</p>
      <button class="btn tiny" data-restore="${i}">이 내용 복원</button></div>`).join('') : '<p>아직 수정 이력이 없습니다.</p>'}
      <div class="row"><button class="btn" id="historyClose">닫기</button></div>`);
    document.getElementById('historyClose').onclick = ui.closeCard;
    document.querySelectorAll('[data-restore]').forEach(btn => {
      btn.onclick = () => {
        const row = rows[Number(btn.dataset.restore)];
        const input = encodeBackup({[row.entryKey]:row.previous});
        importPreview(input, '수정 전 내용 복원');
      };
    });
  } catch (_) { ui.toast('수정 이력을 불러오지 못했습니다'); }
}

function conflictsDialog() {
  if (!store) return;
  const keys = Object.keys(store.conflicts);
  const visible = store.view();
  const displayedRevisions = Object.fromEntries(keys.map(key => [key, store.records[key]?.rev]));
  ui.openCard(`<h2>두 기기에서 수정한 메모</h2><p>같은 항목이 서로 다르게 수정되었습니다. 두 내용 중 유지할 것을 선택하세요.</p>
    ${keys.map((key,i) => `<div class="history-item"><b>${esc(key.replaceAll('|',' · '))}</b>
      ${store.conflicts[key].map(field => `<p>${fieldLabel[field]}<br>이 기기: ${esc(typeof visible[key][field] === 'string' ? visible[key][field] : JSON.stringify(visible[key][field]))}<br>
      서버: ${esc(typeof store.records[key][field] === 'string' ? store.records[key][field] : JSON.stringify(store.records[key][field]))}</p>`).join('')}
      <div class="row"><button class="btn" data-conflict="${i}" data-choice="remote">서버 내용 유지</button><button class="btn primary" data-conflict="${i}" data-choice="mine">이 기기 내용 유지</button></div></div>`).join('')}
    <div class="row"><button class="btn" id="conflictClose">나중에 선택</button></div>`);
  document.getElementById('conflictClose').onclick = ui.closeCard;
  document.querySelectorAll('[data-conflict]').forEach(btn => {
    btn.onclick = () => {
      const key = keys[Number(btn.dataset.conflict)];
      if (store.records[key]?.rev !== displayedRevisions[key]) {
        ui.toast('서버 메모가 다시 변경되었습니다. 내용을 다시 확인해 주세요');
        return conflictsDialog();
      }
      store.resolve(key, btn.dataset.choice);
      schedule(0);
      if (Object.keys(store.conflicts).length) conflictsDialog(); else ui.closeCard();
    };
  });
}

window.optboardSync = {
  isActive: () => Boolean(store),
  edit(key, patch) { store.edit(key, patch); schedule(); },
  downloadBackup,
  importBackup: input => importPreview(input),
};
button.onclick = login;
conflictButton.onclick = conflictsDialog;
document.getElementById('btnBackup').onclick = backupDialog;
document.getElementById('memoFilePick').onchange = async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) return ui.toast('백업 파일은 20MB 이하여야 합니다');
  try { importPreview(JSON.parse(await file.text())); } catch (_) { ui.toast('JSON 백업 파일을 읽지 못했습니다'); }
};
window.addEventListener('online', () => { draw(); schedule(0); });
window.addEventListener('offline', draw);
window.addEventListener('beforeunload', event => {
  if (store?.storageError && Object.keys(store.pending).length) { event.preventDefault(); event.returnValue = ''; }
});

draw();
if (syncConfig.enabled) {
  button.disabled = true;
  try {
    const [appSDK, authSDK, dbSDK] = await Promise.all([
      import('https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js'),
      import('https://www.gstatic.com/firebasejs/12.19.0/firebase-auth.js'),
      import('https://www.gstatic.com/firebasejs/12.19.0/firebase-firestore.js')
    ]);
    sdk = {...appSDK, ...authSDK, ...dbSDK};
    const app = sdk.initializeApp(syncConfig.firebase);
    auth = sdk.getAuth(app);
    db = sdk.getFirestore(app);
    sdk.onAuthStateChanged(auth, async user => {
      if (stopListening) stopListening();
      stopListening = null;
      clearTimeout(timer);
      ready = false;
      store = null;
      currentUser = user;
      lastError = '';
      ui.showRecords({}, false);
      if (!user) return draw();
      if (!syncConfig.ownerUid || user.uid !== syncConfig.ownerUid) {
        lastError = syncConfig.ownerUid ? '허용된 본인 계정으로 로그인해 주세요' : '본인 계정 등록을 완료해야 합니다';
        status.dataset.setupUid = syncConfig.ownerUid ? '' : user.uid;
        return draw();
      }
      try {
        store = new MemoStore(localStorage, 'optboard.private.v2.' + user.uid, draw);
        const listeningStore = store;
        draw();
        stopListening = sdk.onSnapshot(sdk.collection(db, 'users', user.uid, 'entries'),
          {includeMetadataChanges:true}, snapshot => {
            if (store !== listeningStore || currentUser?.uid !== user.uid) return;
            const records = {};
            snapshot.docs.forEach(item => { records[item.id] = item.data(); });
            store.receive(records);
            if (!snapshot.metadata.fromCache) { ready = true; lastError = ''; schedule(0); }
            draw();
          }, error => {
            if (store !== listeningStore || currentUser?.uid !== user.uid) return;
            lastError = error.code === 'permission-denied' ? '메모 접근 권한을 확인해 주세요' : '개인 메모 연결이 끊겼습니다';
            draw();
          });
      } catch (_) { lastError = '기기 메모를 읽지 못했습니다. 기존 데이터를 보존하고 백업을 확인해 주세요'; draw(); }
    });
    button.disabled = false;
  } catch (_) {
    status.textContent = '동기화 연결 실패 · 이 기기의 메모와 백업을 사용할 수 있습니다';
    button.disabled = false;
  }
} else {
  button.onclick = () => ui.toast('Firebase 프로젝트와 본인 계정 설정이 완료되면 사용할 수 있습니다');
}
