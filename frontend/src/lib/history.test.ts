import {describe,it,expect} from 'vitest'
import {roomSeries,statistics,historyRooms} from './history'
import type {HistoryPoint} from './types'
const sample=(timestamp:string,value:number,count=1):HistoryPoint=>({timestamp,sensor_id:'s',room_id:'r',temperature:value,humidity:50,temperature_min:value-1,temperature_max:value+1,humidity_min:40,humidity_max:60,count})
describe('history truthfulness',()=>{it('weights aggregate averages by sample counts and preserves extrema',()=>{expect(statistics([sample('2026-01-01T00:00:00Z',10,1),sample('2026-01-01T01:00:00Z',20,9)],'r','temperature')).toEqual({min:9,max:21,average:19,count:10})});it('inserts a null gap when samples stop',()=>{const result=roomSeries([sample('2026-01-01T00:00:00Z',20),sample('2026-01-01T03:00:00Z',23)],'r','temperature',3600);expect(result).toEqual([[Date.parse('2026-01-01T00:00:00Z'),20],[Date.parse('2026-01-01T01:00:00Z'),null],[Date.parse('2026-01-01T03:00:00Z'),23]])});it('does not invent room data or bridge reassignments',()=>{expect(roomSeries([sample('2026-01-01T00:00:00Z',20)],'other','temperature',900)).toEqual([]);expect(statistics([],'r','temperature')).toBeNull()})})

describe('rooms relevant to history',()=>{
 const room=(id:string)=>({id,name:id,temperature:null,humidity:null,available:false})
 it('hides rooms without assigned sensors or actual historical measurements',()=>{
  const empty={...sample('2026-10-22T00:00:00Z',20),room_id:'hall',temperature:null,humidity:null}
  expect(historyRooms([room('hall'),room('bedroom')],[{room_id:'bedroom'}],[empty]).map(r=>r.id)).toEqual(['bedroom'])
 })
 it('keeps an unassigned room with history after its sensor has moved',()=>{
  const point={...sample('2026-10-22T00:00:00Z',20),room_id:'old-room'}
  expect(historyRooms([room('old-room'),room('new-room')],[{room_id:'new-room'}],[point]).map(r=>r.id)).toEqual(['old-room','new-room'])
 })
 it('includes removed rooms with valid historical data, including zero humidity',()=>{
  const point={...sample('2026-10-22T00:00:00Z',20),room_id:'archived',temperature:null,humidity:0}
  expect(historyRooms([],[],[point]).map(r=>({id:r.id,name:r.name}))).toEqual([{id:'archived',name:'archived'}])
 })
})
