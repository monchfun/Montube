import React from "react";
import {createRoot} from "react-dom/client";
import App from "./App";
import "./styles.css";

// 渲染失败（浏览器过旧、资源缺失等）时把错误直接显示出来，避免 fnOS 里只看到一片空白。
function showFatal(error){
  const message=error?.message||String(error);
  const box=document.createElement("div");
  box.style.cssText="margin:48px auto;max-width:560px;padding:24px;border:1px solid #e3e9ec;border-radius:12px;background:#fff;font:14px/1.7 system-ui,sans-serif;color:#17212b";
  box.textContent=`Montube 前端加载失败：${message}`;
  document.body.appendChild(box);
}
window.addEventListener("unhandledrejection",e=>{if(!document.getElementById("root").childElementCount)showFatal(e.reason)});
try{
  createRoot(document.getElementById("root")).render(<React.StrictMode><App/></React.StrictMode>);
}catch(error){
  showFatal(error);
}
