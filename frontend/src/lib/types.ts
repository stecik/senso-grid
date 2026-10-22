export type Metric = 'temperature' | 'humidity'
export type ChartMetric = Metric | 'both'
export interface Sensor {read_state?:'waiting'|'reading'|'retrying'|'ready'|'unavailable';id:string;name:string;address:string|null;protocol:string;room_id:string|null;enabled:boolean;sample_interval_seconds:number;interval_override_seconds?:number|null;last_seen:string|null;temperature:number|null;humidity:number|null;rssi:number|null;available:boolean;battery_raw:number|null}
export interface Room {id:string;name:string;temperature:number|null;humidity:number|null;available:boolean}
export type Point = [number,number]
export interface PlanRoom {id:string;name:string;polygon:Point[]}
export interface Marker {sensor_id:string;room_id:string|null;x:number;y:number}
export interface Floorplan {schema_version:1;id:string;name:string;units:'m';width:number;height:number;rooms:PlanRoom[];sensors:Marker[]}
export interface Dashboard {mode:'demo'|'ble'|'off';now:string;average_temperature:number|null;average_humidity:number|null;sensors:Sensor[];rooms:Room[];status:{collector:string;storage:string;last_error:string|null}}
export interface Settings {language:'cs'|'en';theme:'light'|'dark'|'system';temperature_unit:'C'|'F';push_enabled:boolean;heatmap:{temperature:[number,number];humidity:[number,number]}}
export interface HistoryPoint {timestamp:string;sensor_id:string;room_id:string|null;temperature:number|null;humidity:number|null;temperature_min:number|null;temperature_max:number|null;humidity_min:number|null;humidity_max:number|null;count:number}
export interface History {points:HistoryPoint[];source:'demo'|'influxdb3'}
export interface Rule {id:string;name:string;sensor_id:string|null;room_id:string|null;metric:Metric|'offline';operator:'above'|'below';threshold:number;duration_seconds:number;reset_threshold:number;enabled:boolean}
export interface AlertEvent {id:string;rule_id:string;rule_name:string;state:'active'|'resolved';message:string;started_at:string;resolved_at:string|null}
export interface SensorPreview {temperature:number;humidity:number;timestamp:string}
export interface Discovered {available?:boolean;seen_in_scan?:boolean;temperature?:number;humidity?:number;timestamp?:string;measurement_error?:boolean;name:string;address:string;rssi:number;protocol:string|null;service_uuids:string[];manufacturer_data:unknown;service_data:unknown}
export interface Auth {setup_required:boolean;authenticated:boolean;user:{id:string;username:string}|null}
export interface SystemSettings {sample_interval_seconds:number;stale_after_seconds:number}
