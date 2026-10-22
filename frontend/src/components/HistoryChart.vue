<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import {use} from 'echarts/core'
import {LineChart} from 'echarts/charts'
import {CanvasRenderer} from 'echarts/renderers'
import {GridComponent,TooltipComponent,DataZoomComponent,LegendComponent} from 'echarts/components'
import VChart from 'vue-echarts'
import {state,unit} from '../lib/state'
import {chartSeries} from '../lib/history'
import type {HistoryPoint,Metric,ChartMetric,Room} from '../lib/types'
use([CanvasRenderer,LineChart,GridComponent,TooltipComponent,DataZoomComponent,LegendComponent])
const {t}=useI18n()
const props=withDefaults(defineProps<{points:HistoryPoint[];rooms:Room[];selected:string[];metric:ChartMetric;bucket?:string;interval?:number;intervals?:Record<string,number>;start?:number;end?:number}>(),{bucket:'raw',interval:900,intervals:()=>({}),start:undefined,end:undefined})
const metrics=computed<Metric[]>(()=>props.metric==='both'?['temperature','humidity']:[props.metric])
const option=computed(()=>{
 const dark=state.settings.theme==='dark'||(state.settings.theme==='system'&&matchMedia('(prefers-color-scheme: dark)').matches)
 const color=dark?'#a1afc6':'#65748b',line=dark?'#2a3851':'#e4eaf3'
 return {
  animationDuration:350,grid:{left:48,right:props.metric==='both'?48:18,top:28,bottom:68,containLabel:false},
  tooltip:{trigger:'axis',confine:true},
  xAxis:{type:'time',min:props.start,max:props.end,axisLabel:{color,fontSize:10,hideOverlap:true},axisLine:{lineStyle:{color:line}},splitLine:{show:false}},
  yAxis:metrics.value.map((metric,index)=>({type:'value',scale:true,name:unit(metric),position:index===1?'right':'left',nameTextStyle:{color,fontSize:10},axisLabel:{color,fontSize:10},splitLine:{show:index===0,lineStyle:{color:line,type:'dashed'}}})),
  dataZoom:[{type:'inside',filterMode:'none'},{type:'slider',bottom:3,height:18,borderColor:'transparent',backgroundColor:dark?'#1e2d49':'#eaf0ff',fillerColor:'#315efb25',handleStyle:{color:'#315efb'},textStyle:{color,fontSize:9}}],
  series:chartSeries(props.points,props.rooms,props.selected,props.metric,{bucket:props.bucket,interval:props.interval,intervals:props.intervals,temperatureUnit:state.settings.temperature_unit,labels:{temperature:t('temperature'),humidity:t('humidity')}}),
 }
})
</script>
<template><div class="history-chart"><div class="chart-key"><span v-for="kind in metrics" :key="kind"><i :class="kind"></i>{{ t(kind) }} ({{ unit(kind) }})</span></div><VChart class="chart" :option="option" :update-options="{replaceMerge:['series','yAxis']}" autoresize :aria="{enabled:true}" /></div></template>
