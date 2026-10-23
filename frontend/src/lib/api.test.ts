import {afterEach,expect,it,vi} from 'vitest'
import {diagnosticArchive} from './api'

afterEach(()=>vi.unstubAllGlobals())
it('downloads diagnostics as binary with the existing session',async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response(new Uint8Array([80,75,3,4]),{headers:{'Content-Type':'application/zip'}}))
 vi.stubGlobal('fetch',fetch)
 const blob=await diagnosticArchive()
 expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([80,75,3,4])
 expect(fetch).toHaveBeenCalledWith('/api/diagnostics',expect.objectContaining({credentials:'same-origin'}))
})
it('keeps authentication errors out of the downloaded file',async()=>{
 const dispatchEvent=vi.fn()
 vi.stubGlobal('window',{dispatchEvent})
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'Authentication required'}),{status:401})))
 await expect(diagnosticArchive()).rejects.toThrow('Authentication required')
 expect(dispatchEvent).toHaveBeenCalledOnce()
})
