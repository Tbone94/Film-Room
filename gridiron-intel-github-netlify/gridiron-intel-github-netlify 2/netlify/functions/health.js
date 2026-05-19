const headers = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'Access-Control-Allow-Origin': '*',
};

exports.handler = async () => {
  return {
    statusCode: 200,
    headers,
    body: JSON.stringify({
      ok: true,
      service: 'gridiron-intel-netlify-functions',
      message: 'Netlify Functions are deployed.',
      redditOAuthConfigured: Boolean(process.env.REDDIT_CLIENT_ID && process.env.REDDIT_CLIENT_SECRET),
      hasRedditUserAgent: Boolean(process.env.REDDIT_USER_AGENT),
      timestamp: new Date().toISOString(),
    }),
  };
};
