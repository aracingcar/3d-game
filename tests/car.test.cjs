// Run with: node tests/car.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element() {
  const listeners = {}, classes = new Set();
  return {
    listeners, style:{}, hidden:false, clientWidth:800, clientHeight:600,
    classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},
    addEventListener:(name,fn)=>listeners[name]=fn, append(){}, setAttribute(){}, setPointerCapture(){}, blur(){},
    getBoundingClientRect:()=>({left:100,top:50,width:800,height:600}),
    querySelector:()=>element(),
    getContext:()=>new Proxy({createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)})},{get:(t,k)=>k in t?t[k]:()=>{},set:()=>true})
  };
}
const elements=[], container=element(), events={};
const map={getZoom:()=>6.5,getPitch:()=>52,getBearing:()=>-8,getPadding:()=>({}),getMaxPitch:()=>60,
  getCenter:()=>({lng:1,lat:1}),getContainer:()=>container,setMaxPitch(){},jumpTo(view){this.lastView=view;},on(){}};
for(const h of ['dragPan','dragRotate','touchZoomRotate','touchPitch','keyboard','doubleClickZoom','scrollZoom']) {
  map[h]={enabled:h!=='keyboard',isEnabled(){return this.enabled;},enable(){this.enabled=true;},disable(){this.enabled=false;}};
}
let picked=[1.5,1.5,20], redraws=0;
const context=vm.createContext({window:{}, document:{createElement:()=>{const e=element();elements.push(e);return e;},body:element(),getElementById:()=>element()},
  addEventListener:(name,fn)=>events[name]=fn,performance:{now:()=>0},requestAnimationFrame(){},setTimeout(){},innerWidth:1000,devicePixelRatio:1});
for(const f of ['boat.js','car.js']) vm.runInContext(fs.readFileSync(__dirname+'/../6_display/car/'+f,'utf8'),context);
const car=context.window.createCarMechanics({deck:{SimpleMeshLayer:class{constructor(props){Object.assign(this,props);}}},map,
  terrain:{x0:0,y0:3,step:1,NR:4,NC:4,GZ:new Float32Array(16).fill(10),outline:[[[.1,.1],[2.9,.1],[2.9,2.9],[.1,2.9],[.1,.1]]],getExaggeration:()=>1},
  getRelief:()=>1,setRelief(){},refresh:()=>redraws++,pickTerrain:()=>picked});
const dock=elements.find(e=>e.id==='car-dock');
assert.equal(car.layer().data.length,0,'no automatic spawn');
assert.equal(car.place([0,0]),false,'outside outline rejected even with terrain grid');
assert.equal(car.place([9,9]),false,'outside grid rejected');
const pointer=(x,y)=>({button:0,pointerId:1,clientX:x,clientY:y});
dock.listeners.pointerdown(pointer(920,700));
assert.equal(car.isPlacing(),true);
dock.listeners.pointermove(pointer(400,300));
dock.listeners.pointerup(pointer(400,300));
assert.equal(car.state.placed,true); assert.equal(car.state.selected,true);
assert.deepEqual(Array.from(car.state.pos),[1.5,1.5]);
assert.equal(car.isPlacing(),false); assert.equal(map.dragPan.enabled,false);
car.state.pos=[1.5,2.89999]; car.state.vel=[0,1000];
car.tick(.05);
assert.equal(car.state.placed,true,'car remains visible after crossing boundary');
assert.equal(car.state.falling,true);
assert.equal(car.layer().data.length,1);
const edgeZ=car.layer().getPosition(car.state)[2], edgeY=car.state.pos[1], cameraAtEdge=map.lastView;
car.tick(.05);
assert(car.layer().getPosition(car.state)[2]<edgeZ,'car falls below its edge altitude');
assert(car.state.pos[1]>edgeY,'forward momentum continues during fall');
assert.equal(map.lastView,cameraAtEdge,'camera holds at edge instead of following underground');
assert.equal(car.state.selected,true);
car.click({object:car.state}); assert.equal(car.state.selected,true,'click cannot strand a falling car');
for(let i=0;i<60;i++) car.tick(.05);
assert.equal(car.state.placed,false,'completed fall returns car to dock');
assert.equal(car.state.falling,false);
assert.equal(car.layer().data.length,0); assert.equal(car.driveKeys.size,0);
assert.equal(map.dragPan.enabled,true); assert.equal(map.keyboard.enabled,false,'original disabled handlers stay disabled');
assert.equal(map.lastView.center.lng,1,'overview restored');
dock.listeners.pointerdown(pointer(920,700)); dock.listeners.pointermove(pointer(950,720)); dock.listeners.pointerup(pointer(950,720));
assert.equal(car.state.placed,false,'drop outside map rejected');
dock.listeners.pointerdown(pointer(920,700)); dock.listeners.pointercancel(); assert.equal(car.isPlacing(),false);
assert.equal(car.place([1.2,1.2]),true,'can place again after reset');
const key=(code,target={})=>({code,target,preventDefault(){this.prevented=true;}});
const up=key('ArrowUp',{matches:()=>false}); events.keydown(up);
assert.equal(car.driveKeys.has('KeyW'),true,'ArrowUp drives like W'); assert.equal(up.prevented,true);
events.keyup(key('ArrowUp')); assert.equal(car.driveKeys.has('KeyW'),false);
events.keydown(key('ArrowLeft',{matches:()=>true})); assert.equal(car.driveKeys.size,0,'keys typed into a text box are left alone');
events.keydown({code:'Escape'}); assert.equal(car.state.placed,true); assert.equal(car.state.selected,false,'Escape still pauses normal driving');
events.keydown({code:'Escape'}); assert.equal(car.state.selected,true);
car.state.pos=[1.5,2.89999]; car.state.vel=[0,1000]; car.tick(.05);
assert.equal(car.state.falling,true);
events.keydown({code:'Escape'}); assert.equal(car.state.placed,false,'Escape can skip the fall');
assert(redraws>0);

// Donuts: boost + full lock on wet tyres (river wetness) spins the rear wheels and the car pivots in a tight circle;
// on dry tyres the rear holds the same input and the car carves a wide, fast arc instead.
function spinTest(wet) {
  const flat={x0:0,y0:3,step:1,NR:4,NC:4,GZ:new Float32Array(16).fill(10),outline:[[[.1,.1],[2.9,.1],[2.9,2.9],[.1,2.9],[.1,.1]]],getExaggeration:()=>1};
  const c=context.window.createCarMechanics({deck:{SimpleMeshLayer:class{constructor(props){Object.assign(this,props);}}},map,terrain:flat,
    getRelief:()=>1,setRelief(){},refresh(){},pickTerrain:()=>picked,isWet:()=>wet});
  c.place([1.5,1.5]); c.state.wet=wet;
  for(const k of ['KeyW','ShiftLeft','KeyD']) c.driveKeys.add(k);
  const carMetres=4*55*78271.5*Math.cos(1.5*Math.PI/180)/Math.pow(2,10.5)/4/111320; // degrees per simulated car metre (the car crosses the map SPEED_SCALE=4 times faster)
  let turned=0, far=0, h=c.state.heading;
  for(let i=0;i<120;i++) { c.tick(.05); turned+=((c.state.heading-h+3*Math.PI)%(2*Math.PI))-Math.PI; h=c.state.heading;
    far=Math.max(far,Math.hypot(c.state.pos[0]-1.5,c.state.pos[1]-1.5)/carMetres); }
  return {turns:turned/2/Math.PI,far};
}
const wetSpin=spinTest(1), drySpin=spinTest(0);
assert(wetSpin.turns>1.5,`wet boost at full lock keeps spinning (${wetSpin.turns.toFixed(2)} turns in 6 s)`);
assert(wetSpin.far<12,`and stays on the spot (${wetSpin.far.toFixed(1)} m)`);
assert(drySpin.turns<.75&&drySpin.far>50,`dry tyres grip and carve a wide arc (${drySpin.turns.toFixed(2)} turns, ${drySpin.far.toFixed(0)} m)`);
// Landings: the springs take the hit, so the tyres load up then go light on the rebound; a harder landing uses up the
// travel, bottoms out and scrubs speed; in the air the body keeps the rotation it took off with.
function landing(hardness) {
  const flat={x0:0,y0:12,step:1,NR:13,NC:13,GZ:new Float32Array(169).fill(10),outline:[[[.1,.1],[11.9,.1],[11.9,11.9],[.1,11.9],[.1,.1]]],getExaggeration:()=>1};
  const c=context.window.createCarMechanics({deck:{SimpleMeshLayer:class{constructor(p){Object.assign(this,p);}}},map,terrain:flat,
    getRelief:()=>1,setRelief(){},refresh(){},pickTerrain:()=>picked,isWet:()=>0});
  c.place([6,3]); c.state.vel=[0,20]; c.tick(.01);
  events.keydown({code:'Space',repeat:false,target:{matches:()=>false},preventDefault(){}});
  c.state.jumpV*=hardness;
  const r={maxSusp:0,minSusp:0,scrub:1,airPitch:0};
  c.tick(.01); assert(c.state.jump>0,'Space leaves the ground');
  c.state.pitch=0; c.state.pitchV=.5; // nose rotating up as it leaves
  while(c.state.jump>0) { r.airPitch=c.state.pitch; c.tick(.01); }
  for(let i=0;i<150;i++) { const b=Math.hypot(...c.state.vel); c.tick(.01);
    if(i<20) r.scrub=Math.min(r.scrub,Math.hypot(...c.state.vel)/b);
    r.maxSusp=Math.max(r.maxSusp,c.state.susp); r.minSusp=Math.min(r.minSusp,c.state.susp); }
  return r;
}
const soft=landing(1), hard=landing(3);
assert(soft.maxSusp>.05&&soft.maxSusp<.15,`a plain jump compresses the springs without bottoming (${soft.maxSusp.toFixed(3)} m)`);
assert(soft.minSusp<0,'and rebounds past ride height');
assert(soft.airPitch>.2,`in the air the body keeps rotating as it took off (${soft.airPitch.toFixed(2)} rad by touchdown)`);
assert(hard.maxSusp>.14&&hard.scrub<.9,`a hard landing bottoms out and scrubs speed (kept ${(hard.scrub*100).toFixed(0)}%)`);
assert(soft.scrub>.97,`a plain landing barely slows the car (kept ${(soft.scrub*100).toFixed(0)}%)`);
// Nitro: Shift burns the tank in about 4 s, locks when empty (no boost), and refills after you let go.
{
  const flat={x0:0,y0:12,step:1,NR:13,NC:13,GZ:new Float32Array(169).fill(10),outline:[[[.1,.1],[11.9,.1],[11.9,11.9],[.1,11.9],[.1,.1]]],getExaggeration:()=>1}; // big enough not to drive off
  const c=context.window.createCarMechanics({deck:{SimpleMeshLayer:class{constructor(props){Object.assign(this,props);}}},map,terrain:flat,
    getRelief:()=>1,setRelief(){},refresh(){},pickTerrain:()=>picked,isWet:()=>0});
  c.place([1.5,1.5]); c.driveKeys.add('KeyW'); c.driveKeys.add('ShiftLeft');
  for(let i=0;i<60;i++) c.tick(.05);
  assert(c.state.nitro>.15&&c.state.nitro<.4&&c.state.boosting,`3 s of boost leaves about a quarter (${c.state.nitro.toFixed(2)})`);
  for(let i=0;i<30;i++) c.tick(.05);
  assert.equal(c.state.nitro,0); assert.equal(c.state.nitroLocked,true); assert.equal(c.state.boosting,false,'an empty tank gives no boost');
  c.driveKeys.delete('ShiftLeft');
  for(let i=0;i<60;i++) c.tick(.05);
  assert(c.state.nitro>.25&&!c.state.nitroLocked,`it refills once you let go (${c.state.nitro.toFixed(2)})`);
}
// Boat: only on the river, pointed along it, kept on the water when steered into the bank, with the relief raised for it.
{
  const flat={x0:0,y0:3,step:.01,NR:301,NC:301,GZ:new Float32Array(301*301).fill(10),outline:[[[.1,.1],[2.9,.1],[2.9,2.9],[.1,2.9],[.1,.1]]],getExaggeration:()=>1};
  const river=(lon,lat)=>lon>1.49&&lon<1.51&&lat>1&&lat<2; // a 2 km-wide river running north-south
  let reliefs=[1,1], setCalls=[];
  const b=context.window.createCarMechanics({deck:{SimpleMeshLayer:class{constructor(props){Object.assign(this,props);}}},map,terrain:flat,
    getRelief:()=>1,setRelief(){},refresh(){},pickTerrain:()=>picked,isWet:()=>0,
    waterAt:(lon,lat)=>river(lon,lat)?{top:50}:null, pickRiver:()=>null,
    setReliefs:(t,r)=>{ const before=reliefs; reliefs=[t,r]; setCalls.push([t,r]); return before; }});
  assert.equal(b.place([1.6,1.5],'boat'),false,'a boat cannot go on land');
  assert.equal(b.place([1.5,1.5],'boat'),true);
  assert.equal(b.state.vehicle,'boat');
  assert(Math.abs(Math.sin(b.state.heading))<.2,'it is pointed along the river');
  assert.deepEqual(reliefs,[2,.1],'terrain up, rivers down for the boat');
  b.driveKeys.add('KeyW'); b.driveKeys.add('KeyD');
  let left=false;
  for(let i=0;i<200;i++) { b.tick(.05); if(!river(...b.state.pos)) left=true; }
  assert.equal(left,false,'the boat never leaves the water, even steering into the bank');
  assert(Math.hypot(...b.state.vel)>0||b.state.pos[1]!==1.5,'it moves');
  b.reset();
  assert.deepEqual(reliefs,[1,1],'relief restored when the boat is put away');
  assert.equal(b.place([1.2,1.2],'car'),true,'the car still works after the boat'); assert.equal(b.state.vehicle,'car');
}
// Town dash: Start switches the towns on and names a town; arriving scores and names the next; the clock runs out.
{
  const flat={x0:0,y0:12,step:1,NR:13,NC:13,GZ:new Float32Array(169).fill(10),outline:[[[.1,.1],[11.9,.1],[11.9,11.9],[.1,11.9],[.1,.1]]],getExaggeration:()=>1};
  const places=[{name:'Alpha',lon:2,lat:9},{name:'Beta',lon:5,lat:6},{name:'Gamma',lon:9,lat:3},{name:'Outside',lon:30,lat:3}];
  let townsOn=false, redrawn=0;
  const g=context.window.createCarMechanics({deck:{SimpleMeshLayer:class{constructor(p){Object.assign(this,p);}},ScatterplotLayer:class{constructor(p){Object.assign(this,p);}},
    LineLayer:class{constructor(p){Object.assign(this,p);}},TextLayer:class{constructor(p){Object.assign(this,p);}}},map,terrain:flat,
    getRelief:()=>1,setRelief(){},refresh:()=>redrawn++,pickTerrain:()=>picked,isWet:()=>0,getPlaces:()=>places,setTowns:on=>{townsOn=on;}});
  const start=elements.find(e=>e.id==='game-start');
  assert(start,'the Start button exists when the page supplies towns');
  assert.equal(start.hidden,true,'Start stays hidden until the car is placed');
  g.place([6,6]);
  assert.equal(start.hidden,false,'placing the car reveals Start');
  assert.equal(g.game.mode,'off','placing the car does not start a game');
  start.listeners.click();
  assert.equal(townsOn,true,'Start switches the towns on');
  g.tick(.01);
  assert.equal(g.game.mode,'playing'); assert(g.game.target&&g.game.target.name!=='Outside','a town on the map is named');
  assert(g.game.left>8,`the clock allows time for the drive (${g.game.left.toFixed(1)} s)`);
  assert.equal(g.layers().filter(l=>l.id?.startsWith('dash-')).length,3,'the target is marked on the map');
  const before=g.game.left; g.tick(.05);
  assert(g.game.left<before,'the clock counts down');
  const first=g.game.target; g.state.pos=[first.lon,first.lat]; g.tick(.01);
  assert.equal(g.game.score,1,'arriving scores'); assert.notEqual(g.game.target,first,'and names a new town');
  g.game.left=.01; g.tick(.05);
  assert.equal(g.game.mode,'over','running out of time ends the game'); assert.equal(g.game.best,1);
  assert.equal(start.hidden,false,'Play again shows from the driver\'s seat');
  g.state.selected=false; g.state.placed=true; g.reset();
  assert.equal(g.game.mode,'off','the result goes when the car is taken off the map'); assert.equal(start.hidden,true,'Start hides when the car is taken off the map');
  const esc=()=>events.keydown({code:'Escape',repeat:false,target:{matches:()=>false},preventDefault(){}});
  g.place([6,6]);
  assert.equal(start.hidden,false,'replacing the car restores Start for a fresh game');
  start.listeners.click(); g.game.left=.01; g.tick(.05);
  assert.equal(g.game.mode,'over');
  esc(); assert.equal(start.hidden,true,'Play again hides when you get out of the car');
  esc(); assert.equal(start.hidden,false,'and returns when you get back in');
  start.listeners.click();
  assert.equal(g.game.mode,'playing','Play again restarts at once'); assert.equal(g.game.score,0);
}
console.log('Car placement, drag cancellation, invalid drops, animated fall, delayed reset, camera restoration, reuse, arrow keys, wet-boost donuts, landings, the nitro tank, the river boat and the town dash passed.');
// A second element with id car-dock (the gauge panel dock) once let its CSS hide the vehicle button.
for (const file of ['../6_display/template.html', '../docs/dashboard.html']) {
  const html = fs.readFileSync(__dirname + '/' + file, 'utf8');
  assert.equal((html.match(/\sid="car-dock"/g) || []).length, 0, `${file}: car-dock is the button car.js creates; no markup may reuse it`);
}
