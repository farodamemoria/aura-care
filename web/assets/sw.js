const CACHE='faro-familia-v67';
const ASSETS=['/assets/app.css?v=8','/assets/events.css?v=3','/assets/people.css?v=2','/assets/care.css?v=2','/assets/patient.css?v=2','/assets/family.css?v=4','/assets/agenda.css?v=2','/assets/tokens.css?v=8','/assets/logo-light.svg','/assets/logo-dark.svg','/assets/icon.svg','/assets/icon-180.png','/assets/icon-192.png','/assets/icon-512.png','/assets/app.js?v=55','/assets/manifest.webmanifest'];

// KAN-203: el documento del portal y los datos personales nunca se guardan en la cache del
// navegador; solo se cachean los estaticos publicos para que el portal cargue rapido.
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
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||!url.pathname.startsWith('/assets/')){
    return;
  }
  event.respondWith(
    caches.match(event.request).then(cached=>{
      const network=fetch(event.request).then(response=>{
        if(response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy)).catch(()=>{});}
        return response;
      });
      return cached||network;
    }).catch(()=>caches.match(event.request).then(cached=>cached||Response.error())),
  );
});
