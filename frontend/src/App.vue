<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {useI18n} from 'vue-i18n'
import {state,refreshAuth} from './lib/state'
import {api,errorMessage,write} from './lib/api'
import type {Auth} from './lib/types'
import Icon from './components/Icon.vue'
import Notice from './components/Notice.vue'
import Brand from './components/Brand.vue'
const {t}=useI18n()
const loading=ref(true),error=ref(''),busy=ref(false),username=ref(''),password=ref('')
const nav=[{path:'/',label:'dashboard',icon:'grid'},{path:'/history',label:'history',icon:'history'},{path:'/floorplan',label:'floorplan',icon:'plan'},{path:'/alerts',label:'alerts',icon:'bell'},{path:'/settings',label:'settings',icon:'settings'}]
async function initialize(){error.value='';loading.value=true;try{await refreshAuth()}catch(e){error.value=errorMessage(e)}finally{loading.value=false}}
async function authenticate(){busy.value=true;error.value='';try{await write<Auth>(state.auth?.setup_required?'/auth/setup':'/auth/login',{username:username.value,password:password.value});password.value='';await refreshAuth()}catch(e){error.value=errorMessage(e)}finally{busy.value=false}}
async function logout(){busy.value=true;try{await api('/auth/logout',{method:'POST'});state.auth={setup_required:false,authenticated:false,user:null}}catch(e){error.value=errorMessage(e)}finally{busy.value=false}}
function unauthorized(){if(state.auth?.authenticated){state.auth={setup_required:false,authenticated:false,user:null};error.value=t('authRequired')}}
onMounted(()=>{void initialize();window.addEventListener('sensogrid:unauthorized',unauthorized)})
onUnmounted(()=>window.removeEventListener('sensogrid:unauthorized',unauthorized))
</script>

<template>
  <div v-if="loading" class="boot">
    <div class="brand"><Brand /></div>
    <p class="muted">{{ t('authWorking') }}</p>
  </div>

  <main v-else-if="!state.auth?.authenticated" class="auth-layout">
    <div class="auth-grid" aria-hidden="true">
      <svg class="auth-contour" viewBox="0 0 1000 800" fill="none">
        <path d="M110 150H490V310H760V640H110V150ZM110 400H490M490 310V640M280 400V640" />
        <path d="M175 220H420V365H685V565H355V470H175V220Z" class="contour-inner" />
        <circle cx="280" cy="275" r="7" /><circle cx="600" cy="475" r="7" /><circle cx="235" cy="530" r="7" />
      </svg>
    </div>
    <section class="auth-stage">
      <a class="brand auth-brand" href="/"><Brand /></a>
      <div class="auth-form">
        <div class="auth-label"><Icon name="thermo" :size="18" /><span>{{ t('local') }}</span></div>
        <h1>{{ t(state.auth?.setup_required?'setupTitle':'loginTitle') }}</h1>
        <p class="muted">{{ t(state.auth?.setup_required?'setupNote':'loginNote') }}</p>
        <Notice v-if="error" kind="error">{{ t(state.auth?'authFailed':'error') }}<details><summary>{{ t('details') }}</summary>{{ error }}</details></Notice>
        <form v-if="state.auth" @submit.prevent="authenticate">
          <label>{{ t('username') }}<input v-model="username" name="username" autocomplete="username" required maxlength="80" autofocus></label>
          <label>{{ t('password') }}<input v-model="password" type="password" name="password" :autocomplete="state.auth.setup_required?'new-password':'current-password'" :minlength="state.auth.setup_required?8:1" :maxlength="256" :pattern="state.auth.setup_required?'(?=.*\\p{Lu})(?=.*\\p{Ll})(?=.*[\\p{P}\\p{S}]).{8,256}':undefined" required><small v-if="state.auth.setup_required">{{ t('passwordHint') }}</small></label>
          <button class="primary wide" :disabled="busy">{{ t(busy?'loading':state.auth.setup_required?'setup':'login') }}<Icon name="arrow" /></button>
        </form>
        <button v-else class="primary" @click="initialize">{{ t('retry') }}</button>
      </div>
      <footer class="auth-footer">
        <span class="auth-local"><i></i>{{ t('localOnly') }}</span>
        <button class="text-button language-switch" @click="state.settings.language=state.settings.language==='cs'?'en':'cs'">{{ state.settings.language==='cs'?'English':'Čeština' }}</button>
      </footer>
    </section>
  </main>

  <div v-else class="app-shell">
    <header class="app-header">
      <div class="header-inner">
        <RouterLink class="brand" to="/"><Brand /></RouterLink>
        <nav class="desktop-nav" aria-label="Main">
          <RouterLink v-for="item in nav" :key="item.path" :to="item.path" :class="{exact:$route.path===item.path}">
            <Icon :name="item.icon" :size="17" /><span>{{ t(item.label) }}</span>
          </RouterLink>
        </nav>
        <div class="header-account">
          <span class="local-indicator"><i :class="{disconnected:!state.online}"></i><span>{{ t(state.online?'local':'offline') }}</span></span>
          <span class="account-name">{{ state.auth.user?.username }}</span>
          <button class="icon-button" :aria-label="t('logout')" :title="t('logout')" :disabled="busy" @click="logout"><Icon name="logout" :size="18" /></button>
        </div>
      </div>
    </header>
    <div class="main-column">
      <Notice v-if="!state.online" class="connection-notice" kind="error">{{ t('connectionLost') }}</Notice>
      <RouterView v-slot="{Component}"><Transition name="page" mode="out-in"><component :is="Component" /></Transition></RouterView>
    </div>
    <nav class="bottom-nav" aria-label="Main">
      <RouterLink v-for="item in nav" :key="item.path" :to="item.path" :class="{exact:$route.path===item.path}">
        <Icon :name="item.icon" /><span>{{ t(item.label) }}</span>
      </RouterLink>
    </nav>
  </div>
</template>
