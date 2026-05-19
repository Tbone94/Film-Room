const ALLOWED_SORTS = new Set(['new', 'relevance', 'hot', 'top', 'comments']);
const MAX_LIMIT = 25;

const headers = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'public, max-age=300, s-maxage=600',
  'Access-Control-Allow-Origin': '*',
};

function json(statusCode, body) {
  return { statusCode, headers, body: JSON.stringify(body) };
}

function cleanSubreddit(value) {
  return String(value || '').replace(/^r\//i, '').trim();
}

function cleanQuery(value) {
  return String(value || '').trim().slice(0, 120);
}

function normalizePosts(data, subreddit) {
  const children = data?.data?.children || [];
  return children.map((child) => {
    const d = child.data || {};
    return {
      title: d.title || 'Untitled Reddit post',
      selftext: String(d.selftext || '').slice(0, 500),
      score: Number(d.score || 0),
      numComments: Number(d.num_comments || 0),
      author: d.author || 'reddit',
      created: Number(d.created_utc || Date.now() / 1000),
      url: `https://reddit.com${d.permalink || ''}`,
      subreddit: d.subreddit || subreddit,
      upvoteRatio: Number(d.upvote_ratio || 0),
      flair: d.link_flair_text || null,
    };
  });
}

async function fetchReddit(base, subreddit, q, limit, sort) {
  const url = new URL(`${base}/r/${subreddit}/search.json`);
  url.searchParams.set('q', q);
  url.searchParams.set('restrict_sr', '1');
  url.searchParams.set('sort', sort);
  url.searchParams.set('t', 'month');
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('type', 'link');
  url.searchParams.set('raw_json', '1');

  const response = await fetch(url.toString(), {
    headers: {
      'Accept': 'application/json,text/plain,*/*',
      'User-Agent': 'GridironIntelScoutNetwork/1.0 personal fantasy football research app',
    },
  });

  const text = await response.text();
  if (response.status === 429) {
    const error = new Error('Reddit rate limit hit. Try again in a minute.');
    error.statusCode = 429;
    throw error;
  }
  if (!response.ok) {
    const error = new Error(`Reddit returned ${response.status}`);
    error.statusCode = response.status;
    throw error;
  }
  if (text.trim().startsWith('<')) {
    const error = new Error('Reddit returned HTML instead of JSON. Reddit may be blocking this public endpoint.');
    error.statusCode = 502;
    throw error;
  }

  try {
    return JSON.parse(text);
  } catch (err) {
    const error = new Error('Reddit returned invalid JSON.');
    error.statusCode = 502;
    throw error;
  }
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 204, headers, body: '' };
  }
  if (event.httpMethod !== 'GET') {
    return json(405, { error: 'Method not allowed' });
  }

  const subreddit = cleanSubreddit(event.queryStringParameters?.subreddit);
  const q = cleanQuery(event.queryStringParameters?.q);
  const requestedLimit = Number(event.queryStringParameters?.limit || 12);
  const limit = Math.max(1, Math.min(MAX_LIMIT, Number.isFinite(requestedLimit) ? requestedLimit : 12));
  const sort = ALLOWED_SORTS.has(event.queryStringParameters?.sort) ? event.queryStringParameters.sort : 'new';

  if (!subreddit || !/^[A-Za-z0-9_]+$/.test(subreddit)) {
    return json(400, { error: 'Invalid subreddit.' });
  }
  if (!q) {
    return json(400, { error: 'Missing search query.' });
  }

  const bases = ['https://www.reddit.com', 'https://old.reddit.com'];
  let lastError = null;

  for (const base of bases) {
    try {
      const data = await fetchReddit(base, subreddit, q, limit, sort);
      return json(200, normalizePosts(data, subreddit));
    } catch (err) {
      lastError = err;
      if (err.statusCode === 429) break;
    }
  }

  return json(lastError?.statusCode || 502, {
    error: lastError?.message || 'Reddit scan unavailable.',
    fallback: 'Use the Manual Paste box in Fan Base Intel.',
  });
};
