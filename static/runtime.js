/* Public parameters only. No keys, credentials or account lists here. */
window.RadarRuntimeReady=(async()=>{
  try{
    const response=await fetch('/api/runtime',{credentials:'same-origin',cache:'no-store'});if(!response.ok)return;
    const config=await response.json();window.RadarRuntime=config;
    document.documentElement.dataset.serproVisible=String(config.serpro_visible);
    document.documentElement.dataset.animations=String(config.animations);
    if(!localStorage.getItem('radar-theme')){if(typeof setTheme==='function')setTheme(config.default_theme,false);else document.documentElement.dataset.theme=config.default_theme;}
    const footer=document.querySelector('.content>footer');if(footer)footer.textContent=config.copyright.replaceAll('{ano}',String(new Date().getFullYear()));
    const brand=document.querySelector('.sidebar .brand strong');if(brand&&config.site_name!=='Radar CNPJ')brand.textContent=config.site_name;
    document.getElementById('portfolioAddTestLead')?.toggleAttribute('hidden',!config.test_leads);
    if(config.is_admin){const nav=document.querySelector('.primary-navigation');if(nav&&!nav.querySelector('[href="/admin"]')){const link=document.createElement('a');link.className='nav-item';link.href='/admin';link.innerHTML='<span aria-hidden="true">⚙</span><span><b>Administração</b><small>Parâmetros do Radar</small></span>';nav.append(link);}}
    const protectNavigation=e=>{if(e.detail?.view==='monitor'&&!config.serpro_visible&&typeof navigateToSection==='function')navigateToSection('dashboard');};
    window.addEventListener('radar:navigate',protectNavigation);
    if(location.hash==='#monitor'&&!config.serpro_visible&&typeof navigateToSection==='function')navigateToSection('dashboard');
    window.dispatchEvent(new Event('radar:runtime'));
  }catch(_){/* Existing app remains available when configuration cannot be fetched. */}
})();
