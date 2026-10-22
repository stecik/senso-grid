import {describe,it,expect} from 'vitest'
import {heatmapColor} from './heatmap'

describe('continuous floorplan heatmap',()=>{
 it('distinguishes nearby comfortable temperatures instead of bucketing them',()=>{
  expect(heatmapColor(22.9,'temperature',[18,25])).not.toBe(heatmapColor(23.9,'temperature',[18,25]))
  expect(heatmapColor(21.5,'temperature',[18,25])).toBe('rgb(189, 207, 174)')
  expect(heatmapColor(19.75,'temperature',[18,25])).toBe('rgb(182, 205, 195)')
 })
 it('clamps at the configured cold and warm limits',()=>{
  expect(heatmapColor(-5,'temperature',[18,25])).toBe(heatmapColor(18,'temperature',[18,25]))
  expect(heatmapColor(40,'temperature',[18,25])).toBe(heatmapColor(25,'temperature',[18,25]))
  expect(heatmapColor(18,'temperature',[18,25])).toBe('rgb(174, 203, 215)')
  expect(heatmapColor(25,'temperature',[18,25])).toBe('rgb(223, 169, 132)')
 })
 it('interpolates humidity through a green center with custom limits',()=>{
  expect(heatmapColor(50,'humidity',[30,70])).toBe('rgb(183, 203, 170)')
  expect(heatmapColor(40,'humidity',[30,70])).not.toBe(heatmapColor(60,'humidity',[30,70]))
  expect(heatmapColor(60,'humidity',[40,80])).toBe('rgb(183, 203, 170)')
 })
 it('remains continuous across the center and both configured limits',()=>{
  const channels=(color:string)=>color.match(/\d+/g)!.map(Number)
  for(const n of [18,21.5,25]){
   const before=channels(heatmapColor(n-.001,'temperature',[18,25]))
   const after=channels(heatmapColor(n+.001,'temperature',[18,25]))
   expect(Math.max(...before.map((channel,i)=>Math.abs(channel-after[i]!)))).toBeLessThanOrEqual(1)
  }
 })
 it('keeps missing and non-finite measurements hatched',()=>{
  for(const value of [null,undefined,NaN,Infinity])expect(heatmapColor(value,'temperature',[18,25])).toBe('url(#unavailable)')
 })
})
