const CACHE='radar-shell-v80';
const ASSETS=['/style.css','/visual.css','/lead-layout.css','/company-layout.css','/company-layout.js','/segmentation.css','/commercial-taxonomy.js','/segmentation.js','/campaign-presets.js','/commercial-tools.js','/commercial-tools.css','/bi-integrated.css','/app.js','/team.js','/bi-lab.js','/auth.js','/manifest.webmanifest','/icon.svg','/fonts/Inter-Latin.woff2','/vendor/radar-libraries.js','/vendor/radar-charts.js','/vendor/radar-pdf.js','/tools-core.js','/radar-tools.js','/radar-tools.css','/radar-report.js','/report-studio.js','/radar-charts.js'];
ASSETS.push('/react-login.js','/react-login.css','/react-discovery.js','/react-discovery.css','/react-overview.js','/react-overview.css');
ASSETS.push('/runtime.js','/runtime.css');
ASSETS.push('/react-help.js','/help-center.css','/prospect-qualification.js');
ASSETS.push('/react-sales-ops.js','/sales-ops.css');
ASSETS.push('/radar-polish.css','/bi-metrics.js');
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||!ASSETS.includes(url.pathname))return;
  event.respondWith(fetch(event.request).then(response=>{if(response.ok&&!response.redirected){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy));}return response}).catch(()=>caches.match(event.request)));
});
