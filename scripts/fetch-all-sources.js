import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'fs';

const NOW = new Date();
const STAT_SEASON = Number(process.env.FILM_ROOM_STATS_SEASON || NOW.getUTCFullYear() - 1);
const PROJECTION_SEASON = Number(process.env.FILM_ROOM_PROJECTION_SEASON || NOW.getUTCFullYear());
const SLEEPER_URL = 'https://api.sleeper.app/v1/players/nfl';
const SLEEPER_TREND_ADD = 'https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=24&limit=50';
const SLEEPER_TREND_DROP = 'https://api.sleeper.app/v1/players/nfl/trending/drop?lookback_hours=24&limit=50';
const NFLVERSE_WEEKLY = season => `https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_week_${season}.csv`;
const ESPN_NEWS = id => `https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?athlete=${id}&limit=5`;
const ESPN_STATS = (id, season = STAT_SEASON) => `https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/${season}/types/2/athletes/${id}/statistics`;
const ESPN_PROJECTIONS = (id, season = PROJECTION_SEASON) => `https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/${season}/types/2/athletes/${id}/projections`;
const FANTASYPROS_ECR = process.env.FILM_ROOM_FANTASYPROS_URL || 'https://www.fantasypros.com/nfl/rankings/ppr-cheatsheets.php';

const FANTASY_POSITIONS = new Set(['QB','RB','WR','TE','K','DEF','DST']);
const ESPN_ENRICH_LIMIT = Number(process.env.FILM_ROOM_ESPN_ENRICH_LIMIT || 260);
const SLEEP_MS = Number(process.env.FILM_ROOM_SOURCE_SLEEP_MS || 350);
const MIN_SLEEPER_PLAYERS = Number(process.env.FILM_ROOM_MIN_PLAYERS || 100);
const ENABLE_FANTASYPROS = process.env.FILM_ROOM_ENABLE_FANTASYPROS !== '0';

const health = {};
function startHealth(key){ health[key] = { ok:false, count:0, message:'started', started_at:new Date().toISOString(), duration_ms:null }; return Date.now(); }
function finishHealth(key, started, ok, count=0, message='ok'){
  health[key] = { ...(health[key]||{}), ok:!!ok, count:Number(count||0), message:String(message||''), duration_ms:Date.now()-started, checked_at:new Date().toISOString() };
}
function sleep(ms){ return new Promise(resolve => setTimeout(resolve, ms)); }
function normalizeName(value=''){
  return String(value).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9 ]/g,' ').replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/\s+/g,' ').trim();
}
function compactName(value=''){ return normalizeName(value).replace(/\s+/g,''); }
function clamp(n,min,max){ return Math.max(min,Math.min(max,n)); }
async function safeJson(url, label = 'json'){
  try{
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 18000);
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'FilmRoom/5.5 daily data builder', 'Accept':'application/json,text/plain,*/*' }
    });
    clearTimeout(timeout);
    if(!response.ok){ console.warn(`${label} returned ${response.status}`); return null; }
    const text = await response.text();
    if(text.trim().startsWith('<')){ console.warn(`${label} returned HTML`); return null; }
    return JSON.parse(text);
  }catch(error){ console.warn(`${label} fetch failed:`, error.message); return null; }
}
async function safeText(url, label = 'text'){
  try{
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 22000);
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'Mozilla/5.0 FilmRoom/5.5 fantasy research data builder', 'Accept':'text/html,text/csv,text/plain,*/*' }
    });
    clearTimeout(timeout);
    if(!response.ok){ console.warn(`${label} returned ${response.status}`); return ''; }
    return await response.text();
  }catch(error){ console.warn(`${label} fetch failed:`, error.message); return ''; }
}
function parseCsv(text){
  const rows=[]; let row=[]; let cell=''; let quoted=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i], next=text[i+1];
    if(quoted){ if(ch==='"'&&next==='"'){ cell+='"'; i++; } else if(ch==='"') quoted=false; else cell+=ch; }
    else if(ch==='"') quoted=true;
    else if(ch===','){ row.push(cell); cell=''; }
    else if(ch==='\n'){ row.push(cell); rows.push(row); row=[]; cell=''; }
    else if(ch!=='\r') cell+=ch;
  }
  if(cell || row.length){ row.push(cell); rows.push(row); }
  const heads=rows.shift()||[];
  return rows.filter(r=>r.length).map(values=>Object.fromEntries(heads.map((h,i)=>[h,values[i]||''])));
}
function num(row,key){ const n=Number(row?.[key]); return Number.isFinite(n)?n:0; }
function add(acc,key,value){ acc[key]=Number((acc[key]||0)+value); }
function pprFromLine(acc, pos){
  if(acc.fantasy_points_ppr) return acc.fantasy_points_ppr;
  if(pos==='QB') return acc.passing_yards*.04 + acc.passing_tds*4 + acc.rushing_yards*.1 + acc.rushing_tds*6 - acc.interceptions*2 - acc.fumbles*2;
  return acc.rushing_yards*.1 + acc.rushing_tds*6 + acc.receptions + acc.receiving_yards*.1 + acc.receiving_tds*6 - acc.fumbles*2;
}
function compactStatLine(stat){
  if(!stat) return null; const out = {};
  for(const [k,v] of Object.entries(stat)){
    if(v === null || v === undefined || v === '') continue;
    out[k] = typeof v === 'number' ? Number(v.toFixed ? v.toFixed(2) : v) : v;
  }
  return Object.keys(out).length ? out : null;
}
function mapESPNName(rawName=''){
  const key=String(rawName).toLowerCase().replace(/[^a-z0-9]/g,'');
  const map = {
    gamesplayed:'games', games:'games', gp:'games', appearances:'games', completions:'completions',
    passingattempts:'passing_attempts', attempts:'passing_attempts', passingyards:'passing_yards', passyards:'passing_yards',
    passingtouchdowns:'passing_tds', passingtds:'passing_tds', interceptions:'interceptions', passinginterceptions:'interceptions',
    rushingattempts:'carries', rushingcarries:'carries', carries:'carries', rushingyards:'rushing_yards',
    rushingtouchdowns:'rushing_tds', rushingtds:'rushing_tds', receptions:'receptions', receivingreceptions:'receptions',
    receivingtargets:'targets', targets:'targets', receivingyards:'receiving_yards', receivingtouchdowns:'receiving_tds', receivingtds:'receiving_tds',
    fumbleslost:'fumbles', fumbles:'fumbles', lostfumbles:'fumbles', fantasypoints:'fantasy_points_ppr', fantasypts:'fantasy_points_ppr',
    totalpoints:'fantasy_points_ppr', points:'fantasy_points_ppr'
  };
  return map[key] || null;
}
function collectESPNStats(raw){
  if(!raw) return null; const out = { source: 'ESPN' };
  const scan = value => {
    if(Array.isArray(value)) value.forEach(scan);
    else if(value && typeof value === 'object'){
      const statName = value.name || value.shortName || value.displayName || value.abbreviation;
      if(statName && value.value !== undefined){ const normalized = mapESPNName(statName); const n = Number(value.value); if(normalized && Number.isFinite(n)) out[normalized] = n; }
      for(const child of Object.values(value)){ if(child && (Array.isArray(child) || typeof child === 'object')) scan(child); }
    }
  };
  scan(raw);
  const has = Object.entries(out).some(([k,v]) => k !== 'source' && Number(v) > 0);
  if(!has) return null;
  out.fantasy_points_ppr = Number(pprFromLine(out, out.position || 'FLEX').toFixed(2));
  return compactStatLine(out);
}
async function fetchWeeklyStats(){
  const started=startHealth('nflverse_stats');
  for(const season of [STAT_SEASON, STAT_SEASON-1, STAT_SEASON-2]){
    const text=await safeText(NFLVERSE_WEEKLY(season), `nflverse ${season}`);
    if(!text || text.trim().startsWith('<')) continue;
    const rows=parseCsv(text); if(!rows.length) continue;
    const byName={}; const weeks={};
    for(const row of rows){
      const name=row.player_display_name||row.player_name||row.player||row.name; const position=row.position||row.pos||'';
      if(!name || !['QB','RB','WR','TE'].includes(position)) continue;
      const key=normalizeName(name); if(!key) continue;
      if(!byName[key]){ byName[key]={season, source:'nflverse', player_name:name, position, team:row.recent_team||row.team||row.posteam||'', games:0, fantasy_points_ppr:0, carries:0, rushing_yards:0, rushing_tds:0, receptions:0, targets:0, receiving_yards:0, receiving_tds:0, passing_yards:0, passing_tds:0, interceptions:0, fumbles:0}; weeks[key]=new Set(); }
      const acc=byName[key]; const wk=row.week||row.game_id||`${row.season||season}-${row.week || ''}`;
      if(wk && !weeks[key].has(wk)){ weeks[key].add(wk); acc.games=weeks[key].size; }
      add(acc,'fantasy_points_ppr',num(row,'fantasy_points_ppr')||num(row,'fantasy_points'));
      add(acc,'carries',num(row,'carries')); add(acc,'rushing_yards',num(row,'rushing_yards')); add(acc,'rushing_tds',num(row,'rushing_tds'));
      add(acc,'receptions',num(row,'receptions')); add(acc,'targets',num(row,'targets')); add(acc,'receiving_yards',num(row,'receiving_yards')); add(acc,'receiving_tds',num(row,'receiving_tds'));
      add(acc,'passing_yards',num(row,'passing_yards')); add(acc,'passing_tds',num(row,'passing_tds')); add(acc,'interceptions',num(row,'interceptions')); add(acc,'fumbles',num(row,'fumbles_lost')||num(row,'sack_fumbles_lost'));
    }
    for(const stat of Object.values(byName)) stat.fantasy_points_ppr = Number(pprFromLine(stat, stat.position).toFixed(2));
    finishHealth('nflverse_stats', started, true, Object.keys(byName).length, `loaded ${season}`);
    return { season, byName };
  }
  finishHealth('nflverse_stats', started, false, 0, 'no release parsed');
  return { season: STAT_SEASON, byName: {} };
}
function parsePossibleJson(text){
  const out=[];
  const patterns=[
    /var\s+ecrData\s*=\s*(\{[\s\S]*?\});/,
    /var\s+playerData\s*=\s*(\[[\s\S]*?\]);/,
    /var\s+players\s*=\s*(\[[\s\S]*?\]);/,
    /"players"\s*:\s*(\[[\s\S]*?\])\s*[,}]/
  ];
  for(const pattern of patterns){
    const m=text.match(pattern);
    if(!m) continue;
    try{ out.push(JSON.parse(m[1])); }catch{}
  }
  return out;
}
function rankFromAny(p, fallback){
  const keys=['rank_ecr','ecr','rank','overall_rank','rank_ave','position_rank'];
  for(const k of keys){ const n=Number(p?.[k]); if(Number.isFinite(n) && n>0) return n; }
  return fallback;
}
async function fetchFantasyProsECR(){
  const started=startHealth('fantasypros_ecr');
  if(!ENABLE_FANTASYPROS){ finishHealth('fantasypros_ecr', started, false, 0, 'disabled'); return {}; }
  const text=await safeText(FANTASYPROS_ECR, 'FantasyPros ECR');
  if(!text || text.trim().startsWith('<!DOCTYPE html>')===false && !text.includes('FantasyPros') && !text.includes('rank')){
    finishHealth('fantasypros_ecr', started, false, 0, 'empty or unexpected response'); return {};
  }
  const chunks=parsePossibleJson(text);
  const map={};
  for(const chunk of chunks){
    const list=Array.isArray(chunk) ? chunk : (chunk.players || chunk.data || []);
    if(!Array.isArray(list)) continue;
    list.forEach((p,i)=>{
      const name=(p.player_name || p.name || p.full_name || p.player || '').trim();
      if(!name) return;
      const rank=rankFromAny(p,i+1);
      map[normalizeName(name)]={
        source:'FantasyPros', ecr_rank:rank, ecr_best:Number(p.rank_min||p.best||p.low)||null, ecr_worst:Number(p.rank_max||p.worst||p.high)||null,
        ecr_avg:Number(p.rank_ave||p.avg||p.average)||null, ecr_tier:Number(p.tier)||null, ecr_adp:Number(p.adp)||null, raw_name:name
      };
    });
    if(Object.keys(map).length) break;
  }
  if(!Object.keys(map).length){
    // Last-resort lightweight HTML row parser. Kept non-fatal because page markup changes often.
    const rowRe=/<tr[\s\S]*?<\/tr>/g; let rows=text.match(rowRe)||[]; let i=0;
    for(const row of rows){
      const clean=row.replace(/<script[\s\S]*?<\/script>/g,'').replace(/<style[\s\S]*?<\/style>/g,'');
      const nameMatch=clean.match(/data-player-name=["']([^"']+)["']/) || clean.match(/class=["'][^"']*player-name[^"']*["'][^>]*>([^<]+)/);
      if(!nameMatch) continue; const name=nameMatch[1].replace(/&amp;/g,'&').trim(); if(!name) continue; i++;
      map[normalizeName(name)]={source:'FantasyPros', ecr_rank:i, ecr_best:null, ecr_worst:null, ecr_avg:null, ecr_tier:null, ecr_adp:null, raw_name:name};
    }
  }
  finishHealth('fantasypros_ecr', started, Object.keys(map).length>0, Object.keys(map).length, Object.keys(map).length ? 'parsed optional ECR' : 'no rankings parsed');
  return map;
}
function playerPasses(p){
  const positions=p.fantasy_positions || (p.position ? [p.position] : []); const pos=p.position==='DST'?'DEF':p.position;
  return p && p.active !== false && (p.team || pos==='DEF') && positions.some(x=>FANTASY_POSITIONS.has(x));
}
function newsSentiment(news=[]){
  if(!Array.isArray(news)||!news.length) return 50;
  const text=news.map(n=>`${n.headline||''} ${n.description||''}`).join(' ').toLowerCase();
  let score=50;
  ['healthy','cleared','starter','first-team','extension','breakout','impressed','strong','lead role','full practice','praised'].forEach(w=>{ if(text.includes(w)) score+=6; });
  ['injury','hurt','limited','questionable','doubtful','suspended','holdout','setback','hamstring','acl','ankle','bench'].forEach(w=>{ if(text.includes(w)) score-=8; });
  return clamp(Math.round(score),15,92);
}
function statConfidence(player){
  let count = 0;
  if(player.stats_2025) count++; if(player.espn_stats_2025) count++; if(player.projections_2026) count++;
  if(player.news?.length) count++; if(player.trending_adds || player.trending_drops) count++; if(player.depth_chart_position) count++;
  if(player.ecr_rank) count++; if(player.news_sentiment_score && player.news_sentiment_score!==50) count++;
  return Math.min(98, 34 + count * 9);
}
function normPlayer(p, index, statsMap, addMap, dropMap, ecrMap){
  const pos=p.position==='DST'?'DEF':p.position;
  const name=p.full_name || `${p.first_name||''} ${p.last_name||''}`.trim() || String(p.player_id);
  const key=normalizeName(name); const compact=compactName(name);
  const nflverseStats=statsMap[key] || null;
  const ecr=ecrMap[key] || ecrMap[compact] || null;
  return {
    player_id:String(p.player_id||p.sleeper_id||name), full_name:name, first_name:p.first_name || name.split(' ')[0], last_name:p.last_name || name.split(' ').slice(1).join(' '),
    position:pos, fantasy_positions:p.fantasy_positions || [pos], team:p.team || pos, age:p.age || null, years_exp:p.years_exp ?? null, college:p.college || '', espn_id:p.espn_id || p.metadata?.espn_id || null,
    injury_status:p.injury_status || null, depth_chart_position:p.depth_chart_position || (pos==='DEF'?1:null), search_rank:p.search_rank || 999,
    adp:ecr?.ecr_adp || p.search_rank || index + 1, trending_adds:addMap[String(p.player_id)] || 0, trending_drops:dropMap[String(p.player_id)] || 0,
    fantasypros_ecr:ecr, ecr_rank:ecr?.ecr_rank || null, ecr_best:ecr?.ecr_best || null, ecr_worst:ecr?.ecr_worst || null, ecr_tier:ecr?.ecr_tier || null, ecr_adp:ecr?.ecr_adp || null,
    nflverse_stats_2025:nflverseStats, stats_2025:nflverseStats, espn_stats_2025:null, projections_2026:null, news:[], news_sentiment_score:50,
    source_status:{sleeper:true,nflverse:!!nflverseStats,espn_stats:false,espn_projection:false,espn_news:false,trending:!!(addMap[String(p.player_id)]||dropMap[String(p.player_id)]),ecr:!!ecr,news_sentiment:false},
    last_updated:new Date().toISOString()
  };
}
async function main(){
  console.log('Film Room multi-source Phase 3 data refresh started');
  const sleeperStart=startHealth('sleeper_players'); const sleeperRaw=await safeJson(SLEEPER_URL, 'Sleeper players');
  const rawPlayers=Object.values(sleeperRaw||{}).filter(playerPasses).sort((a,b)=>(a.search_rank||999)-(b.search_rank||999));
  finishHealth('sleeper_players', sleeperStart, rawPlayers.length >= MIN_SLEEPER_PLAYERS, rawPlayers.length, `${rawPlayers.length} players`);
  if(rawPlayers.length < MIN_SLEEPER_PLAYERS){ throw new Error(`Too few Sleeper players fetched (${rawPlayers.length}); refusing to overwrite data/players.json`); }

  const trendsStart=startHealth('sleeper_trending');
  const [addsRaw, dropsRaw, stats, ecrMap] = await Promise.all([
    safeJson(SLEEPER_TREND_ADD, 'Sleeper adds'), safeJson(SLEEPER_TREND_DROP, 'Sleeper drops'), fetchWeeklyStats(), fetchFantasyProsECR()
  ]);
  const addMap={}; (Array.isArray(addsRaw)?addsRaw:[]).forEach(x=>{ if(x.player_id) addMap[String(x.player_id)]=Number(x.count||0); });
  const dropMap={}; (Array.isArray(dropsRaw)?dropsRaw:[]).forEach(x=>{ if(x.player_id) dropMap[String(x.player_id)]=Number(x.count||0); });
  finishHealth('sleeper_trending', trendsStart, true, Object.keys(addMap).length+Object.keys(dropMap).length, 'adds/drops loaded');

  const players=rawPlayers.slice(0,650).map((p,i)=>normPlayer(p,i,stats.byName,addMap,dropMap,ecrMap));

  const espnStart=startHealth('espn_enrichment');
  const espnTargets=players.filter(p=>p.espn_id).slice(0,ESPN_ENRICH_LIMIT); let enriched=0, espnStatsCount=0, espnProjectionCount=0, espnNewsCount=0, espnAttempted=0, espnMatched=0;
  for(const p of espnTargets){
    espnAttempted++;
    const [espnStatsRaw, espnProjectionRaw, newsRaw] = await Promise.all([
      safeJson(ESPN_STATS(p.espn_id, STAT_SEASON), `${p.full_name} ESPN stats`),
      safeJson(ESPN_PROJECTIONS(p.espn_id, PROJECTION_SEASON), `${p.full_name} ESPN projections`),
      safeJson(ESPN_NEWS(p.espn_id), `${p.full_name} ESPN news`)
    ]);
    const espnStats=collectESPNStats(espnStatsRaw); const espnProjection=collectESPNStats(espnProjectionRaw);
    if(espnStats){ espnStats.season = STAT_SEASON; espnStats.source = 'ESPN'; p.espn_stats_2025 = espnStats; p.stats_2025 = espnStats; p.source_status.espn_stats = true; espnStatsCount++; }
    if(espnProjection){ espnProjection.season = PROJECTION_SEASON; espnProjection.source = 'ESPN Projection'; p.projections_2026 = espnProjection; p.source_status.espn_projection = true; espnProjectionCount++; }
    if(espnStats||espnProjection||newsRaw?.articles?.length) espnMatched++;
    if(newsRaw?.articles?.length){
      p.news=newsRaw.articles.slice(0,5).map(a=>({headline:a.headline, date:a.published, url:a.links?.web?.href || a.links?.api?.href || '', description:String(a.description||'').slice(0,220), source:a.source || 'ESPN'}));
      p.news_sentiment_score = newsSentiment(p.news); p.source_status.espn_news = true; p.source_status.news_sentiment = true; espnNewsCount++;
    }
    p.source_confidence = statConfidence(p); enriched++;
    if(enriched % 40 === 0) console.log(`ESPN enriched ${enriched}/${espnTargets.length}`);
    await sleep(SLEEP_MS);
  }
  const espnSuccessRate = espnAttempted ? Math.round((espnMatched / espnAttempted) * 100) : 0;
  console.log(`ESPN enrichment: ${espnMatched}/${espnAttempted} (${espnSuccessRate}%) players matched`);
  if(espnAttempted && espnSuccessRate < 20) console.warn('ESPN API may be sparse this run. Data deck will still build from the other sources.');
  finishHealth('espn_enrichment', espnStart, true, enriched, `stats ${espnStatsCount}, projections ${espnProjectionCount}, news ${espnNewsCount}, matched ${espnSuccessRate}%`);
  for(const p of players) p.source_confidence = statConfidence(p);

  const sources=['sleeper_players','sleeper_trending','nflverse_stats','espn_stats','espn_projections','espn_news','fantasypros_ecr_optional','news_sentiment'];
  const source_counts={
    sleeper_players:players.length,
    sleeper_trending:players.filter(p=>p.trending_adds||p.trending_drops).length,
    nflverse_stats:players.filter(p=>p.nflverse_stats_2025).length,
    espn_stats:players.filter(p=>p.espn_stats_2025).length,
    espn_projections:players.filter(p=>p.projections_2026).length,
    espn_news:players.filter(p=>p.news?.length).length,
    fantasypros_ecr:players.filter(p=>p.ecr_rank).length,
    news_sentiment:players.filter(p=>p.news_sentiment_score && p.news_sentiment_score!==50).length
  };
  const payload={
    updated:new Date().toISOString(), phase:'multi-source-phase3', sources, source_counts, source_health:health,
    player_count:players.length, stat_season:stats.season, projection_season:PROJECTION_SEASON, players
  };
  mkdirSync('data',{recursive:true});
  writeFileSync('data/players.json', JSON.stringify(payload,null,2));
  console.log(`Done. Wrote ${players.length} players.`); console.log('Source counts:', source_counts); console.log('Source health:', health);
}
main().catch(error=>{ console.error(error); process.exit(1); });
