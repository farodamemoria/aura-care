const CACHE='faro-familia-v35';
const ASSETS=['/','/assets/app.css?v=3','/assets/events.css?v=2','/assets/people.css?v=2','/assets/care.css?v=2','/assets/patient.css?v=2','/assets/family.css?v=4','/assets/agenda.css?v=2','/assets/tokens.css?v=1','/assets/logo-light.svg','/assets/logo-dark.svg','/assets/icon.svg','/assets/icon-180.png','/assets/icon-192.png','/assets/icon-512.png','/assets/app.js?v=27','/assets/manifest.webmanifest'];

self.addEventListener('install',event=>{
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)));
});

self.addEventListener('activate',event=>{
  event.waitUntil(
    caches.keys()
      .then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))
      .then(()=>self.clients.claim()),
  );
});

self.addEventListener('fetch',event=>{
  if(event.request.method==='GET'){
    event.respondWith(fetch(event.request).then(response=>{
      const copy=response.clone();
      caches.open(CACHE).then(cache=>cache.put(event.request,copy)).catch(()=>{});
      return response;
    }).catch(()=>caches.match(event.request).then(cached=>cached||Response.error())));
  }
});
