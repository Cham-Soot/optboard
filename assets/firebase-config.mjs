// Firebase web configuration is public connection metadata, never an admin credential.
// Keep disabled until the project and owner-only Firestore rules are verified.
export const syncConfig = {
  enabled: false,
  ownerUid: '',
  firebase: {}
};
