const ALLOWED_SORTS = new Set(['new', 'relevance', 'hot', 'top', 'comments']);
const MAX_LIMIT = 25;

const headers = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'public, max-age=180, s-maxage=300',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Accept',
};

let tokenCache = { token: null, expiresAt: 0 };

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

async function textOrError(response) {
  const text = await response.text();
  if (response.status === 429) {
    const error = new Error('Reddit rate limit hit. Try again in a minute.');
    error.statusCode = 429;
    throw error;
  }
  if (!response.ok) {
    let details = '';
    try {
      const parsed = JSON.parse(text);
      details = parsed?.message || parsed?.error || parsed?.reason || '';
    } catch (_) {
      details = text.trim().startsWith('<') ? 'Reddit returned an HTML block page.' : text.slice(0, 180);
    }
    const error = new Error(`Reddit returned ${response.status}${details ? `: ${details}` : ''}`);
    error.statusCode = response.status;
    throw error;
  }
  if (text.trim().startsWith('<')) {
    const error = new Error('Reddit returned HTML instead of JSON. Reddit may be blocking this endpoint.');
    error.statusCode = 502;
    throw error;
  }
  return text;
}

async function parseJsonResponse(response) {
  const text = await textOrError(response);
  try {
    return JSON.parse(text);
  } catch (_) {
    const error = new Error('Reddit returned invalid JSON.');
    error.statusCode = 502;
    throw error;
  }
}

function oauthConfigured() {
  return Boolean(process.env.REDDIT_CLIENT_ID && process.env.REDDIT_CLIENT_SECRET);
}

async function getRedditAccessToken() {
  if (!oauthConfigured()) return null;
  if (tokenCache.token && Date.now() < tokenCache.expiresAt - 60_000) {
    return tokenCache.token;
  }

  const clientId = process.env.REDDIT_CLIENT_ID;
  const clientSecret = process.env.REDDIT_CLIENT_SECRET;
  const basic = Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
  const userAgent = process.env.REDDIT_USER_AGENT || 'GridironIntelScoutNetwork/1.1 by personal fantasy football researcher';

  const response = await fetch('https://www.reddit.com/api/v1/access_token', {
    method: 'POST',
    headers: {
      Authorization: `Basic ${basic}`,
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': userAgent,
      Accept: 'application/json',
    },
    body: new URLSearchParams({ grant_type: 'client_credentials' }).toString(),
  });

  const data = await parseJsonResponse(response);
  if (!data?.access_token) {
    const error = new Error('Reddit OAuth did not return an access token. Check REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET.');
    error.statusCode = 502;
    throw error;
  }

  tokenCache = {
    token: data.access_token,
    expiresAt: Date.now() + Number(data.expires_in || 3600) * 1000,
  };
  return tokenCache.token;
}

async function fetchRedditOAuth(subreddit, q, limit, sort) {
  const token = await getRedditAccessToken();
  if (!token) {
    const error = new Error('Reddit OAuth is not configured. Add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in Netlify environment variables.');
    error.statusCode = 428;
    throw error;
  }

  const url = new URL(`https://oauth.reddit.com/r/${subreddit}/search`);
  url.searchParams.set('q', q);
  url.searchParams.set('restrict_sr', '1');
  url.searchParams.set('sort', sort);
  url.searchParams.set('t', 'month');
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('type', 'link');
  url.searchParams.set('raw_json', '1');

  const response = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
      'User-Agent': process.env.REDDIT_USER_AGENT || 'GridironIntelScoutNetwork/1.1 by personal fantasy football researcher',
    },
  });

  return parseJsonResponse(response);
}

async function fetchRedditPublicJson(base, subreddit, q, limit, sort) {
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
      Accept: 'application/json,text/plain,*/*',
      'User-Agent': process.env.REDDIT_USER_AGENT || 'GridironIntelScoutNetwork/1.1 personal fantasy football research app',
    },
  });

  return parseJsonResponse(response);
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

  const attempts = [];

  // Best path: authenticated Reddit API, when env vars are configured in Netlify.
  if (oauthConfigured()) {
    try {
      const data = await fetchRedditOAuth(subreddit, q, limit, sort);
      return json(200, normalizePosts(data, subreddit));
    } catch (err) {
      attempts.push(`OAuth API: ${err.message || err}`);
      // Continue to public JSON fallback below unless rate-limited.
      if (err.statusCode === 429) {
        return json(429, { error: err.message, attempts, fallback: 'Try again later or use Manual Paste.' });
      }
    }
  } else {
    attempts.push('OAuth API: not configured. Add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in Netlify if public JSON is blocked.');
  }

  // Fallback: legacy/public JSON endpoint. This is often blocked from hosted serverless IPs.
  const bases = ['https://www.reddit.com', 'https://old.reddit.com'];
  for (const base of bases) {
    try {
      const data = await fetchRedditPublicJson(base, subreddit, q, limit, sort);
      return json(200, normalizePosts(data, subreddit));
    } catch (err) {
      attempts.push(`${base}: ${err.message || err}`);
      if (err.statusCode === 429) break;
    }
  }

  return json(403, {
    error: 'Reddit blocked the unauthenticated/public JSON scan from this Netlify Function.',
    details: 'Netlify Functions are deployed, but Reddit is rejecting the upstream request. Configure Reddit OAuth environment variables in Netlify or use Manual Paste.',
    oauthConfigured: oauthConfigured(),
    attempts: attempts.slice(0, 5),
    fallback: 'Use the Manual Paste box in Fan Base Intel until OAuth is configured.',
  });
};
