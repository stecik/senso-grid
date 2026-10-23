import type {HistoryPoint,Metric,ChartMetric,Room,Sensor} from './types'

interface ChartSeriesOptions {bucket:string;interval:number;intervals:Record<string,number>;temperatureUnit:'C'|'F';labels:Record<Metric,string>}
const chartPalette=['#315efb','#c2853e','#0e9fba','#8b75d7','#d66b8a','#587aa2']
export function chartSeries(points:HistoryPoint[],rooms:{id:string;name:string}[],selected:string[],metric:ChartMetric,options:ChartSeriesOptions){
 const metrics:Metric[]=metric==='both'?['temperature','humidity']:[metric]
 return selected.flatMap(id=>metrics.map(kind=>{
  const room=rooms.find(r=>r.id===id),color=chartPalette[Math.max(0,rooms.findIndex(r=>r.id===id))%chartPalette.length]!
  const unit=kind==='humidity'?'%':'°'+options.temperatureUnit
  return {
   id:id+'-'+kind,name:(room?.name??id)+(metric==='both'?' · '+options.labels[kind]:''),
   type:'line' as const,yAxisIndex:metric==='both'&&kind==='humidity'?1:0,
   showSymbol:false,connectNulls:true,
   lineStyle:{width:2,type:kind==='humidity'?'dashed' as const:'solid' as const,color},
   itemStyle:{color},emphasis:{focus:'series' as const},
   tooltip:{valueFormatter:(value:unknown)=>{const n=Array.isArray(value)?value[1]:value;return typeof n==='number'?n.toFixed(1)+' '+unit:'—'}},
   data:roomSeries(points,id,kind,intervalSeconds(options.bucket,options.intervals[id]??options.interval)).map(([x,y]):[number,number|null]=>[x,y==null?null:kind==='temperature'&&options.temperatureUnit==='F'?y*9/5+32:y]),
  }
 }))
}

export function intervalSeconds(bucket:string,expected=900){return ({hour:3600,day:86400,week:604800,month:2678400} as Record<string,number>)[bucket]??expected}
export function roomSeries(points:HistoryPoint[],roomId:string,metric:Metric,gapSeconds:number):[number,number|null][] {const grouped=new Map<number,{sum:number;count:number}>();for(const p of points){if(p.room_id!==roomId)continue;const x=Date.parse(p.timestamp);if(!Number.isFinite(x))continue;const y=p[metric];if(y==null){if(!grouped.has(x))grouped.set(x,{sum:0,count:0});continue}const n=Math.max(1,p.count),prev=grouped.get(x)??{sum:0,count:0};prev.sum+=y*n;prev.count+=n;grouped.set(x,prev)}const out:[number,number|null][]=[];for(const [x,v] of [...grouped.entries()].sort((a,b)=>a[0]-b[0])){const prev=out[out.length-1];if(prev&&x-prev[0]>gapSeconds*1500)out.push([prev[0]+gapSeconds*1000,null]);out.push([x,v.count?v.sum/v.count:null])}return out}
export function statistics(points:HistoryPoint[],roomId:string,metric:Metric){const valid=points.filter(p=>p.room_id===roomId&&p[metric]!=null);if(!valid.length)return null;let sum=0,count=0,min=Infinity,max=-Infinity;for(const p of valid){const value=p[metric]!;const n=Math.max(1,p.count);sum+=value*n;count+=n;min=Math.min(min,p[metric==='temperature'?'temperature_min':'humidity_min']??value);max=Math.max(max,p[metric==='temperature'?'temperature_max':'humidity_max']??value)}return {min,max,average:sum/count,count}}

export function historyRooms(rooms:Room[],sensors:Pick<Sensor,'room_id'>[],points:HistoryPoint[]):Room[]{
 const ids=new Set(sensors.map(sensor=>sensor.room_id).filter((id):id is string=>!!id))
 for(const point of points)if(point.room_id&&((point.temperature!=null&&Number.isFinite(point.temperature))||(point.humidity!=null&&Number.isFinite(point.humidity))))ids.add(point.room_id)
 const result=rooms.filter(room=>ids.has(room.id)),known=new Set(result.map(room=>room.id))
 for(const id of ids)if(!known.has(id)&&points.some(point=>point.room_id===id)){result.push({id,name:id,temperature:null,humidity:null,available:false});known.add(id)}
 return result
}
