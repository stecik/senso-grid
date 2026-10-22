import {describe,it,expect} from 'vitest'
import {chartSeries} from './history'
import type {HistoryPoint} from './types'
const point=(timestamp:string,temperature:number|null,humidity:number|null):HistoryPoint=>({timestamp,sensor_id:'s',room_id:'r',temperature,humidity,temperature_min:temperature,temperature_max:temperature,humidity_min:humidity,humidity_max:humidity,count:1})
const points=[point('2026-10-22T00:00:00Z',20,60),point('2026-10-22T03:00:00Z',22,50)]
const rooms=[{id:'other',name:'Other'},{id:'r',name:'Bedroom'}]
const options={bucket:'hour',interval:900,intervals:{},temperatureUnit:'F' as const,labels:{temperature:'Temperature',humidity:'Humidity'}}
describe('combined history chart',()=>{
 it('plots both metrics on separate axes with the same room color and stable line styles',()=>{
  const series=chartSeries(points,rooms,['r'],'both',options)
  expect(series).toHaveLength(2)
  expect(series.map(s=>[s.yAxisIndex,s.lineStyle.type])).toEqual([[0,'solid'],[1,'dashed']])
  expect(series[0]!.lineStyle.color).toBe(series[1]!.lineStyle.color)
  expect(series[0]!.data.map(p=>p[1])).toEqual([68,null,71.6])
  expect(series[1]!.data.map(p=>p[1])).toEqual([60,null,50])
  expect(series.every(s=>s.connectNulls===false)).toBe(true)
 })
 it('uses the same styles, colors and units when displaying each metric separately',()=>{
  const both=chartSeries(points,rooms,['r'],'both',options)
  const temperature=chartSeries(points,rooms,['r'],'temperature',options)
  const humidity=chartSeries(points,rooms,['r'],'humidity',options)
  expect(temperature).toHaveLength(1);expect(humidity).toHaveLength(1)
  expect(temperature[0]!.lineStyle).toEqual(both[0]!.lineStyle)
  expect(humidity[0]!.lineStyle).toEqual(both[1]!.lineStyle)
  expect(humidity[0]!.yAxisIndex).toBe(0)
  expect(temperature[0]!.tooltip.valueFormatter(68)).toContain('°F')
  expect(humidity[0]!.tooltip.valueFormatter(60)).toContain('%')
 })
 it('keeps room colors stable when room selection changes and distinguishes tooltip metrics',()=>{
  const selected=chartSeries(points,rooms,['r'],'both',options)
  const all=chartSeries(points,rooms,['other','r'],'both',options)
  expect(selected[0]!.lineStyle.color).toBe(all[2]!.lineStyle.color)
  expect(selected[0]!.name).toBe('Bedroom · Temperature')
  expect(selected[1]!.name).toBe('Bedroom · Humidity')
  expect(chartSeries(points,rooms,[],'both',options)).toEqual([])
 })
})
