<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
import {bounds,center} from '../lib/geometry'
import {heatmapColor} from '../lib/heatmap'
import {formatValue,state,unit} from '../lib/state'
import type {Floorplan,Room,Metric,Point,PlanRoom} from '../lib/types'
const props=withDefaults(defineProps<{plan:Floorplan;values?:Room[];metric?:Metric;markers?:boolean;selected?:string;editable?:boolean;grid?:boolean;viewBox?:string;draft?:Point[];vertex?:number}>(),{values:()=>[],metric:'temperature',markers:true,editable:false,grid:false,selected:'',viewBox:'',draft:()=>[],vertex:-1})
const emit=defineEmits<{room:[id:string];roomDown:[event:PointerEvent,id:string];vertexDown:[event:PointerEvent,id:string,index:number];markerDown:[event:PointerEvent,id:string];backgroundDown:[event:PointerEvent];move:[event:PointerEvent];up:[event:PointerEvent];wheel:[event:WheelEvent]}>()
const svg=ref<SVGSVGElement|null>(null),dimensions=ref({width:600,height:450})
let observer:ResizeObserver|undefined
const pixelScale=computed(()=>{const box=props.viewBox?props.viewBox.split(/\s+/).map(Number):[-.5,-.5,props.plan.width+1,props.plan.height+1];return Math.max(.01,Math.min(dimensions.value.width/(box[2]||1),dimensions.value.height/(box[3]||1)))})
function font(pixels:number){return {fontSize:pixels/pixelScale.value+'px'}}
function layout(room:PlanRoom){const b=bounds(room.polygon),width=Math.max(1,b.width*pixelScale.value-6),height=b.height*pixelScale.value;const nameFont=Math.max(8,Math.min(11,width/Math.max(1,room.name.length*.55)));return {nameFont,nameWidth:width/pixelScale.value,fitName:room.name.length*nameFont*.55>width,valueFont:Math.max(9,Math.min(20,width/5)),showValue:!props.editable&&width>=44&&height>=56}}
onMounted(()=>{if(!svg.value)return;observer=new ResizeObserver(entries=>{const rect=entries[0]?.contentRect;if(rect&&rect.width>0&&rect.height>0)dimensions.value={width:rect.width,height:rect.height}});observer.observe(svg.value)})
onUnmounted(()=>observer?.disconnect())
const mapped=computed(()=>new Map(props.values.map(v=>[v.id,v])))
function color(id:string){const v=mapped.value.get(id);return heatmapColor(v?.available?v[props.metric]:null,props.metric,state.settings.heatmap[props.metric])}
function roomDown(e:PointerEvent,id:string){if(props.editable){e.stopPropagation();emit('roomDown',e,id)}}
function markerDown(e:PointerEvent,id:string){if(props.editable){e.stopPropagation();emit('markerDown',e,id)}}
</script>
<template>
<svg ref="svg" class="floorplan-svg" :class="{editable}" :viewBox="viewBox||'-0.5 -0.5 '+(plan.width+1)+' '+(plan.height+1)" role="img" :aria-label="plan.name" @pointerdown="emit('backgroundDown',$event)" @pointermove="emit('move',$event)" @pointerup="emit('up',$event)" @pointercancel="emit('up',$event)" @wheel="emit('wheel',$event)">
<defs><pattern id="unavailable" width="0.32" height="0.32" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="0.32" height="0.32" fill="var(--plan-empty)" /><line x1="0" y1="0" x2="0" y2="0.32" stroke="var(--line)" stroke-width="0.035" /></pattern><pattern id="grid" width="0.5" height="0.5" patternUnits="userSpaceOnUse"><path d="M .5 0 H 0 V .5" fill="none" stroke="var(--line)" stroke-width=".012" /></pattern></defs>
<rect v-if="grid" x="0" y="0" :width="plan.width" :height="plan.height" fill="url(#grid)" stroke="var(--line)" stroke-width=".025" />
<g v-for="room in plan.rooms" :key="room.id" class="plan-room" :class="{selected:selected===room.id,unavailable:!editable&&(!mapped.get(room.id)?.available||mapped.get(room.id)?.[metric]==null)}" :tabindex="editable?-1:0" role="button" :aria-label="room.name+' '+formatValue(mapped.get(room.id)?.[metric],metric)+' '+unit(metric)" @click="!editable&&emit('room',room.id)" @keydown.enter="emit('room',room.id)" @pointerdown="roomDown($event,room.id)">
<title>{{ room.name }}{{ editable?'':' · '+formatValue(mapped.get(room.id)?.[metric],metric)+' '+unit(metric) }}</title><polygon :points="room.polygon.map(v=>v.join(',')).join(' ')" :fill="editable?'var(--plan-room)':color(room.id)" stroke="var(--plan-wall)" stroke-width=".075" stroke-linejoin="round" />
<text :x="center(room.polygon)[0]" :y="center(room.polygon)[1]-(layout(room).showValue?12:0)/pixelScale" text-anchor="middle" dominant-baseline="central" class="room-label" :style="font(layout(room).nameFont)" :textLength="layout(room).fitName?layout(room).nameWidth:undefined" lengthAdjust="spacingAndGlyphs">{{ room.name }}</text>
<text v-if="layout(room).showValue" :x="center(room.polygon)[0]" :y="center(room.polygon)[1]+14/pixelScale" text-anchor="middle" dominant-baseline="central" class="room-value" :style="font(layout(room).valueFont)">{{ formatValue(mapped.get(room.id)?.[metric],metric) }}<tspan class="room-unit" :style="font(10)"> {{ unit(metric) }}</tspan></text>
</g>
<g v-if="markers" class="plan-markers"><g v-for="marker in plan.sensors" :key="marker.sensor_id" @pointerdown="markerDown($event,marker.sensor_id)"><circle :cx="marker.x" :cy="marker.y" :r="3/pixelScale" fill="var(--ink)" stroke="var(--surface)" :stroke-width="1.5/pixelScale" /><circle :cx="marker.x" :cy="marker.y" :r=".9/pixelScale" fill="var(--surface)" /><title>{{ marker.sensor_id }}</title></g></g>
<g v-if="editable&&selected"><template v-for="room in plan.rooms.filter(r=>r.id===selected)" :key="room.id"><circle v-for="(point,index) in room.polygon" :key="index" :cx="point[0]" :cy="point[1]" :r="vertex===index?.13:.095" fill="var(--surface)" stroke="var(--ink)" stroke-width=".035" class="vertex" @pointerdown.stop="emit('vertexDown',$event,room.id,index)" /></template></g>
<g v-if="draft.length"><polyline :points="draft.map(v=>v.join(',')).join(' ')" fill="var(--plan-room)" fill-opacity=".5" stroke="var(--ink)" stroke-width=".05" stroke-dasharray=".12 .06" /><circle v-for="(point,index) in draft" :key="index" :cx="point[0]" :cy="point[1]" r=".065" fill="var(--ink)" /></g>
<text v-if="editable" x="0" :y="plan.height+.35" class="room-dimension">{{ plan.width }} × {{ plan.height }} m</text>
</svg>
</template>
