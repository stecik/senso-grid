import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {nextTick} from 'vue'

vi.mock('./api',()=>({api:vi.fn(),write:vi.fn()}))
vi.mock('../i18n',()=>({i18n:{global:{locale:{value:'cs'}}}}))

const media={matches:false,addEventListener:vi.fn()}
const themeMeta={setAttribute:vi.fn()}
const root={classList:{toggle:vi.fn()},lang:''}
let onMediaChange:()=>void

beforeEach(()=>{
  vi.resetModules()
  vi.clearAllMocks()
  media.matches=false
  onMediaChange=()=>{}
  media.addEventListener.mockImplementation((_event:string,callback:()=>void)=>{onMediaChange=callback})
  vi.stubGlobal('matchMedia',()=>media)
  vi.stubGlobal('navigator',{onLine:true})
  vi.stubGlobal('window',{addEventListener:vi.fn()})
  vi.stubGlobal('document',{documentElement:root,querySelector:vi.fn(()=>themeMeta)})
})
afterEach(()=>vi.unstubAllGlobals())

describe('PWA system bar follows the active application theme',()=>{
  it('uses the dark header color when the system starts in dark mode',async()=>{
    media.matches=true
    await import('./state')
    expect(root.classList.toggle).toHaveBeenLastCalledWith('dark',true)
    expect(themeMeta.setAttribute).toHaveBeenLastCalledWith('content','#141f32')
  })
  it('updates the bar when the user changes the app theme',async()=>{
    const {state}=await import('./state')
    state.settings.theme='dark'
    await nextTick()
    expect(themeMeta.setAttribute).toHaveBeenLastCalledWith('content','#141f32')
    state.settings.theme='light'
    await nextTick()
    expect(root.classList.toggle).toHaveBeenLastCalledWith('dark',false)
    expect(themeMeta.setAttribute).toHaveBeenLastCalledWith('content','#ffffff')
  })
  it('follows system changes only when system theme is selected',async()=>{
    const {state}=await import('./state')
    expect(themeMeta.setAttribute).toHaveBeenLastCalledWith('content','#ffffff')
    media.matches=true
    onMediaChange()
    expect(themeMeta.setAttribute).toHaveBeenLastCalledWith('content','#141f32')
    state.settings.theme='light'
    await nextTick()
    media.matches=false
    onMediaChange()
    media.matches=true
    onMediaChange()
    expect(root.classList.toggle).toHaveBeenLastCalledWith('dark',false)
    expect(themeMeta.setAttribute).toHaveBeenLastCalledWith('content','#ffffff')
  })
  it('keeps applying the theme when no theme-color metadata exists',async()=>{
    vi.mocked(document.querySelector).mockReturnValue(null)
    const {state}=await import('./state')
    state.settings.theme='dark'
    await nextTick()
    expect(root.classList.toggle).toHaveBeenLastCalledWith('dark',true)
  })
})
