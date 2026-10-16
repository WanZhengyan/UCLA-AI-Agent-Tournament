'use strict';
const {Battle,Dex,toID}=require('pokemon-showdown');
const mk=(species,moves,ability,item,nature='Adamant',evs={hp:4,atk:252,spe:252})=>({species,moves,ability,item,nature,evs,level:50});
const teams={
 balanced:[
 mk('Incineroar',['Fake Out','Flare Blitz','Knock Off','Parting Shot'],'Intimidate','Safety Goggles','Careful',{hp:252,def:76,spd:180}),
 mk('Rillaboom',['Fake Out','Wood Hammer','Grassy Glide','U-turn'],'Grassy Surge','Assault Vest'),
 mk('Urshifu-Rapid-Strike',['Surging Strikes','Close Combat','Aqua Jet','Protect'],'Unseen Fist','Mystic Water'),
 mk('Flutter Mane',['Moonblast','Shadow Ball','Dazzling Gleam','Protect'],'Protosynthesis','Booster Energy','Timid',{hp:4,spa:252,spe:252}),
 mk('Amoonguss',['Spore','Rage Powder','Pollen Puff','Protect'],'Regenerator','Rocky Helmet','Relaxed',{hp:252,def:156,spd:100}),
 mk('Tornadus',['Bleakwind Storm','Tailwind','Taunt','Protect'],'Prankster','Covert Cloak','Timid',{hp:4,spa:252,spe:252})],
 rain:[
 mk('Pelipper',['Hurricane','Weather Ball','Tailwind','Protect'],'Drizzle','Focus Sash','Modest',{hp:4,spa:252,spe:252}),
 mk('Archaludon',['Electro Shot','Draco Meteor','Flash Cannon','Body Press'],'Stamina','Assault Vest','Modest',{hp:252,spa:252,spd:4}),
 mk('Urshifu-Rapid-Strike',['Surging Strikes','Close Combat','Aqua Jet','Protect'],'Unseen Fist','Mystic Water'),
 mk('Basculegion',['Wave Crash','Last Respects','Aqua Jet','Protect'],'Swift Swim','Life Orb'),
 mk('Rillaboom',['Fake Out','Wood Hammer','Grassy Glide','U-turn'],'Grassy Surge','Miracle Seed'),
 mk('Incineroar',['Fake Out','Flare Blitz','Knock Off','Parting Shot'],'Intimidate','Safety Goggles','Careful',{hp:252,def:76,spd:180})],
 trickroom:[
 {...mk('Indeedee-F',['Follow Me','Psychic','Helping Hand','Protect'],'Psychic Surge','Psychic Seed','Relaxed',{hp:252,def:252,spd:4}),ivs:{spe:0}},
 {...mk('Hatterene',['Trick Room','Expanding Force','Dazzling Gleam','Protect'],'Magic Bounce','Life Orb','Quiet',{hp:252,spa:252,spd:4}),ivs:{spe:0}},
 {...mk('Torkoal',['Eruption','Heat Wave','Earth Power','Protect'],'Drought','Charcoal','Quiet',{hp:252,spa:252,spd:4}),ivs:{spe:0}},
 {...mk('Ursaluna',['Facade','Headlong Rush','Earthquake','Protect'],'Guts','Flame Orb','Brave',{hp:252,atk:252,spd:4}),ivs:{spe:0}},
 {...mk('Farigiraf',['Trick Room','Psychic','Helping Hand','Protect'],'Armor Tail','Sitrus Berry','Quiet',{hp:252,def:100,spa:156}),ivs:{spe:0}},
 {...mk('Amoonguss',['Spore','Rage Powder','Pollen Puff','Protect'],'Regenerator','Rocky Helmet','Relaxed',{hp:252,def:156,spd:100}),ivs:{spe:0}}],
 offense:[
 mk('Chien-Pao',['Ice Spinner','Sucker Punch','Sacred Sword','Protect'],'Sword of Ruin','Focus Sash','Jolly'),
 mk('Dragonite',['Extreme Speed','Ice Spinner','Stomping Tantrum','Aerial Ace'],'Inner Focus','Choice Band'),
 mk('Chi-Yu',['Heat Wave','Dark Pulse','Overheat','Snarl'],'Beads of Ruin','Choice Scarf','Modest',{hp:4,spa:252,spe:252}),
 mk('Flutter Mane',['Moonblast','Shadow Ball','Dazzling Gleam','Protect'],'Protosynthesis','Booster Energy','Timid',{hp:4,spa:252,spe:252}),
 mk('Tornadus',['Bleakwind Storm','Tailwind','Taunt','Protect'],'Prankster','Covert Cloak','Timid',{hp:4,spa:252,spe:252}),
 mk('Ogerpon-Wellspring',['Ivy Cudgel','Horn Leech','Follow Me','Spiky Shield'],'Water Absorb','Wellspring Mask','Jolly')]
};
// Hand-built Regulation I archetypes, not sampled platform draft pools or
// reconstructed private replay sets. Each has two restricted Pokemon and
// distinct items. Battles still disable Tera to match the platform.
teams.regi_rain = [
 mk('Kyogre',['Water Spout','Origin Pulse','Ice Beam','Protect'],'Drizzle','Mystic Water','Modest',{hp:100,spa:252,spe:156}),
 mk('Zamazenta-Crowned',['Body Press','Heavy Slam','Wide Guard','Protect'],'Dauntless Shield','Rusted Shield','Impish',{hp:252,def:156,spe:100}),
 teams.rain[1], teams.balanced[5], teams.balanced[4], teams.balanced[0]
];
teams.regi_shadow = [
 mk('Miraidon',['Electro Drift','Draco Meteor','Volt Switch','Dazzling Gleam'],'Hadron Engine','Choice Specs','Timid',{hp:4,spa:252,spe:252}),
 mk('Calyrex-Shadow',['Astral Barrage','Psychic','Nasty Plot','Protect'],'As One (Spectrier)','Life Orb','Timid',{hp:4,spa:252,spe:252}),
 teams.balanced[0], teams.balanced[1],
 mk('Whimsicott',['Moonblast','Tailwind','Encore','Protect'],'Prankster','Covert Cloak','Timid',{hp:4,spa:252,spe:252}),
 mk('Clefairy',['Follow Me','Helping Hand','Moonblast','Protect'],'Friend Guard','Eviolite','Bold',{hp:252,def:156,spd:100})
];
teams.regi_room = [
 {...mk('Calyrex-Ice',['Glacial Lance','High Horsepower','Trick Room','Protect'],'As One (Glastrier)','Clear Amulet','Brave',{hp:252,atk:252,spd:4}),ivs:{spe:0}},
 mk('Koraidon',['Collision Course','Flare Blitz','Dragon Claw','Protect'],'Orichalcum Pulse','Life Orb','Jolly'),
 teams.trickroom[4], teams.balanced[4], teams.balanced[0], teams.trickroom[3]
];
// Authored speed-control fixture, not reconstructed private replay sets.
// Psychic Seed gives Unburden a visible activation; all six items are distinct.
teams.speed_unburden = [
 mk('Sneasler',['Poison Jab','Close Combat','Acrobatics','Protect'],'Unburden','Psychic Seed','Jolly'),
 {...mk('Indeedee-F',['Follow Me','Psychic','Helping Hand','Protect'],'Psychic Surge','Safety Goggles','Relaxed',{hp:252,def:252,spd:4}),ivs:{spe:0}},
 teams.balanced[3], teams.balanced[2], teams.balanced[5], teams.trickroom[4]
];
// Authored public-set fixtures for non-Speed Paradox activation. These are
// diagnostic teams, not reconstructed tournament teams or an optimized meta.
teams.power_booster = teams.balanced.map(p=>p.species==='Flutter Mane'
 ? {...p,nature:'Modest',evs:{hp:252,spa:252,spe:4}} : p);
teams.power_quark = [
 mk('Iron Hands',['Drain Punch','Wild Charge','Body Press','Protect'],'Quark Drive','Booster Energy','Bold',{hp:252,def:252,spd:4}),
 teams.regi_shadow[0], teams.regi_rain[1], teams.balanced[0], teams.balanced[1], teams.regi_shadow[4]
];
// Coverage extension: four-member rosters prevent preview from omitting the
// non-Speed activation under test. Not an independent tournament sample.
teams.power_booster4 = [0,1,2,3].map(i=>teams.power_booster[i]);
teams.power_quark4 = [0,1,2,5].map(i=>teams.power_quark[i]);
function publicCard(set){const sp=Dex.species.get(set.species);return {...set,card_id:toID(set.species),name:set.species,species:sp.id,types:sp.types.map(x=>x.toUpperCase()),base_stats:sp.baseStats};}
function publicSpeedEffects(p){
 // Only public activation facts: Unburden follows visible item loss on the
 // fixed public set; Paradox's selected stat is announced in the battle log.
 // Never serialize the full engine volatile state or its internal counters.
 const effects=[];
 if(p.volatiles.unburden&&!p.item&&p.ability==='unburden')effects.push('unburden');
 for(const name of ['protosynthesis','quarkdrive']){
  const stat=p.volatiles[name]?.bestStat;
  if(['atk','def','spa','spd','spe'].includes(stat))effects.push(name+stat);
 }
 return effects;
}
function mon(p, own=false){if(!p)return null; const set=p.set;return {...publicCard(set),name:p.name,species:p.baseSpecies.id,current_hp:own?p.hp:Math.ceil(100*p.hp/p.maxhp),max_hp:own?p.maxhp:100,current_hp_fraction:own?p.hp/p.maxhp:Math.ceil(100*p.hp/p.maxhp)/100,status:p.status,ability:p.ability,item:p.item,types:p.getTypes().map(t=>t.toUpperCase()),boosts:{...p.boosts},effects:publicSpeedEffects(p),moves:set.moves,stats:own?{...p.storedStats,hp:p.maxhp}:undefined,fainted:p.fainted,active:p.isActive,revealed:true};}
function targetChoices(b,p,m){
 if(!['normal','any','adjacentAlly','adjacentAllyOrSelf','adjacentFoe'].includes(m.target))return [0];
 const a=[];for(const loc of [1,2,-1,-2])if(b.validTargetLoc(loc,p,m.target)){const t=p.getAtLoc(loc);if(t&&!t.fainted)a.push(loc);}return a.length?a:[1];
}
function template(b,s){const req=s.activeRequest;const switches=s.pokemon.filter(p=>!p.fainted&&!p.isActive);const forced=req.forceSwitch;const need=forced?forced.filter(Boolean).length:0;return {type:'doubles_turn',slots:s.active.map((p,i)=>{
 let options=[];
 if(forced){if(forced[i]){options=switches.map(q=>({type:'switch',species:q.baseSpecies.id}));if(switches.length<need)options.push({type:'pass'});}else options=[{type:'pass'}];}
 else if(!p||p.fainted)options=[{type:'pass'}];
 else {const data=req.active[i];for(const v of data.moves){if(v.disabled||v.pp===0)continue;const m=Dex.moves.get(v.id);options.push({type:'move',move_id:m.id,targets:targetChoices(b,p,m),base_power:m.basePower,category:m.category.toUpperCase(),move_type:m.type.toUpperCase(),target:m.target,current_pp:v.pp,accuracy:m.accuracy===true?1:m.accuracy/100,priority:m.priority});}if(!data.trapped)options.push(...switches.map(q=>({type:'switch',species:q.baseSpecies.id})));}
 return {slot:i,board_position:-(i+1),active_pokemon:mon(p,true),options};})};}
function obs(b,s,seen){const opp=s.foe;for(const p of opp.active)if(p&&!p.fainted)seen.add(p.baseSpecies.id);return {phase:'moving',is_doubles:true,turn:b.turn,format:b.format.id,active_pokemon:s.active.map(p=>mon(p,true)),opponent_active_pokemon:opp.active.map(p=>mon(p)),team:Object.fromEntries(s.pokemon.map(p=>[`${s.id}: ${p.name}`,mon(p,true)])),opponent_team:Object.fromEntries(opp.pokemon.filter(p=>seen.has(p.baseSpecies.id)).map(p=>[`${opp.id}: ${p.name}`,mon(p)])),force_switch:s.activeRequest.forceSwitch||[false,false],weather:b.field.weather,fields:Object.keys(b.field.pseudoWeather).concat(b.field.terrain?[b.field.terrain]:[]),side_conditions:Object.keys(s.sideConditions),opponent_side_conditions:Object.keys(opp.sideConditions),clock:{decision_seconds_left:50,bank_seconds_left:420}};}
function raw(sid,version,ob,t){return {session_id:sid,state_version:version,game_type:'pokemon_vgc_doubles_draft',status:'in_progress',phase:ob.phase,observation:ob,is_current_actor:true,is_terminal:false,legal_actions:{session_id:sid,state_version:version,actions:[{action_id:t.type,input:{session_id:sid,state_version:version,action:t}}]}};}
function enumerate(t){const slots=t.slots.map(s=>s.options.flatMap(o=>o.type==='move'?o.targets.map(x=>({type:'move',move_id:o.move_id,target:x})):[o]));let out=[];for(const a of slots[0])for(const c of slots[1])if(!(a.type==='pass'&&c.type==='pass')&&!(a.type==='switch'&&c.type==='switch'&&a.species===c.species))out.push({type:'doubles_turn',slot_0:a,slot_1:c});return out;}
function baselineStat(b,p,key){const st=p.boosts[key]||0;let x=p.storedStats[key]*(st>=0?(2+st)/2:2/(2-st));if(p.item==='choiceband'&&key==='atk')x*=1.5;if(p.item==='choicespecs'&&key==='spa')x*=1.5;if(p.item==='assaultvest'&&key==='spd')x*=1.5;if(p.item==='eviolite'&&['def','spd'].includes(key))x*=1.5;if(p.ability==='guts'&&p.status&&key==='atk')x*=1.5;if(['hugepower','purepower'].includes(p.ability)&&key==='atk')x*=2;for(const [ab,stat] of [['swordofruin','def'],['beadsofruin','spd'],['tabletsofruin','atk'],['vesselofruin','spa']])if(key===stat&&p.ability!==ab&&b.sides.some(s=>s.active.some(q=>q&&!q.fainted&&q.ability===ab)))x*=.75;return x;}
function damage(b,p,t,m){if(!t||t.fainted||m.category==='Status'||!Dex.getImmunity(m.type,t))return 0;let pow=m.basePower;if(m.id==='eruption'||m.id==='waterspout')pow=150*p.hp/p.maxhp;if(m.id==='facade'&&p.status)pow=140;if(m.id==='surgingstrikes')pow=25*3*1.5;if(m.id==='lastrespects')pow=50+50*p.side.pokemon.filter(q=>q.fainted).length;if(m.id==='fakeout'&&p.activeTurns>1)return 0;const atk=baselineStat(b,p,m.category==='Physical'?'atk':'spa');const def=baselineStat(b,t,m.category==='Physical'?'def':'spd');return (22*pow*atk/def/50+2)*(p.hasType(m.type)?1.5:1)*Math.pow(2,Dex.getEffectiveness(m.type,t))*(m.accuracy===true?1:m.accuracy/100)/t.maxhp;}
function greedy(b,s,t,rng){let best=-Infinity,pick=null;for(const a of enumerate(t)){let score=0;for(let i=0;i<2;i++){const c=a[`slot_${i}`],p=s.active[i];if(c.type==='move'){const m=Dex.moves.get(c.move_id);let targets=c.target?[p.getAtLoc(c.target)]:s.foe.active;if(m.target==='allAdjacent')targets=[...targets,s.active[1-i]];for(const tar of targets){if(!tar)continue;const d=damage(b,p,tar,m);score+=(tar.side===s?-.95:1)*d*(m.target.startsWith('all')?.75:1);if(tar.side!==s&&d>=tar.hp/tar.maxhp)score+=.5;}if(m.id==='fakeout'&&p.activeTurns<=1)score+=.17;}else if(c.type==='switch'){const q=s.pokemon.find(x=>x.baseSpecies.id===c.species);score+=s.activeRequest.forceSwitch?.[i] ? Math.max(...q.set.moves.flatMap(x=>s.foe.active.map(foe=>damage(b,q,foe,Dex.moves.get(x)))))*.2 : -.5;}}
 if(score>best){best=score;pick=a;}}
 return pick;}
function command(b,s,a){if(a.type==='select_lineup'){const order=[...a.leads,...a.bring.filter(x=>!a.leads.includes(x))];return 'team '+order.map(x=>s.pokemon.findIndex(p=>toID(p.baseSpecies.id)===toID(x))+1).join('');}
 return [0,1].map(i=>{const c=a[`slot_${i}`];if(c.type==='pass')return 'pass';if(c.type==='switch')return 'switch '+(s.pokemon.findIndex(p=>toID(p.baseSpecies.id)===toID(c.species))+1);return 'move '+c.move_id+(c.target?' '+c.target:'');}).join(', ');}

module.exports={Battle,Dex,toID,teams,publicCard,mon,template,obs,raw,enumerate,greedy,command};
