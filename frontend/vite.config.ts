import {defineConfig} from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import {readdirSync,readFileSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {createHash} from 'node:crypto'
function offlineShell(){return {name:'sensogrid-offline-shell',closeBundle(){const root=join(import.meta.dirname,'dist');const list=(dir:string):string[]=>readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?list(join(dir,entry.name)):[join(dir,entry.name)]);const assets=list(root).map(path=>'/'+path.slice(root.length+1).replaceAll('\\','/')).filter(path=>path!=='/sw.js'&&/\.(js|css|svg|png|woff2|webmanifest)$/.test(path));const hash=createHash('sha256').update(readFileSync(join(root,'index.html'))).digest('hex').slice(0,12);const source=readFileSync(join(root,'sw.js'),'utf8').replace("const PRECACHE = ['/','/index.html','/icon.svg','/manifest.webmanifest'];",'const PRECACHE = '+JSON.stringify(['/','/index.html',...assets])+';').replace("const CACHE = 'sensogrid-shell-dev';","const CACHE = 'sensogrid-shell-"+hash+"';");writeFileSync(join(root,'sw.js'),source)}}}
export default defineConfig({plugins:[vue(),tailwindcss(),offlineShell()],server:{proxy:{'/api':'http://127.0.0.1:8000','/health':'http://127.0.0.1:8000'}},build:{target:'es2022',rollupOptions:{output:{manualChunks:{charts:['echarts','vue-echarts']}}}}})
