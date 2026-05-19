import { writeFileSync, mkdirSync } from 'fs';

const SEASON = Number(process.env.FILM_ROOM_STATS_SEASON || new Date().getUTCFullYear() - 1);
const SLEEPER_URL = 'https://api.sleeper.app/v1/players/nfl';
const SLEEPER_TREND_ADD = 'https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=24&limit=50';
const SLEEPER_TREND_DROP = 'https://api.sleeper.app/v1/players/nfl/trending/drop?lookback_hours=24&limit=50';
const NFLVERSE_WEEKLY = season => `https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_week_${season}.csv`;
const ESPN_NEWS = id => `https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?athlete=${id}&limit=5`;

const FANTASY_POSITIONS = new Set(['QB','RB','WR','TE','K','DEF','DST']);
const ENRICH_NEWS_LIMIT = Number(process.env.FILM_ROOM_NEWS_LIMIT || 180);
const SLEEP_MS = Number(process.env.FILM_ROOM_NEWS_SLEEP_MS || 250);

function sleep(ms){ return new Promise(resolve => setTimeout(resolve, ms)); }
function normalizeName(value=''){
  return String(value).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9 ]/g,' ').replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/\s+/g,' ').trim();
}
async function safeJson(url){
  try{
    const response = await fetch(url, { headers: { 'User-Agent': 'FilmRoom/5.3 daily data builder', 'Accept':'application/json,text/plain,*/*' } });
    if(!response.ok) return null;
    const text = await response.text();
    if(text.trim().startsWith('<')) return null;
    return JSON.parse(text);
  }catch(error){
    console.warn(`JSON fetch failed: ${url}`, error.message);
    return null;
  }
}
async function safeText(url){
  try{
    const response = await fetch(url, { headers: { 'User-Agent': 'FilmRoom/5.3 daily data builder', 'Accept':'text/csv,text/plain,*/*' } });
    if(!response.ok) return '';
    return await response.text();
  }catch(error){
    console.warn(`Text fetch failed: ${url}`, error.message);
    return '';
  }
}
function parseCsv(text){
  const rows=[]; let row=[]; let cell=''; let quoted=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i], next=text[i+1];
    if(quoted){
      if(ch==='"'&&next==='"'){ cell+='"'; i++; }
      else if(ch==='"') quoted=false;
      else cell+=ch;
    }else if(ch==='"') quoted=true;
    else if(ch===','){ row.push(cell); cell=''; }
    else if(ch==='\n'){ row.push(cell); rows.push(row); row=[]; cell=''; }
    else if(ch!=='\r') cell+=ch;
  }
  if(cell || row.length){ row.push(cell); rows.push(row); }
  const heads=rows.shift()||[];
  return rows.filter(r=>r.length).map(values=>Object.fromEntries(heads.map((h,i)=>[h,values[i]||''])));
}
function num(row,key){ const n=Number(row?.[key]); return Number.isFinite(n)?n:0; }
function add(acc,key,value){ acc[key]=(acc[key]||0)+value; }
function pprFallback(acc, pos){
  if(acc.fantasy_points_ppr) return acc.fantasy_points_ppr;
  if(pos==='QB') return acc.passing_yards*.04 + acc.passing_tds*4 + acc.rushing_yards*.1 + acc.rushing_tds*6 - acc.interceptions*2;
  return acc.rushing_yards*.1 + acc.rushing_tds*6 + acc.receptions + acc.receiving_yards*.1 + acc.receiving_tds*6;
}
async function fetchWeeklyStats(){
  for(const season of [SEASON, SEASON-1, SEASON-2]){
    const text=await safeText(NFLVERSE_WEEKLY(season));
    if(!text || text.trim().startsWith('<')) continue;
    const rows=parseCsv(text);
    if(!rows.length) continue;
    const byName={}; const weeks={};
    for(const row of rows){
      const name=row.player_display_name||row.player_name||row.player||row.name;
      const position=row.position||row.pos||'';
      if(!name || !['QB','RB','WR','TE'].includes(position)) continue;
      const key=normalizeName(name); if(!key) continue;
      if(!byName[key]){
        byName[key]={season, player_name:name, position, team:row.recent_team||row.team||row.posteam||'', games:0, fantasy_points_ppr:0, carries:0, rushing_yards:0, rushing_tds:0, receptions:0, targets:0, receiving_yards:0, receiving_tds:0, passing_yards:0, passing_tds:0, interceptions:0, fumbles:0};
        weeks[key]=new Set();
      }
      const acc=byName[key];
      const wk=row.week||row.game_id||`${row.season||season}-${row.week || ''}`;
      if(wk && !weeks[key].has(wk)){ weeks[key].add(wk); acc.games=weeks[key].size; }
      add(acc,'fantasy_points_ppr',num(row,'fantasy_points_ppr')||num(row,'fantasy_points'));
      add(acc,'carries',num(row,'carries'));
      add(acc,'rushing_yards',num(row,'rushing_yards'));
      add(acc,'rushing_tds',num(row,'rushing_tds'));
      add(acc,'receptions',num(row,'receptions'));
      add(acc,'targets',num(row,'targets'));
      add(acc,'receiving_yards',num(row,'receiving_yards'));
      add(acc,'receiving_tds',num(row,'receiving_tds'));
      add(acc,'passing_yards',num(row,'passing_yards'));
      add(acc,'passing_tds',num(row,'passing_tds'));
      add(acc,'interceptions',num(row,'interceptions'));
      add(acc,'fumbles',num(row,'fumbles_lost')||num(row,'sack_fumbles_lost'));
    }
    for(const stat of Object.values(byName)) stat.fantasy_points_ppr = Number(pprFallback(stat, stat.position).toFixed(2));
    return { season, byName };
  }
  return { season: SEASON, byName: {} };
}
function playerPasses(p){
  const positions=p.fantasy_positions || (p.position ? [p.position] : []);
  const pos=p.position==='DST'?'DEF':p.position;
  return p && p.active !== false && (p.team || pos==='DEF') && positions.some(x=>FANTASY_POSITIONS.has(x));
}
function normPlayer(p, index, statsMap, addMap, dropMap){
  const pos=p.position==='DST'?'DEF':p.position;
  const name=p.full_name || `${p.first_name||''} ${p.last_name||''}`.trim() || String(p.player_id);
  const key=normalizeName(name);
  const stats=statsMap[key] || null;
  return {
    player_id:String(p.player_id||p.sleeper_id||name),
    full_name:name,
    first_name:p.first_name || name.split(' ')[0],
    last_name:p.last_name || name.split(' ').slice(1).join(' '),
    position:pos,
    fantasy_positions:p.fantasy_positions || [pos],
    team:p.team || pos,
    age:p.age || null,
    years_exp:p.years_exp ?? null,
    college:p.college || '',
    espn_id:p.espn_id || p.metadata?.espn_id || null,
    injury_status:p.injury_status || null,
    depth_chart_position:p.depth_chart_position || (pos==='DEF'?1:null),
    search_rank:p.search_rank || 999,
    adp:p.search_rank || index + 1,
    trending_adds:addMap[String(p.player_id)] || 0,
    trending_drops:dropMap[String(p.player_id)] || 0,
    stats_2025:stats,
    news:[],
    last_updated:new Date().toISOString()
  };
}
async function main(){
  console.log('Film Room data refresh started');
  const [sleeperRaw, addsRaw, dropsRaw, stats] = await Promise.all([
    safeJson(SLEEPER_URL), safeJson(SLEEPER_TREND_ADD), safeJson(SLEEPER_TREND_DROP), fetchWeeklyStats()
  ]);
  const addMap={}; (Array.isArray(addsRaw)?addsRaw:[]).forEach(x=>{ if(x.player_id) addMap[String(x.player_id)]=Number(x.count||0); });
  const dropMap={}; (Array.isArray(dropsRaw)?dropsRaw:[]).forEach(x=>{ if(x.player_id) dropMap[String(x.player_id)]=Number(x.count||0); });
  const rawPlayers=Object.values(sleeperRaw||{}).filter(playerPasses).sort((a,b)=>(a.search_rank||999)-(b.search_rank||999));
  let players=rawPlayers.slice(0,600).map((p,i)=>normPlayer(p,i,stats.byName,addMap,dropMap));
  const newsTargets=players.filter(p=>p.espn_id).slice(0,ENRICH_NEWS_LIMIT);
  let done=0;
  for(const p of newsTargets){
    const data=await safeJson(ESPN_NEWS(p.espn_id));
    if(data?.articles?.length){
      p.news=data.articles.slice(0,5).map(a=>({headline:a.headline, date:a.published, url:a.links?.web?.href || a.links?.api?.href || '', description:String(a.description||'').slice(0,220), source:a.source || 'ESPN'}));
    }
    done++;
    if(done % 50 === 0) console.log(`News enriched ${done}/${newsTargets.length}`);
    await sleep(SLEEP_MS);
  }
  const sources=['sleeper_players','sleeper_trending','nflverse_stats','espn_news'];
  const payload={updated:new Date().toISOString(), sources, player_count:players.length, stat_season:stats.season, players};
  mkdirSync('data',{recursive:true});
  writeFileSync('data/players.json', JSON.stringify(payload,null,2));
  console.log(`Done. Wrote ${players.length} players. Stats matched: ${players.filter(p=>p.stats_2025).length}.`);
}
main().catch(error=>{ console.error(error); process.exit(1); });
