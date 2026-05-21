import{j as n,A as e,r as p}from"./index-D8mZA_3n.js";/**
 * @license lucide-react v0.462.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const g=n("Minus",[["path",{d:"M5 12h14",key:"1ays0h"}]]);/**
 * @license lucide-react v0.462.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const k=n("TrendingDown",[["polyline",{points:"22 17 13.5 8.5 8.5 13.5 2 7",key:"1r2t7k"}],["polyline",{points:"16 17 22 17 22 11",key:"11uiuu"}]]);/**
 * @license lucide-react v0.462.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const N=n("TrendingUp",[["polyline",{points:"22 7 13.5 15.5 8.5 10.5 2 17",key:"126l90"}],["polyline",{points:"16 7 22 7 22 13",key:"kwv8wd"}]]);function v({title:l,...t}){const a=t.label||l||"";return e.jsx(f,{...t,label:a})}function f({label:l,value:t,icon:a,iconColor:c="text-blue-600",iconBg:o="bg-blue-100 dark:bg-blue-900/30",trend:s,trendLabel:m,suffix:i,prefix:r,loading:h=!1,onClick:d,className:x=""}){const b=typeof t=="number"?p(t):t,u=s===void 0||s===0?g:s>0?N:k,j=s===void 0||s===0?"text-slate-500":s>0?"text-green-600 dark:text-green-400":"text-red-600 dark:text-red-400";return h?e.jsx("div",{className:`card p-6 ${x}`,children:e.jsxs("div",{className:"animate-pulse",children:[e.jsx("div",{className:"flex items-start justify-between mb-4",children:e.jsx("div",{className:"w-10 h-10 rounded-xl bg-slate-200 dark:bg-slate-700"})}),e.jsx("div",{className:"h-8 w-24 bg-slate-200 dark:bg-slate-700 rounded mb-2"}),e.jsx("div",{className:"h-4 w-32 bg-slate-200 dark:bg-slate-700 rounded"})]})}):e.jsxs("div",{className:`card p-6 ${d?"cursor-pointer hover:shadow-md transition-shadow":""} ${x}`,onClick:d,children:[e.jsx("div",{className:"flex items-start justify-between mb-4",children:a&&e.jsx("div",{className:`w-10 h-10 rounded-xl ${o} flex items-center justify-center flex-shrink-0`,children:e.jsx(a,{size:20,className:c})})}),e.jsxs("div",{className:"flex items-baseline gap-1 mb-1",children:[r&&e.jsx("span",{className:"text-lg text-slate-500 dark:text-slate-400",children:r}),e.jsx("span",{className:"text-2xl font-bold text-slate-900 dark:text-white",children:b}),i&&e.jsx("span",{className:"text-sm text-slate-500 dark:text-slate-400",children:i})]}),e.jsx("p",{className:"text-sm text-slate-600 dark:text-slate-400 mb-2",children:l}),s!==void 0&&e.jsxs("div",{className:`flex items-center gap-1 text-xs font-medium ${j}`,children:[e.jsx(u,{size:12}),e.jsxs("span",{children:[Math.abs(s),"% ",m||(s>=0?"increase":"decrease")]})]})]})}export{v as S,N as T};
//# sourceMappingURL=StatsCard-CnFv25Af.js.map
