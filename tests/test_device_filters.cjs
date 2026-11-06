const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const handlers={};let requests=0;
const document={forms:[],hidden:false,querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>null,addEventListener:(name,fn)=>(handlers[name]??=[]).push(fn)};
const window={};window.parent=window;
vm.runInNewContext(fs.readFileSync('adr_service_agent/dashboard_live.js','utf8'),{document,window,location:{pathname:'/test'},sessionStorage:{getItem:()=>null},addEventListener(){},matchMedia:()=>({matches:false}),setTimeout(){},setInterval(){},Intl,Date,fetch(){requests++;}});
const select=(rows,query='',sort='ip')=>Array.from(window.ADRDeviceList.select(rows,query,sort));
const rows=[
 ['Unknown','192.168.16.1','gateway','Unknown','Router'],
 ['Sonos','192.168.16.100','Kitchen','AA:BB:CC:00:00:01','Audio'],
 ['Apple','192.168.16.20','Office TV','00-11-22-33-44-55','Player'],
 ['apple','192.168.16.9','Bedroom','00:11:22:33:44:01','Player'],
 ['Unknown','192.168.16.10','Unknown','Unknown','Unknown']
];
assert.deepEqual(select(rows).map(r=>r[1]),['192.168.16.1','192.168.16.9','192.168.16.10','192.168.16.20','192.168.16.100']);
assert.deepEqual(select(rows,'','manufacturer').map(r=>r[1]),['192.168.16.9','192.168.16.20','192.168.16.100','192.168.16.1','192.168.16.10']);
assert.deepEqual(select(rows,'','mac').map(r=>r[1]),['192.168.16.9','192.168.16.20','192.168.16.100','192.168.16.1','192.168.16.10']);
assert.equal(select(rows,'APPLE').length,2);
assert.equal(select(rows,'office tv')[0][1],'192.168.16.20');
assert.equal(select(rows,'001122334455')[0][1],'192.168.16.20');
assert.equal(select(rows,'00:11:22:33:44:55')[0][1],'192.168.16.20');
assert.equal(select(rows,'192.168.16.100').length,1);
assert.equal(select(rows,'nothing').length,0);
assert.equal(select(rows,'','hostname').at(-1)[2],'Unknown');
assert.equal(requests,0);assert.equal(rows[0][1],'192.168.16.1');
console.log('Device filtering passed: numeric IP order, alphabetical names, normalized MAC search/sort, unknown-last, empty results, no requests or mutation.');
