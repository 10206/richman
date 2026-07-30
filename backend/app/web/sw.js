// 리치시그널 서비스 워커 — 오프라인 셸 캐시 + 웹 푸시 수신
const VERSION = 'richsignal-v2';
const SHELL = [
  '/',
  '/index.html',
  '/styles.css',
  '/app.js',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// API/외부 요청은 항상 네트워크(SW 미개입). 나머지 동일 출처 자산은 네트워크 우선 +
// 성공 시 캐시 갱신, 실패(오프라인) 시에만 캐시 폴백 → 배포한 새 코드가 즉시 반영됨.
self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/health') return;

  event.respondWith(
    fetch(request)
      .then((resp) => {
        const copy = resp.clone();
        caches.open(VERSION).then((c) => c.put(request, copy)).catch(() => {});
        return resp;
      })
      .catch(() => caches.match(request).then((c) => c || caches.match('/index.html')))
  );
});

// 웹 푸시 수신 → 알림 표시
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: '리치시그널', body: event.data ? event.data.text() : '' }; }
  const title = data.title || '리치시그널';
  const options = {
    body: data.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    tag: data.tag || 'richsignal',
    renotify: true,
    data: { url: data.url || '/', market: data.market || null, sector: data.sector || null },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// 알림 클릭 → 앱 열기(이미 열려 있으면 포커스)
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) { client.navigate(target); return client.focus(); }
      }
      return self.clients.openWindow(target);
    })
  );
});
