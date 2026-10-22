import {shallowRef} from 'vue'
interface InstallPrompt extends Event {prompt:()=>Promise<void>;userChoice:Promise<{outcome:'accepted'|'dismissed'}>}
export const installPrompt=shallowRef<InstallPrompt|null>(null)
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt.value=event as InstallPrompt})
window.addEventListener('appinstalled',()=>{installPrompt.value=null})
export async function installApp(){if(!installPrompt.value)return;await installPrompt.value.prompt();await installPrompt.value.userChoice;installPrompt.value=null}
