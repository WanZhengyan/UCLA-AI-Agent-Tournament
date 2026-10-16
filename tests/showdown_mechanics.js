'use strict';
// Independent oracle: these assertions execute the real Showdown engine.
const assert = require('node:assert/strict');
const {Battle} = require('pokemon-showdown');
const mk = (species, moves, ability, item = '') => ({species, moves, ability, item, level: 50});
const splash = () => mk('Magikarp', ['Splash'], 'Swift Swim');
let checks = 0;
function turn(ours, theirs, a, b = 'splash', setup = () => {}) {
  const battle = new Battle({formatid: 'gen9doublescustomgame', strictChoices: true,
    seed: [10, 20, 30, 40],
    p1: {name: 'ours', team: [ours, splash()]},
    p2: {name: 'theirs', team: [theirs, splash()]}});
  battle.choose('p1', 'team 12');
  battle.choose('p2', 'team 12');
  setup(battle);
  battle.choose('p1', `move ${a}, move splash`);
  battle.choose('p2', `move ${b}, move splash`);
  return battle;
}
for (const [move, species, ability, item, expected] of [
  ['snarl', 'Milotic', 'Competitive', '', {spa: 1}],
  ['icywind', 'Kingambit', 'Defiant', '', {spe: -1, atk: 2}],
  ['icywind', 'Kingambit', 'Defiant', 'Clear Amulet', {}],
  ['partingshot', 'Kingambit', 'Defiant', '', {atk: 3, spa: -1}],
  ['partingshot', 'Serperior', 'Contrary', '', {atk: 1, spa: 1}],
]) {
  const command = move === 'partingshot' ? `${move} 1` : move;
  const b = turn(mk('Tornadus', [move], 'Inner Focus'), mk(species, ['Splash'], ability, item), command);
  for (const stat of ['atk', 'def', 'spa', 'spd', 'spe']) assert.equal(b.p2.active[0].boosts[stat], expected[stat] || 0, `${move}/${ability}/${stat}`);
  checks++;
  b.destroy();
}
{
  const b = turn(mk('Kingambit', ['Sucker Punch'], 'Inner Focus'), mk('Dragonite', ['Extreme Speed'], 'Inner Focus'), 'suckerpunch 1', 'extremespeed 1');
  assert.equal(b.p2.active[0].hp, b.p2.active[0].maxhp);
  assert.ok(b.p1.active[0].hp < b.p1.active[0].maxhp);
  checks++;
  b.destroy();
}
{
  const b = turn(mk('Serperior', ['Overheat'], 'Contrary'), mk('Snorlax', ['Splash'], 'Immunity'), 'overheat 1');
  assert.equal(b.p1.active[0].boosts.spa, 2);
  checks++;
  b.destroy();
}
{
  const b = turn(mk('Chien-Pao', ['Ice Spinner'], 'Inner Focus'), mk('Indeedee-F', ['Splash'], 'Psychic Surge'), 'icespinner 1');
  assert.equal(b.field.terrain, '');
  checks++;
  b.destroy();
}
console.log(JSON.stringify({checks, engine: 'pokemon-showdown@' + require('pokemon-showdown/package.json').version}));
