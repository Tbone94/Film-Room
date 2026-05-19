const headers = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'public, s-maxage=86400, stale-while-revalidate=604800',
  'Access-Control-Allow-Origin': '*',
};

function normalizeName(value = '') {
  return String(value).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9 ]/g, ' ').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
}
function parseCsv(text) {
  const rows = []; let row = []; let cell = ''; let quoted = false;
  for (let i = 0; i < text.length; i++) { const ch = text[i]; const next = text[i + 1];
    if (quoted) { if (ch === '"' && next === '"') { cell += '"'; i++; } else if (ch === '"') { quoted = false; } else { cell += ch; } }
    else if (ch === '"') quoted = true; else if (ch === ',') { row.push(cell); cell = ''; }
    else if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; } else if (ch !== '\r') cell += ch;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const heads = rows.shift() || []; return rows.map(values => Object.fromEntries(heads.map((h, i) => [h, values[i] || ''])));
}
function number(row, key) { const value = Number(row[key]); return Number.isFinite(value) ? value : 0; }
function add(acc, key, value) { acc[key] = (acc[key] || 0) + value; }
async function fetchSeason(season) {
  const url = `https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_week_${season}.csv`;
  const response = await fetch(url, { headers: { 'User-Agent': 'FilmRoom/5.1 source engine (Netlify Function)' } });
  if (!response.ok) throw new Error(`nflverse returned ${response.status}`);
  return response.text();
}
exports.handler = async event => {
  try {
    const requested = Number(event.queryStringParameters?.season);
    const now = new Date(); const currentYear = now.getUTCFullYear();
    const seasons = [requested || currentYear - 1, currentYear - 2, currentYear - 3].filter((v, i, a) => Number.isFinite(v) && a.indexOf(v) === i);
    let text = ''; let season = seasons[0]; let lastError = null;
    for (const candidate of seasons) { try { text = await fetchSeason(candidate); season = candidate; break; } catch (err) { lastError = err; } }
    if (!text) throw lastError || new Error('Unable to load player stats');
    const rows = parseCsv(text); const byName = {}; const weekTracker = {};
    for (const row of rows) {
      const name = row.player_display_name || row.player_name || row.player || row.name;
      const position = row.position || row.pos || '';
      if (!name || !['QB', 'RB', 'WR', 'TE'].includes(position)) continue;
      const key = normalizeName(name); if (!key) continue;
      if (!byName[key]) { byName[key] = { player_name: name, position, team: row.recent_team || row.team || row.posteam || '', season, games: 0, fantasy_points_ppr: 0, carries: 0, rushing_yards: 0, rushing_tds: 0, receptions: 0, targets: 0, receiving_yards: 0, receiving_tds: 0, passing_yards: 0, passing_tds: 0, interceptions: 0 }; weekTracker[key] = new Set(); }
      const acc = byName[key]; const week = row.week || `${row.season || season}-${row.game_id || ''}`;
      if (week && !weekTracker[key].has(week)) { weekTracker[key].add(week); acc.games = weekTracker[key].size; }
      add(acc, 'fantasy_points_ppr', number(row, 'fantasy_points_ppr') || number(row, 'fantasy_points'));
      add(acc, 'carries', number(row, 'carries')); add(acc, 'rushing_yards', number(row, 'rushing_yards')); add(acc, 'rushing_tds', number(row, 'rushing_tds'));
      add(acc, 'receptions', number(row, 'receptions')); add(acc, 'targets', number(row, 'targets')); add(acc, 'receiving_yards', number(row, 'receiving_yards')); add(acc, 'receiving_tds', number(row, 'receiving_tds'));
      add(acc, 'passing_yards', number(row, 'passing_yards')); add(acc, 'passing_tds', number(row, 'passing_tds')); add(acc, 'interceptions', number(row, 'interceptions'));
    }
    const byLastInitial = {}; for (const [key, stat] of Object.entries(byName)) { const parts = key.split(' '); const lastInitial = `${parts.slice(1).join(' ') || parts[0]} ${parts[0]?.[0] || ''}`.trim(); byLastInitial[lastInitial] = stat; }
    return { statusCode: 200, headers, body: JSON.stringify({ ok: true, season, source: 'nflverse player_stats weekly CSV', count: Object.keys(byName).length, byName, byLastInitial }) };
  } catch (error) { return { statusCode: 500, headers: { ...headers, 'Cache-Control': 'no-store' }, body: JSON.stringify({ ok: false, error: 'Automated stats unavailable', details: error.message }) }; }
};
