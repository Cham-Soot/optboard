// Firebase web configuration is public connection metadata, never an admin credential.
// Access is restricted to this owner's UID by the deployed Firestore rules.
export const syncConfig = {
  enabled: true,
  ownerUid: 'joCqZrG5yAgzJn0cigwozuVZDEs2',
  firebase: {
    projectId: 'optboard-memo',
    appId: '1:822651847007:web:70e73e6289f63b13b176ea',
    apiKey: 'AIzaSyC-KIUrz1JT9VqE_WGS2eS9fwuHa5aC8po',
    authDomain: 'optboard-memo.firebaseapp.com',
    messagingSenderId: '822651847007'
  }
};
