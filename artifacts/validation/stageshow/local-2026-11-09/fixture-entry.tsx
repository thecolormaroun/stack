import React from 'react'
import {createRoot} from 'react-dom/client'
import Form from './examples/form-error'
import Static from './examples/static-card'
import Loading from './examples/loading'
import {Stage} from './kit/stage'
import {Window} from './kit/window'
import './acceptance-scene.css'
const mode=new URLSearchParams(location.search).get('mode')||'form'
const payload=`</figcaption><img src=x onerror="window.__captionExecuted=1"> & 'single' "double"`
function Probe(){return <Stage width={560} height={400} initial={{}} script={async a=>{await a.wait(1200);a.mark(payload);await a.wait(1300)}} play="once">{()=> <span data-target="bad" style={{position:'absolute',left:540,top:80,width:140,height:60,background:'#ddd'}}>Clipped action</span>}</Stage>}
function Scene(){return <Stage width={560} height={300} compact={{below:560,width:358,height:280}} initial={{saved:false}} poster={{saved:true}} cursor={{at:{x:400,y:250}}} script={async a=>{await a.wait(400);await a.click('save');a.mark('saved');a.put({saved:true});await a.wait(1400);a.mark('reset');a.put({saved:false});await a.wait(1000)}} className="validation-scene">{(s,rect,layout)=>{
 const content=<div className="validation-content"><h2>Release preview</h2><p>One local draft, ready to share.</p><div className="validation-track"><div className="validation-progress" style={{transform:`scaleX(${s.saved?1:0.15})`}}/></div><button data-target="save" className="validation-save"><span style={{opacity:s.saved?0:1}}>Save preview</span><span style={{opacity:s.saved?1:0}}>Preview saved</span></button></div>;
 return layout==='compact'?<div className="validation-card">{content}</div>:<Window title="Draft studio" className="validation-window">{content}</Window>
 }}</Stage>}
createRoot(document.getElementById('root')!).render(mode==='static'?<Static/>:mode==='loop'?<Loading/>:mode==='failure'?<Probe/>:mode==='scene'?<Scene/>:<Form/>);
