// A search provider for DeepSeek Harness's web seam (ctx.web): web_search asks a search-capable model behind any OpenAI-compatible
// chat completions endpoint (OpenRouter, Perplexity, GLM, Qwen, a local server, ...) and returns its answer with the sources it cites.
// No imports: dsh can load it from any path (an `insert` row naming this file) without installing it into a profile.

export const name = "web-search-openai-compatible";
export const inject = ["web"];
export const PROVIDER_ID = "openai-compatible";

const DEFAULT_MAX_TOKENS = 1024;
const USER_AGENT = "dsh-web-search-openai-compatible/0.0.1";

/** Config (the row's `config`):
 *  baseURL     the endpoint including /v1 (e.g. https://openrouter.ai/api/v1); /chat/completions is appended
 *  model       the model that searches (e.g. perplexity/sonar on OpenRouter)
 *  apiKeyEnv   the credential name the key is read from (credentials service, then the launch environment: process, <cwd>/.env,
 *              $DSH_HOME/.env); leave it and apiKey out for an endpoint without a key (a local server)
 *  apiKey      a literal key instead (avoid: it sits in the config file)
 *  body        extra request fields, as the endpoint wants them: tools, plugins, enable_search, web_search_options, ...
 *  headers     extra request headers
 *  maxTokens   the answer's upper bound (default 1024) */
export function apply(ctx, config) {
  ctx.web.registerSearchProvider(new OpenAICompatibleSearch(ctx, config ?? {}));
}

export class OpenAICompatibleSearch {
  id = PROVIDER_ID;

  constructor(ctx, config) {
    this.ctx = ctx;
    this.config = config;
  }

  options() {
    const c = this.config;       // the row's plain config (no schema, so cordis passes it as written)
    return { ...c, baseURL: String(c.baseURL ?? "").replace(/\/+$/, ""), maxTokens: c.maxTokens ?? DEFAULT_MAX_TOKENS };
  }

  available() {
    const o = this.options();
    return URL.canParse(o.baseURL) && typeof o.model === "string" && o.model.length > 0 && Number.isInteger(o.maxTokens) && o.maxTokens > 0;
  }

  async search(request, signal) {
    const o = this.options();
    const endpoint = `${o.baseURL}/chat/completions`;
    const key = await this.apiKey(o);
    const body = {
      ...o.body,
      model: o.model,
      max_tokens: o.maxTokens,
      stream: false,
      messages: [{ role: "user", content: `Search the web for: ${request.query}\n\nAnswer briefly from what you find, and cite the URL of every source you use.` }],
    };
    let response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        redirect: "error",       // never follow a redirect with the key on it
        headers: { ...o.headers, ...(key ? { authorization: `Bearer ${key}` } : {}), "content-type": "application/json", accept: "application/json", "user-agent": USER_AGENT },
        body: JSON.stringify(body),
        ...(signal ? { signal } : {}),
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw searchError(`request to ${endpoint} failed: ${String(error)}`, error);
    }
    if (!response.ok) {
      let detail = "";
      try {
        const parsed = await response.json();
        detail = typeof parsed.error === "string" ? parsed.error : parsed.error?.message ?? parsed.message ?? "";
      } catch {}
      throw searchError(`${endpoint} answered HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
    }
    let parsed;
    try { parsed = await response.json(); }
    catch (error) {
      if (signal?.aborted) throw error;
      throw searchError(`${endpoint} returned a body that is not JSON: ${String(error)}`, error);
    }
    const content = answerOf(parsed);
    const sources = sourcesOf(parsed);
    if (!content && sources.length === 0) throw searchError(`${endpoint} (model ${o.model}) returned neither an answer nor sources`);
    return { ...(content ? { content } : {}), sources, truncated: false };
  }

  async apiKey(o) {
    if (typeof o.apiKey === "string" && o.apiKey.length > 0) return o.apiKey;
    if (!o.apiKeyEnv) return undefined;
    const stored = await this.ctx.get("credentials")?.resolve(o.apiKeyEnv);
    if (stored?.value) return stored.value;
    const launched = this.ctx.get("launchEnvironment");
    const value = launched ? launched.get(o.apiKeyEnv)?.value : process.env[o.apiKeyEnv];
    if (value) return value;
    const e = searchError(`no API key for "${o.apiKeyEnv}": put it in the launching environment or $DSH_HOME/.env`);
    e.code = "WEB_PROVIDER_CREDENTIAL_MISSING";
    throw e;
  }
}

/** The answer text: a plain string, or the text parts of a content array. */
export function answerOf(res) {
  const c = res?.choices?.[0]?.message?.content;
  if (typeof c === "string") return c.trim();
  if (Array.isArray(c)) return c.map((p) => (typeof p === "string" ? p : p?.text ?? "")).join("").trim();
  return "";
}

/** Sources in the shapes OpenAI-compatible endpoints use, deduped by URL in the order they appear:
 *  message.annotations[].url_citation {url, title, content}   OpenAI, OpenRouter (all models, Perplexity included)
 *  search_results[] {url, title, snippet, date}               Perplexity
 *  web_search[] {link, title, content, publish_date}          Zhipu GLM with the web_search tool
 *  citations[] (URL strings)                                  Perplexity, older form */
export function sourcesOf(res) {
  const seen = new Map();
  const add = (url, title, snippet, publishedAt) => {
    if (typeof url !== "string" || !/^https?:\/\//i.test(url) || seen.has(url)) return;
    seen.set(url, {
      url,
      ...(typeof title === "string" && title ? { title } : {}),
      ...(typeof snippet === "string" && snippet ? { snippet } : {}),
      ...(typeof publishedAt === "string" && publishedAt ? { publishedAt } : {}),
    });
  };
  for (const a of res?.choices?.[0]?.message?.annotations ?? []) {
    if (a?.type === "url_citation") add(a.url_citation?.url ?? a.url, a.url_citation?.title ?? a.title, a.url_citation?.content);
  }
  for (const r of list(res?.search_results)) add(r?.url, r?.title, r?.snippet, r?.date);
  for (const r of list(res?.web_search)) add(r?.link, r?.title, r?.content, r?.publish_date);
  for (const u of list(res?.citations)) add(typeof u === "string" ? u : u?.url);
  return [...seen.values()];
}

function list(v) {
  return Array.isArray(v) ? v : [];
}

function searchError(message, cause) {
  const e = new Error(`openai-compatible search: ${message}`, cause === undefined ? undefined : { cause });
  e.code = "WEB_PROVIDER_ERROR";
  return e;
}
