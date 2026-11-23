# dsh-web-search-openai-compatible: a DeepSeek Harness search provider

DeepSeek Harness (`dsh`) runs models from many providers, but its own `web_search` backends need a DeepSeek key (or an Exa /
Perplexity key). This plugin registers one more search provider, `openai-compatible`: each search is one chat completions request
to a search-capable model behind any OpenAI-compatible endpoint (OpenRouter, Perplexity, Zhipu GLM, Qwen, a local server, ...).
The model's answer becomes the result's text, and the sources it cites become the result's source list.

GameAnything uses it by itself: a `dsh` run on an OpenRouter key without a DeepSeek key searches with `perplexity/sonar` on
OpenRouter (README, "DeepSeek Harness as the background agent"). This page is for using it in your own dsh.

No imports and no build: dsh loads `index.js` from wherever it is, so there is nothing to install into a profile.

## Mount it

Add two rows to a patch file: `$DSH_HOME/cordis.patch.yml` (every profile), `$DSH_HOME/profiles/<profile>/cordis.patch.yml`, or a
file given with `--patch`. The first row loads the plugin (an absolute path, or a `file://` URL on Windows), the second makes it
the search backend. Check the result with `dsh --profile <profile> --dump-config`.

```yaml
- insert:
    - id: web-search-openai-compatible
      name: /path/to/GameAnything/plugins/dsh-web-search-openai-compatible/index.js
      config:
        baseURL: https://openrouter.ai/api/v1
        apiKeyEnv: OPENROUTER_API_KEY
        model: perplexity/sonar
- id: web
  config: { searchProvider: openai-compatible, fetchProvider: http }
```

## Config

| key | meaning |
|---|---|
| `baseURL` | the endpoint including `/v1`; `/chat/completions` is appended |
| `model` | the model that searches |
| `apiKeyEnv` | where the key is: the credentials service (web / tui), else the launch environment (the process, `<cwd>/.env`, `$DSH_HOME/.env`; the headless profile has only this). Leave it out for an endpoint without a key |
| `apiKey` | a literal key instead (avoid: it then sits in the patch file) |
| `body` | extra request fields the endpoint wants: `tools`, `plugins`, `enable_search`, ... |
| `headers` | extra request headers |
| `maxTokens` | the answer's upper bound, default 1024 |

The request is sent with `Authorization: Bearer <key>` and is refused if the endpoint redirects, so the key never follows a redirect.
Sources are read from whichever of these the response has, deduplicated by URL:
`choices[0].message.annotations[].url_citation` (OpenAI, OpenRouter), `search_results` (Perplexity), `web_search` (Zhipu GLM),
`citations` (URL strings). An answer without any of them is still returned, as text only.

## Examples

OpenRouter, any model with OpenRouter's web search server tool (beta; billed per search by its engine):

```yaml
config:
  baseURL: https://openrouter.ai/api/v1
  apiKeyEnv: OPENROUTER_API_KEY
  model: deepseek/deepseek-v4-flash
  body: { tools: [ { type: "openrouter:web_search", parameters: { engine: exa, max_results: 5 } } ] }
```

Written from the providers' documentation, not yet run against them:

```yaml
# Zhipu GLM: the web_search tool; the sources come back in the response's top-level web_search list
config:
  baseURL: https://open.bigmodel.cn/api/paas/v4
  apiKeyEnv: ZHIPU_API_KEY
  model: glm-4-air
  body: { tools: [ { type: web_search, web_search: { enable: true, search_result: true } } ] }

# Qwen (DashScope compatible mode): enable_search; this mode returns no source list, so results are the answer text only
config:
  baseURL: https://dashscope.aliyuncs.com/compatible-mode/v1
  apiKeyEnv: DASHSCOPE_API_KEY
  model: qwen-plus
  body: { enable_search: true }
```

## Privacy and cost

Each search sends the query (only the query, no conversation) to `baseURL`, and through it to the search engine the endpoint
uses. Each search is a paid model request: `perplexity/sonar` on OpenRouter is $0.005 per search plus $1 per million tokens
each way (October 2026).

## Tested

With `@deepseek-ai/dsh` 0.2.1-rc.2 and 0.2.1-rc.5, profile `headless`, against a local OpenAI-compatible stand-in: loading by path and by
`file://` URL, the key from `$DSH_HOME/.env`, each source shape above, errors (HTTP 401, no key). Not yet against a real
endpoint.
