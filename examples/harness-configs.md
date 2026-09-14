# Harness snippets that work against this server

Model id is `glm-5.3-flash`; the API is OpenAI-compatible on rank 0 port 8000 (or 8888 through the nginx
passthrough). Thinking is off unless you send `enable_thinking: true`; the template understands
`reasoning_effort` low / high / max (anything else falls back to max).

## DeepSeek Harness (dsh) — `.dsh/settings.yaml`

```yaml
llm-pi-ai:
  providers:
    sparks-glm-3n:
      displayName: Sparks · GLM 5.3 Flash (3 nodes)
      apiKeyEnv: SPARK_LOCAL_API_KEY        # any value if the server has no key
      api: openai-completions
      baseURL: http://<head>:8000/v1
      streamIdleTimeoutMs: 900000
      compat:
        supportsDeveloperRole: false
        supportsReasoningEffort: true
        maxTokensField: max_tokens
        thinkingFormat: chat-template
        chatTemplateKwargs:
          enable_thinking:
            $var: thinking.enabled
          reasoning_effort:
            $var: thinking.effort
            omitWhenOff: true
      models:
        - id: glm-5.3-flash
          name: GLM 5.3 Flash · 3× Sparks · 1M
          contextWindow: 1000000
          maxTokens: 65536
          input: [ text, image ]
          reasoningEfforts:
            off:
            low: low
            high: high
            xhigh: max
```

## ZCode — `~/.zcode/v2/config.json` (quit the app before editing)

```json
"custom:sparks-glm": {
  "name": "Sparks",
  "kind": "openai-compatible",
  "options": { "apiKey": "any", "baseURL": "http://<head>:8000/v1", "apiKeyRequired": true },
  "enabled": true,
  "source": "custom",
  "models": {
    "glm-5.3-flash": {
      "name": "GLM 5.3 Flash 3×",
      "reasoning": { "enabled": true, "variants": ["low", "high", "max"], "defaultVariant": "low" },
      "limit": { "context": 1000000, "output": 65536 },
      "modalities": { "input": ["text", "image"], "output": ["text"] },
      "zcode": { "modified": true, "priority": 101 }
    }
  }
}
```

## Hermes Agent — `~/.hermes/config.yaml`

```yaml
model:
  default: glm-5.3-flash
  provider: custom
  base_url: http://<head>:8000/v1
  api_key: "any"
  context_length: 1000000
  max_tokens: 65536
agent:
  reasoning_effort: low
```
Hermes' effort menu has levels the template does not know (minimal/medium/xhigh/ultra → max on the
server). A small provider plugin that maps them to low/high/max makes the menu honest; ask if you want it.

## omp — `~/.omp/agent/models.yml`

```yaml
providers:
  sparks:
    baseUrl: http://<head>:8000/v1
    models:
      - id: glm-5.3-flash
        name: GLM 5.3 Flash (3x Sparks, 1M)
        reasoning: true
        contextWindow: 1000000
        maxTokens: 65536
```

## curl

```bash
curl http://<head>:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "glm-5.3-flash",
  "messages": [{"role":"user","content":"Write a haiku about three small computers."}],
  "max_tokens": 200,
  "chat_template_kwargs": {"enable_thinking": true, "reasoning_effort": "low"}
}'
```
