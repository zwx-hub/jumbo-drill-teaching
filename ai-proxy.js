// ============================================================================
// AI 教学助教 · 云端代理（Cloudflare Worker）
// ----------------------------------------------------------------------------
// 作用：把前端页面的 /chat 请求转发到 DeepSeek API。DeepSeek API Key 以
//       Worker 环境变量（Secret）保存，只存在于服务端，绝不暴露给浏览器。
// 部署步骤见 README「AI 教学助教（DeepSeek）」一节。
// ============================================================================

const DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions';
const DEFAULT_MODEL = 'deepseek-chat';

function cors(resp) {
  resp.headers.set('Access-Control-Allow-Origin', '*');
  resp.headers.set('Access-Control-Allow-Methods', 'POST, OPTIONS');
  resp.headers.set('Access-Control-Allow-Headers', 'Content-Type');
  return resp;
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8' }
  });
}

export default {
  async fetch(request, env) {
    // CORS 预检
    if (request.method === 'OPTIONS') {
      return cors(new Response(null, { status: 204 }));
    }
    // 只接受 POST 且路径以 /chat 结尾
    if (request.method !== 'POST' || !new URL(request.url).pathname.endsWith('/chat')) {
      return cors(json({ ok: false, error: 'Not Found' }, 404));
    }
    if (!env.DEEPSEEK_API_KEY) {
      return cors(json({ ok: false, error: '代理未配置 DEEPSEEK_API_KEY（Worker 环境变量）' }, 503));
    }
    let body;
    try {
      body = await request.json();
    } catch (e) {
      return cors(json({ ok: false, error: '请求体不是合法 JSON' }, 400));
    }
    const messages = body.messages;
    if (!Array.isArray(messages) || !messages.length) {
      return cors(json({ ok: false, error: '缺少 messages 参数' }, 400));
    }
    const payload = {
      model: body.model || DEFAULT_MODEL,
      messages: messages,
      max_tokens: Math.min(Math.max(parseInt(body.max_tokens, 10) || 2048, 1), 8192),
      stream: false
    };
    try {
      const resp = await fetch(DEEPSEEK_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + env.DEEPSEEK_API_KEY
        },
        body: JSON.stringify(payload)
      });
      const data = await resp.json();
      if (!resp.ok) {
        const emsg = (data && data.error && data.error.message) || '';
        let msg = 'AI 服务暂时不可用（HTTP ' + resp.status + '）';
        if (resp.status === 401) msg = 'DeepSeek API Key 无效或未授权，请检查 Worker 环境变量。';
        else if (resp.status === 402) msg = 'DeepSeek 账户余额不足，请登录 DeepSeek 开放平台充值后重试。';
        else if (resp.status === 429) msg = 'AI 请求过于频繁，请稍等片刻再试。';
        else if (emsg) msg += '（' + emsg + '）';
        return cors(json({ ok: false, error: msg }, 502));
      }
      const reply = (data.choices && data.choices[0] && data.choices[0].message)
        ? data.choices[0].message.content
        : '';
      return cors(json({ ok: true, reply: reply, model: data.model || payload.model }));
    } catch (e) {
      return cors(json({ ok: false, error: '代理转发 DeepSeek 失败' }, 502));
    }
  }
};
