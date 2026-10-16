'use strict';
// Same public observations for both policies; each runs in an isolated process.
const {spawn}=require('node:child_process');
const readline=require('node:readline');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {Battle,toID,teams,publicCard,template,obs,raw,command}=require('./showdown_support');
const dirs=[process.env.A_DIR,process.env.B_DIR].map(p=>path.resolve(p));
const output=path.resolve(process.env.RESULT_DIR);
if(fs.existsSync(output)) throw new Error('Refusing to overwrite an existing experiment');
fs.mkdirSync(output,{recursive:true});
function hashes(dir){return Object.fromEntries(fs.readdirSync(path.join(dir,'pokemon_bot')).filter(x=>x.endsWith('.py')||x==='dex_data.json').sort().map(x=>[x,crypto.createHash('sha256').update(fs.readFileSync(path.join(dir,'pokemon_bot',x))).digest('hex')]));}
const before=dirs.map(hashes);
function client(dir){
  const child=spawn(process.env.PYTHON,['tests/bridge.py'],{cwd:dir,stdio:['pipe','pipe','pipe'],env:{...process.env,POKEMON_BOT_NO_CACHE:'1'}});
  let pending=null,stderr='',dead=false;
  const latency=[];
  child.stderr.on('data',x=>stderr+=x);
  child.on('exit',code=>{dead=true;if(pending)pending.reject(new Error('Policy exited '+code+' '+stderr));});
  readline.createInterface({input:child.stdout}).on('line',line=>{
    if(!pending)return;
    try{pending.resolve(JSON.parse(line));}catch(e){pending.reject(e);}finally{pending=null;}
  });
  return {child,latency,get stderr(){return stderr;},async ask(payload){
    if(dead)throw new Error('Policy process already exited');
    if(pending)throw new Error('Only one outstanding request per policy');
    const start=performance.now();let timer;
    const result=await new Promise((resolve,reject)=>{timer=setTimeout(()=>reject(new Error('Decision exceeded 15 seconds')),15000);pending={resolve,reject};child.stdin.write(JSON.stringify(payload)+'\n');}).finally(()=>clearTimeout(timer));
    latency.push(performance.now()-start);
    if(result.bridge_error||result.error||result.diagnostics?.fallback)throw new Error('Invalid/fallback policy result: '+JSON.stringify(result));
    return result.action;
  }};
}
const clients=dirs.map(client);
const usedSessions=new Set();
const suite=process.env.COMPARE_SUITE||'core';
const suites={
 core:[['balanced','rain'],['rain','balanced'],['trickroom','balanced'],['balanced','offense'],['offense','rain'],['trickroom','offense']],
 regi:[['regi_rain','regi_shadow'],['regi_shadow','regi_room'],['regi_room','regi_rain'],['regi_rain','rain']],
 speed:[['speed_unburden','balanced'],['speed_unburden','offense'],['rain','offense'],['trickroom','speed_unburden']],
 mirror:['power_booster','power_quark','offense','rain'].map(name=>[name,name]),
 paradox_mirror:['power_booster4','power_quark4'].map(name=>[name,name]),
 paradox:[['power_booster','offense'],['power_quark','regi_rain']]
};
if(!suites[suite])throw new Error('Unknown COMPARE_SUITE; use core, regi, speed, mirror, or paradox');
const pairs=suites[suite];
async function game(pair,swap,n,reverseTeams=false){
  if(reverseTeams)pair=[...pair].reverse();
  const lineup=[teams[pair[swap?1:0]],teams[pair[swap?0:1]]];
  const seed=[7123+n,8193+13*n,8917+7*n,9341+19*n];
  const b=new Battle({formatid:'gen9doublescustomgame@@@Picked Team Size = 4,Terastal Clause,Adjust Level = 50',seed,strictChoices:true,p1:{name:swap?'B':'A',team:lineup[0]},p2:{name:swap?'A':'B',team:lineup[1]}});
  const sessionIds=[0,1].map(policy=>`offline-compare-${n}-${swap}-${reverseTeams}-${policy}`);
  for(const sid of sessionIds){if(usedSessions.has(sid))throw new Error('Duplicate game session: '+sid);usedSessions.add(sid);}
  const versions=[0,0],seen=[new Set(),new Set()],decisions=[];
  let steps=0;
  try{
    while(!b.ended&&steps++<160){
      const pending=b.sides.filter(s=>s.activeRequest&&!s.activeRequest.wait&&!s.isChoiceDone());
      if(!pending.length)throw new Error('No pending request');
      const choices=[];
      for(const side of pending){
        const position=side.n,policy=swap?1-position:position;
        const sid=sessionIds[policy];
        let ob,t;
        if(side.activeRequest.teamPreview){
          ob={phase:'team_preview',your_roster:lineup[position].map(publicCard),opponent_roster:lineup[1-position].map(publicCard)};
          t={type:'select_lineup',roster:lineup[position].map(x=>toID(x.species))};
        }else{t=template(b,side);ob=obs(b,side,seen[position]);}
        const action=await clients[policy].ask(raw(sid,versions[position]++,ob,t)).catch(error=>{
          error.gameContext={policy:policy===0?'A':'B',phase:ob.phase,turn:b.turn,pair,swap,reverseTeams,seed};
          throw error;
        });
        decisions.push({turn:b.turn,policy:policy===0?'A':'B',phase:ob.phase,action});
        choices.push([side,command(b,side,action)]);
      }
      for(const [side,choice] of choices)if(!b.choose(side.id,choice))throw new Error('Illegal choice: '+choice);
    }
    const result={pair,swap,reverseTeams,seed,winner:b.winner||'incomplete',turns:b.turn,steps};
    fs.writeFileSync(path.join(output,`game-${n}-${swap}-${reverseTeams}.json`),JSON.stringify({result,decisions,log:b.log},null,2));
    return result;
  }finally{b.destroy();}
}
(async()=>{
  const count=Number(process.argv[2]||24),offset=Number(process.argv[3]||1000),results=[];
  // Identical rosters need seat swaps only: reversing the teams would replay
  // the very same game/seed, not provide another independent observation.
  const mirrorSuite=['mirror','paradox_mirror'].includes(suite);
  const blockSize=mirrorSuite?2:4;
  if(count%blockSize)throw new Error('Use complete team/seat swap blocks');
  for(let i=0;i<count/blockSize;i++)for(const reverseTeams of mirrorSuite?[false]:[false,true])for(const swap of [false,true]){
    const r=await game(pairs[i%pairs.length],swap,offset+i,reverseTeams);results.push(r);console.log(JSON.stringify(r));
  }
  const after=dirs.map(hashes);
  const latency=clients.map(c=>{const a=[...c.latency].sort((x,y)=>x-y);return {decisions:a.length,median:a[Math.floor(a.length*.5)],p95:a[Math.floor(a.length*.95)],max:a.at(-1)};});
  const summary=results.reduce((s,r)=>(s[r.winner]=(s[r.winner]||0)+1,s),{});
  const report={dirs,suite,before,after,codeUnchanged:JSON.stringify(before)===JSON.stringify(after),uniqueSessions:usedSessions.size,engine:'pokemon-showdown@0.11.11',results,summary,latency,stderr:clients.map(c=>c.stderr),limitations:['Handmade rosters, no online matchmaking or draft benchmark.','The same fixed sets are public to both policies; opponent HP is rounded to displayed percent.','Seed-paired team and seat swaps, but RNG can diverge after decisions diverge.','No Tera; the regi suite includes two-restricted archetypes, not the actual platform card pool.']};
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({summary,latency,codeUnchanged:report.codeUnchanged}));
})().catch(e=>{
  fs.writeFileSync(path.join(output,'failure.json'),JSON.stringify({error:e.message,context:e.gameContext||null,before,after:dirs.map(hashes)},null,2));
  console.error(e);process.exitCode=1;
}).finally(()=>clients.forEach(c=>c.child.kill()));
