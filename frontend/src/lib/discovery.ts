import type {Discovered,Sensor} from './types'

/** A scan updates sightings; it never removes a device the user may still add. */
export function mergeDiscovery(known:Discovered[],seen:Discovered[]):Discovered[]{
 const previousStates=new Map(known.map(device=>[macKey(device.address),device.available]))
 const devices:Discovered[]=known.map(device=>({...device,available:false,seen_in_scan:false}))
 const byAddress=new Map(devices.map(device=>[macKey(device.address),device]))
 for(const sighting of seen){
  const address=sighting.address.toUpperCase(),key=macKey(address),previous=byAddress.get(key)
  const defined=Object.fromEntries(Object.entries(sighting).filter(([,value])=>value!==undefined))
  const device={...previous,...defined,address,name:sighting.name||previous?.name||address,protocol:previous?.protocol==='lt_thermometer'?previous.protocol:sighting.protocol??previous?.protocol??null,available:previousStates.get(key),seen_in_scan:true,measurement_error:false} as Discovered
  if(previous)Object.assign(previous,device)
  else{devices.push(device);byAddress.set(key,device)}
 }
 return devices
}

/** Keep the last successful value and its timestamp, explicitly marked offline. */
export function failedPreview(device:Discovered){device.measurement_error=true;device.available=false}

/** Browser cache is untrusted; remembered readings never imply a live connection. */
export function restoreDiscovery(value:string|null):Discovered[]{
 try{
  const parsed:unknown=JSON.parse(value??'[]')
  if(!Array.isArray(parsed))return []
  const devices:Discovered[]=[]
  for(const row of parsed){
   if(!row||typeof row!=='object'||typeof row.address!=='string'||!row.address.trim()||row.address.length>128)continue
   devices.push({name:typeof row.name==='string'?row.name.slice(0,100):row.address,address:row.address.toUpperCase(),protocol:typeof row.protocol==='string'?row.protocol:null,rssi:typeof row.rssi==='number'&&Number.isFinite(row.rssi)?row.rssi:0,service_uuids:[],manufacturer_data:{},service_data:{},temperature:typeof row.temperature==='number'&&Number.isFinite(row.temperature)?row.temperature:undefined,humidity:typeof row.humidity==='number'&&Number.isFinite(row.humidity)?row.humidity:undefined,timestamp:typeof row.timestamp==='string'&&Number.isFinite(Date.parse(row.timestamp))?row.timestamp:undefined,available:false,seen_in_scan:false})
  }
  return mergeDiscovery(devices,[])
 }catch{return []}
}

export const macKey=(address:string)=>address.replace(/[:\-\s]/g,'').toUpperCase()
export interface CatalogueSensor {key:string;name:string;address:string|null;protocol:string|null;rssi:number|null;temperature:number|null;humidity:number|null;timestamp?:string|null;available?:boolean;read_state?:Sensor['read_state'];saved?:Sensor;device?:Discovered}
export function sensorCatalogue(discovered:Discovered[],saved:Sensor[]):CatalogueSensor[]{
 const candidates=new Map(discovered.map(device=>[macKey(device.address),device]))
 const rows:CatalogueSensor[]=saved.map(sensor=>{
  const key=sensor.address?macKey(sensor.address):sensor.id,device=candidates.get(key)
  candidates.delete(key)
  const fromServer=sensor.temperature!=null&&sensor.humidity!=null
  return {key,name:sensor.name,address:sensor.address,protocol:sensor.protocol,rssi:sensor.rssi??device?.rssi??null,temperature:fromServer?sensor.temperature:device?.temperature??null,humidity:fromServer?sensor.humidity:device?.humidity??null,timestamp:fromServer?sensor.last_seen:device?.timestamp??sensor.last_seen,available:sensor.available,read_state:sensor.read_state,saved:sensor,device}
 })
 for(const [key,device] of candidates)rows.push({key,name:device.name,address:device.address,protocol:device.protocol,rssi:device.rssi,temperature:device.temperature??null,humidity:device.humidity??null,timestamp:device.timestamp,available:device.available,device})
 return rows
}
