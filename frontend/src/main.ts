import {createApp} from 'vue'
import {createRouter,createWebHistory} from 'vue-router'
import App from './App.vue'
import Dashboard from './pages/Dashboard.vue'
import {i18n} from './i18n'
import './style.css'
import './lib/pwa'
import {dialogDirective} from './lib/dialog'
const router=createRouter({history:createWebHistory(),routes:[{path:'/',component:Dashboard},{path:'/history',component:()=>import('./pages/History.vue')},{path:'/floorplan',component:()=>import('./pages/Editor.vue')},{path:'/alerts',component:()=>import('./pages/Alerts.vue')},{path:'/settings',component:()=>import('./pages/Settings.vue')}]})
createApp(App).use(router).use(i18n).directive('dialog',dialogDirective).mount('#app')
if('serviceWorker' in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{/* unsupported origin: monitoring remains available */}))
