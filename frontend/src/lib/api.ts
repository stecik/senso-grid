export class ApiError extends Error { constructor(public status:number,message:string){super(message)} }
async function checkedResponse(path:string, options:RequestInit={}):Promise<Response> {
 const response=await fetch('/api'+path,{...options,credentials:'same-origin',headers:{...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}})
 if(!response.ok){let message=response.statusText;try{const body=await response.json();message=typeof body.detail==='string'?body.detail:JSON.stringify(body.detail)}catch{/* non-JSON gateway error */}if(response.status===401)window.dispatchEvent(new Event('sensogrid:unauthorized'));throw new ApiError(response.status,message)}
 return response
}
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {const response=await checkedResponse(path,options);return response.status===204?undefined as T:response.json() as Promise<T>}
export async function diagnosticArchive():Promise<Blob>{return (await checkedResponse('/diagnostics')).blob()}
export function write<T>(path:string,body:unknown,method='POST'){return api<T>(path,{method,body:JSON.stringify(body)})}
export function errorMessage(error:unknown){return error instanceof Error?error.message:String(error)}
