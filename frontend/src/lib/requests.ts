/** Keeps asynchronous responses associated with the document actually submitted. */
export class SnapshotGate {
 private generation=0
 begin(snapshot:string){return {generation:++this.generation,snapshot}}
 isLatest(ticket:{generation:number}){return ticket.generation===this.generation}
 matches(ticket:{generation:number;snapshot:string},current:string){return this.isLatest(ticket)&&ticket.snapshot===current}
}
/** Deliberately excludes browser-only expirationTime; backend accepts these fields only. */
export function pushPayload(subscription:Pick<PushSubscription,'endpoint'|'toJSON'>,label:string){const json=subscription.toJSON();if(!json.keys?.p256dh||!json.keys.auth)throw new Error('Invalid Push subscription keys');return {endpoint:subscription.endpoint,keys:{p256dh:json.keys.p256dh,auth:json.keys.auth},label:label.slice(0,100)}}
