import {describe,it,expect} from 'vitest'
import {mergeDiscovery,failedPreview,restoreDiscovery,sensorCatalogue} from './discovery'
import type {Discovered,Sensor} from './types'
const found:Discovered={name:'LT_room',address:'AA:BB',rssi:-60,protocol:'lt_thermometer',service_uuids:[],manufacturer_data:{},service_data:{},temperature:22.4,humidity:47,timestamp:'2026-10-22T18:00:00Z',available:true}

it('uses current BTHome availability and protocol instead of cached LT data',()=>{
 const result=mergeDiscovery([found],[{...found,protocol:'bthome_v2',available:true,battery_percent:90}])
 expect(result[0]).toMatchObject({protocol:'bthome_v2',available:true,battery_percent:90})
})

it('does not revive an unavailable sighting from cached readings',()=>{
 const result=mergeDiscovery([found],[{...found,available:false}])
 expect(result[0]?.available).toBe(false)
})
describe('discovery survives temporary loss',()=>{
 it('keeps a missing sensor and its last measurement after an empty scan',()=>{
  const result=mergeDiscovery([found],[])
  expect(result).toHaveLength(1)
  expect(result[0]).toMatchObject({name:'LT_room',address:'AA:BB',temperature:22.4,humidity:47,available:false,seen_in_scan:false})
 })
 it('merges repeat sightings without losing a known protocol or creating duplicates',()=>{
  const result=mergeDiscovery([found],[{...found,address:'aa:bb',name:'',protocol:null,temperature:undefined,humidity:undefined,timestamp:undefined,rssi:-85}])
  expect(result).toHaveLength(1)
  expect(result[0]).toMatchObject({name:'LT_room',protocol:'lt_thermometer',temperature:22.4,humidity:47,rssi:-85,seen_in_scan:true})
 })
 it('retains last values when a later read fails',()=>{
  const device={...found}
  failedPreview(device)
  expect(device).toMatchObject({temperature:22.4,humidity:47,timestamp:'2026-10-22T18:00:00Z',available:false,measurement_error:true})
 })
 it('restores remembered candidates as unavailable until read again',()=>{
  const result=restoreDiscovery(JSON.stringify([found]))
  expect(result[0]).toMatchObject({name:'LT_room',temperature:22.4,humidity:47,available:false})
  expect(restoreDiscovery('bad json')).toEqual([])
  expect(restoreDiscovery(JSON.stringify([{address:1},{...found,timestamp:'invalid'}]))[0]?.timestamp).toBeUndefined()
 })
})

const saved:Sensor={id:'saved-bedroom',name:'Ložnice',address:'AA:BB:CC:DD:EE:FF',protocol:'lt_thermometer',room_id:'bedroom',enabled:true,sample_interval_seconds:900,last_seen:'2026-10-22T19:00:00Z',temperature:20.8,humidity:51,rssi:-70,available:true,battery_raw:1}
it('shows one canonical sensor with saved name and current server values',()=>{
 const rows=sensorCatalogue([{...found,name:'LT_factory',address:'aa-bb-cc-dd-ee-ff',temperature:22.4}], [saved])
 expect(rows).toHaveLength(1)
 expect(rows[0]).toMatchObject({name:'Ložnice',temperature:20.8,humidity:51,available:true,saved:{id:'saved-bedroom',room_id:'bedroom'}})
})
it('keeps saved offline sensors without discoveries and new devices once',()=>{
 const rows=sensorCatalogue([{...found,address:'11:22:33:44:55:66'},{...found,address:'11-22-33-44-55-66'}],[{...saved,available:false,temperature:null,humidity:null}])
 expect(rows).toHaveLength(2)
 expect(rows[0]).toMatchObject({name:'Ložnice',available:false,saved:{id:'saved-bedroom'}})
 expect(rows[1]?.saved).toBeUndefined()
})
