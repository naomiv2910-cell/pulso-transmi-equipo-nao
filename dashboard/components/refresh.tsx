"use client";
import { useEffect, useTransition } from "react";
import { useRouter } from "next/navigation";
export function Refresh(){
 const router=useRouter();const [pending,startTransition]=useTransition();
 useEffect(()=>{const id=setInterval(()=>{if(!document.hidden)router.refresh();},60000);return()=>clearInterval(id);},[router]);
 return <button className="refresh" disabled={pending} onClick={()=>startTransition(()=>router.refresh())}>{pending?"Actualizando…":"↻ Actualizar"}</button>;
}
