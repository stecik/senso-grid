import type {Metric} from './types'

export const heatmapPalettes:Record<Metric,readonly [string,string,string]>={
 temperature:['#aecbd7','#bdcfae','#dfa984'],
 humidity:['#ded4a5','#b7cbaa','#a6c6d9'],
}

/** Interpolate within the comfort band; saturate outside its configured limits. */
export function heatmapColor(value:number|null|undefined,metric:Metric,limits:readonly [number,number]):string{
 if(value==null||!Number.isFinite(value))return 'url(#unavailable)'
 const position=Math.max(0,Math.min(1,(value-limits[0])/(limits[1]-limits[0])))*2
 const half=position<=1?0:1,fraction=position-half,palette=heatmapPalettes[metric]
 const channels=(hex:string)=>[1,3,5].map(start=>parseInt(hex.slice(start,start+2),16))
 const from=channels(palette[half]),to=channels(palette[half+1]!)
 return 'rgb('+from.map((channel,i)=>Math.round(channel+(to[i]!-channel)*fraction)).join(', ')+')'
}
