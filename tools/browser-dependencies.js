import { parsePhoneNumberFromString } from 'libphonenumber-js/max';
import Papa from 'papaparse';
import {observeResize} from './resize-observer.cjs';
import { createIcons, LayoutDashboard, Building2, Users, ChartNoAxesCombined, Search, Settings2, SlidersHorizontal, ListFilter, Wrench, Target, RefreshCw } from 'lucide';
const features = new Map();
function loadFeature(name) {
  if (!['charts','pdf'].includes(name)) return Promise.reject(Error('Biblioteca desconhecida'));
  if (!features.has(name)) features.set(name,new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src='/vendor/radar-'+name+'.js?v=1';
    script.onload=()=>resolve();script.onerror=()=>{features.delete(name);script.remove();reject(Error('Biblioteca local indisponível. Recarregue o Radar.'));};document.head.append(script);
  }));
  return features.get(name);
}
window.RadarLibraries = { parsePhoneNumberFromString, Papa, loadFeature, observeResize,
  icons: () => createIcons({ icons: { LayoutDashboard, Building2, Users, ChartNoAxesCombined, Search, Settings2, SlidersHorizontal, ListFilter, Wrench, Target, RefreshCw } }) };
