const CACHE='faro-familia-v15';
const ASSETS=['/','/assets/app.css?v=2','/assets/events.css?v=1','/assets/people.css?v=1','/assets/care.css?v=1','/assets/patient.css?v=1','/assets/app.js?v=11','/assets/manifest.webmanifest'];

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
    event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));
  }
});
