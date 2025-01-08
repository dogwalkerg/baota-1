import{ac as a,J as e,e as t}from"./utils-lib.js?v=1736403705";import{c as l,r as s,k as o,l as r,e as p,p as m,M as n,d as u}from"./base-lib.js?v=1736403705";import"./__commonjsHelpers__.js?v=1736403705";const c={class:"p-[20px] h-full"},_=t(l({__name:"index",props:{compData:{default:()=>[]}},setup(t){const l=u((()=>e((()=>import("./index396.js?v=1736403705")),__vite__mapDeps([]),import.meta.url))),_=u((()=>e((()=>import("./index397.js?v=1736403705")),__vite__mapDeps([]),import.meta.url))),d=t,i=s("routeBackup"),b=[{label:"常规备份",name:"routeBackup",lazy:!0,render:()=>p(_,{compData:d.compData},null)},{label:"增量备份",name:"incrementBackup",lazy:!0,render:()=>p(l,{compData:d.compData},null)}];return(e,t)=>{const l=a;return o(),r("div",c,[p(l,{type:"card",modelValue:m(i),"onUpdate:modelValue":t[0]||(t[0]=a=>n(i)?i.value=a:null),options:b,class:"bt-tabs bt-tabs-card"},null,8,["modelValue"])])}}}),[["__scopeId","data-v-ce9629be"]]);export{_ as default};
function __vite__mapDeps(indexes) {
  if (!__vite__mapDeps.viteFileDeps) {
    __vite__mapDeps.viteFileDeps = []
  }
  return indexes.map((i) => __vite__mapDeps.viteFileDeps[i])
}
