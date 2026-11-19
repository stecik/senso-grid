import { reactive, watch } from 'vue'
import { api, write } from './api'
import type {Auth,Settings} from './types'
import { i18n } from '../i18n'
export const state=reactive({auth:null as Auth|null,settings:{language:'cs',theme:'system',temperature_unit:'C',push_enabled:false,heatmap:{temperature:[18,25],humidity:[30,70]}} as Settings,online:navigator.onLine})
const media=matchMedia('(prefers-color-scheme: dark)')
function applyTheme(){
  const dark=state.settings.theme==='dark'||(state.settings.theme==='system'&&media.matches)
  document.documentElement.classList.toggle('dark',dark)
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute('content',dark?'#141f32':'#ffffff')
  document.documentElement.lang=state.settings.language
  i18n.global.locale.value=state.settings.language
}
watch(()=>state.settings,applyTheme,{deep:true,immediate:true});media.addEventListener('change',applyTheme)
window.addEventListener('online',()=>{state.online=true});window.addEventListener('offline',()=>{state.online=false})
export async function refreshAuth(){state.auth=await api<Auth>('/auth/status');if(state.auth.authenticated)state.settings=await api<Settings>('/settings')}
export async function saveSettings(patch:Partial<Settings>){state.settings=await write<Settings>('/settings',patch,'PATCH')}
export function formatValue(value:number|null|undefined,metric:'temperature'|'humidity',digits=1){if(value==null||!Number.isFinite(value))return '—';const v=metric==='temperature'&&state.settings.temperature_unit==='F'?value*9/5+32:value;return new Intl.NumberFormat(state.settings.language,{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(v)}
export function unit(metric:'temperature'|'humidity'){return metric==='humidity'?'%':'°'+state.settings.temperature_unit}
export function time(value:string|null|undefined){if(!value)return '—';return new Intl.DateTimeFormat(state.settings.language,{dateStyle:'short',timeStyle:'short'}).format(new Date(value))}
