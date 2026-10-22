export class ApiError extends Error { constructor(public status:number,message:string){super(message)} }
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
 const response=await fetch('/api'+path,{...options,credentials:'same-origin',headers:{...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}})
 if(!response.ok){let message=response.statusText;try{const body=await response.json();message=typeof body.detail==='string'?body.detail:JSON.stringify(body.detail)}catch{/* non-JSON gateway error */}if(response.status===401)window.dispatchEvent(new Event('sensogrid:unauthorized'));throw new ApiError(response.status,message)}
 if(response.status===204)return undefined as T
 return response.json() as Promise<T>
}
export function write<T>(path:string,body:unknown,method='POST'){return api<T>(path,{method,body:JSON.stringify(body)})}
export function errorMessage(error:unknown){return error instanceof Error?error.message:String(error)}
