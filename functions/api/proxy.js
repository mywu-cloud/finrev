// Cloudflare Pages Function: CORS proxy for TWSE and FinMind APIs
export async function onRequest(context) {
  const url = new URL(context.request.url);
    const target = url.searchParams.get('url');
      if (!target) {
          return new Response('Missing url param', { status: 400 });
            }
              // Only allow TWSE and FinMind
                const allowed = [
                    'openapi.twse.com.tw',
                        'api.finmindtrade.com'
                          ];
                            const targetUrl = new URL(target);
                              const ok = allowed.some(h => targetUrl.hostname === h);
                                if (!ok) {
                                    return new Response('Forbidden', { status: 403 });
                                      }
                                        const resp = await fetch(target, {
                                            headers: { 'User-Agent': 'Mozilla/5.0' }
                                              });
                                                const body = await resp.arrayBuffer();
                                                  return new Response(body, {
                                                      status: resp.status,
                                                          headers: {
                                                                'Content-Type': resp.headers.get('Content-Type') || 'application/json',
                                                                      'Access-Control-Allow-Origin': '*',
                                                                            'Cache-Control': 'no-cache'
                                                                                }
                                                                                  });
                                                                                  }
