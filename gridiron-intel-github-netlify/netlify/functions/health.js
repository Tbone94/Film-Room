exports.handler = async () => {
  return {
    statusCode: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Access-Control-Allow-Origin': '*'
    },
    body: JSON.stringify({ ok: true, service: 'gridiron-intel-netlify-functions', message: 'Netlify Functions are deployed.' })
  };
};
