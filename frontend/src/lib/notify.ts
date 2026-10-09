export const notificationsEnabled = () => localStorage.getItem('cm-desktop-notify') !== 'off';

export function requestNotifyPermission() {
  try {
    if (notificationsEnabled() && 'Notification' in window && Notification.permission === 'default') {
      void Notification.requestPermission().catch(() => {});
    }
  } catch {
    /* Browser notifications are optional. */
  }
}

export function desktopNotify(title: string, body: string) {
  try {
    if (
      !notificationsEnabled() ||
      !('Notification' in window) ||
      Notification.permission !== 'granted' ||
      document.visibilityState !== 'hidden'
    )
      return;
    const notification = new Notification(title, { body, tag: 'occ-run' });
    notification.onclick = () => {
      window.focus();
      notification.close();
    };
  } catch {
    /* Permission or platform may make notifications unavailable. */
  }
}
