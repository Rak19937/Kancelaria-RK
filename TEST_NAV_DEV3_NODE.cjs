/* Behavioral menu regression without a browser or external npm packages. */
'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag = '') { this.tag = tag; this.listeners = {}; this.attrs = {}; this.classes = new Set(); this.hidden = false; this.open = false; this.value = ''; this.textContent = ''; this.title = ''; this.children = []; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  dispatch(name, value = {}) { for (const fn of this.listeners[name] || []) fn({preventDefault() {}, ...value}); }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name] ?? null; }
  contains(node) { return this === node || this.children.includes(node); }
  focus() { globalActive = this; }
  get classList() { return {toggle:(value,on) => on ? this.classes.add(value) : this.classes.delete(value),contains:(value)=>this.classes.has(value)}; }
  querySelectorAll(name) { if (name === '.nav-link') return this.links || []; if (name === '.nav-system') return this.groups || []; return []; }
}
let globalActive = null;
let now = 0;
let timers = [];
let uid = 0;
let store = new Map();
function schedule(fn, ms) { const id = ++uid; timers.push({id,at:now+ms,fn}); return id; }
function advance(ms) { now += ms; while (true) { const eligible = timers.filter(t=>t.at<=now).sort((a,b)=>a.at-b.at)[0]; if (!eligible) break; timers = timers.filter(t=>t!==eligible); eligible.fn(); } }
function fixture(savedPin = false) {
  now=0;timers=[];uid=0;store=new Map(savedPin ? [['rk.dev3.menu.pinned','1']] : []);
  const sidebar = new Element('sidebar'), trigger = new Element('trigger'), pin = new Element('pin'), finder = new Element('finder');
  const link1 = new Element('link1'), link2 = new Element('link2'), details = new Element('details');
  link1.textContent='Pulpit';link2.textContent='Ustawienia';
  details.links=[link2]; details.open = false;
  sidebar.links=[link1,link2];sidebar.groups=[details];sidebar.children=[trigger,pin,finder,link1,link2,details];
  const selectors={'.sidebar':sidebar,'[data-dev3-nav-toggle]':trigger,'[data-dev3-nav-pin]':pin,'[data-dev3-nav-filter]':finder};
  const doc = new Element('document');doc.activeElement = null;doc.body = new Element('body');
  const sandbox={document:{querySelector:(s)=>selectors[s] || null,addEventListener:(a,b)=>doc.addEventListener(a,b),get activeElement(){return globalActive},body:doc.body}, localStorage:{getItem:(x)=>store.get(x),setItem:(x,y)=>store.set(x,y)},setTimeout:schedule,clearTimeout:(id)=>{timers=timers.filter(t=>t.id!==id)},setInterval:()=>{},Date,Number,Math,String,Array,Boolean};
  globalActive=null;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'assets','rk_dev3_nav.js'),'utf8'),sandbox,{filename:'rk_dev3_nav.js'});
  return {sidebar,trigger,pin,finder,link1,link2,details,doc};
}
{
  const f=fixture();
  assert.equal(f.trigger.attrs['aria-expanded'],'false');
  f.sidebar.dispatch('mouseenter'); advance(169);
  assert.equal(f.trigger.attrs['aria-expanded'],'false');
  advance(1); assert.equal(f.trigger.attrs['aria-expanded'],'true');
  f.pin.focus();f.pin.dispatch('click');
  assert.equal(f.sidebar.classList.contains('dev3-pinned'),true);
  assert.equal(store.get('rk.dev3.menu.pinned'),'1');
  // Regression: unpin while pointer is still inside must close immediately.
  f.pin.dispatch('click');
  assert.equal(f.sidebar.classList.contains('dev3-pinned'),false);
  assert.equal(f.sidebar.classList.contains('dev3-open'),false);
  assert.equal(f.trigger.attrs['aria-expanded'],'false');
  assert.equal(store.get('rk.dev3.menu.pinned'),'0');
  advance(500);assert.equal(f.trigger.attrs['aria-expanded'],'false');
  // Explicit click can reopen without moving mouse outside first.
  f.trigger.dispatch('click'); assert.equal(f.trigger.attrs['aria-expanded'],'true');
  f.trigger.dispatch('click'); assert.equal(f.trigger.attrs['aria-expanded'],'false');
  f.sidebar.dispatch('mouseleave');advance(250);
  f.sidebar.dispatch('mouseenter');advance(180);assert.equal(f.trigger.attrs['aria-expanded'],'true');
  f.sidebar.dispatch('mouseleave');advance(250);assert.equal(f.trigger.attrs['aria-expanded'],'false');
}
{
  const f=fixture(true);
  assert.equal(f.pin.attrs['aria-pressed'],'true');
  assert.equal(f.trigger.attrs['aria-expanded'],'true');
  f.trigger.dispatch('click');
  assert.equal(f.pin.attrs['aria-pressed'],'false');
  assert.equal(f.trigger.attrs['aria-expanded'],'false');
  // Shortcut Alt+M toggles independent of hover state.
  f.doc.dispatch('keydown',{altKey:true,ctrlKey:false,shiftKey:false,key:'m'});
  assert.equal(f.trigger.attrs['aria-expanded'],'true');
  f.doc.dispatch('keydown',{altKey:true,ctrlKey:false,shiftKey:false,key:'m'});
  assert.equal(f.trigger.attrs['aria-expanded'],'false');
  f.trigger.dispatch('click'); f.trigger.focus();
  f.doc.dispatch('keydown',{key:'Escape'});
  assert.equal(f.trigger.attrs['aria-expanded'],'false');
}
{
  const f=fixture();
  f.finder.value = 'ustaw'; f.finder.dispatch('input');
  assert.equal(f.link1.hidden,true);assert.equal(f.link2.hidden,false);
  assert.equal(f.details.open,true);
  f.finder.value='';f.finder.dispatch('input');
  assert.equal(f.link1.hidden,false);assert.equal(f.details.open,false);
}
const css=fs.readFileSync(path.join(__dirname,'assets','rk_dev3_nav.css'),'utf8');
assert.match(css,/\.app\s*>\s*\.sidebar\.dev3-open/);
assert.doesNotMatch(css,/\.app\s*>\s*\.sidebar:hover/);
assert.doesNotMatch(css,/\.app\s*>\s*\.sidebar:focus-within/);
console.log('OK: menu pin/unpin/hover/click/Escape/Alt+M/filter & CSS states');
