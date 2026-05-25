const headers = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'Access-Control-Allow-Origin': '*',
};

exports.handler = async () => ({
  statusCode: 200,
  headers,
  body: JSON.stringify({
    ok: true,
    service: 'commanders-pulse-functions',
    message: 'Commanders Pulse Netlify Functions are deployed.',
    timestamp: new Date().toISOString(),
  }),
});
