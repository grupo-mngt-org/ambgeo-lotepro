"""Cliente OpenRouter (IA) — usado pelo Motor de Bolhas.

Segue o mesmo estilo de `registry.py`: urllib puro, sem dependência externa.

Os modelos gratuitos do OpenRouter são instáveis (rate limit, indisponibilidade,
respostas malformadas). Por isso `chat()` ENCADEIA os modelos configurados em
`config.OPENROUTER_MODELS`: tenta o 1º; em qualquer falha (HTTP, timeout, corpo
sem `choices`), cai para o próximo. Se todos falharem, levanta `AIUnavailable` —
e o chamador (bolhas.analisar) degrada para o estudo determinístico.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request

from .. import config

USER_AGENT = "LotePro/0.3 (devs@grupomngt.com.br)"


class AIUnavailable(RuntimeError):
    """Nenhum modelo da cadeia respondeu (sem chave, sem rede ou todos falharam)."""


def is_configured() -> bool:
    return bool(config.OPENROUTER_KEY and config.OPENROUTER_MODELS)


def _call_model(model: str, messages: list[dict], *,
                temperature: float, max_tokens: int, json_mode: bool) -> str:
    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        config.OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            # Boa prática OpenRouter (atribuição da aplicação). Headers HTTP
            # precisam ser ASCII/latin-1 — nada de travessão/acentos aqui.
            "HTTP-Referer": "https://grupomngt.com.br",
            "X-Title": "LotePro - Motor de Bolhas",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=config.OPENROUTER_TIMEOUT) as resp:
        data = json.loads(resp.read())
    choices = data.get("choices")
    if not choices:
        raise ValueError(f"resposta sem 'choices' (modelo {model})")
    content = (choices[0].get("message") or {}).get("content")
    if not content or not content.strip():
        raise ValueError(f"conteúdo vazio (modelo {model})")
    return content


def _describe_error(model: str, e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = e.read().decode("utf-8", "ignore")[:160]
        except Exception:
            detail = ""
        return f"{model}: HTTP {e.code} {detail}"
    return f"{model}: {type(e).__name__} {e}"


def _run_bounded(fn, cap: float):
    """Roda fn() numa thread daemon com teto de tempo `cap` (s).

    Se estourar, levanta TimeoutError (a thread abandonada termina sozinha —
    daemon). Se fn levantar, repassa a exceção. Bound de RELÓGIO: serve para
    rotacionar rápido quando um modelo trava/demora (os free são imprevisíveis)."""
    box: dict = {}

    def run():
        try:
            box["ok"] = fn()
        except Exception as e:  # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(cap)
    if "ok" in box:
        return box["ok"]
    if t.is_alive():
        raise TimeoutError(f"sem resposta válida em {cap:.0f}s")
    raise box.get("err", RuntimeError("falha desconhecida"))


def chat(messages: list[dict], *, temperature: float = 0.3,
         max_tokens: int = 4000, json_mode: bool = False, validate=None,
         parallel: bool = False, deadline: float | None = None) -> dict:
    """Conversa com os modelos na ORDEM de `config.OPENROUTER_MODELS`. {content, model}.

    Estratégia padrão (`parallel=False`) = ROTAÇÃO + FALLBACK por custo: tenta o
    1º modelo (free); se falhar/erro/demorar além do teto por-modelo, ROTACIONA
    para o próximo, e assim por diante até o ÚLTIMO (que deve ser o modelo PAGO,
    garantido). Assim usa-se free quando dá, e nunca se fica sem IA. Cada modelo
    não-final tem teto curto (`OPENROUTER_FREE_TIMEOUT`); o último tem teto longo
    (`OPENROUTER_TIMEOUT`). `parallel=True` mantém o modo "corrida" (todos juntos).

    `validate(content)`: rejeita a resposta levantando exceção (ex.: modelo que
    devolve só "pensamento", sem o JSON pedido) → rotaciona.
    `deadline`: prazo TOTAL (s); esgotado, levanta AIUnavailable (→ heurístico).
    """
    if not is_configured():
        raise AIUnavailable("OpenRouter não configurado (defina open_router_key no .env).")

    models = config.OPENROUTER_MODELS
    deadline = deadline if deadline is not None else config.OPENROUTER_DEADLINE

    def attempt(model: str) -> str:
        content = _call_model(model, messages, temperature=temperature,
                              max_tokens=max_tokens, json_mode=json_mode)
        if validate is not None:
            validate(content)  # levanta → resposta rejeitada
        return content

    if not parallel:
        errors: list[str] = []
        n = len(models)
        start = time.monotonic()
        for i, model in enumerate(models):
            if time.monotonic() - start > deadline:
                break
            cap = config.OPENROUTER_TIMEOUT if i == n - 1 else config.OPENROUTER_FREE_TIMEOUT
            try:
                content = _run_bounded(lambda m=model: attempt(m), cap)
                return {"content": content, "model": model}
            except Exception as e:  # timeout, erro HTTP, validação rejeitou…
                errors.append(_describe_error(model, e))
        raise AIUnavailable("Todos os modelos falharam — " + " | ".join(errors))

    # Modo corrida (opcional): lança todos e fica com o 1º válido.
    out: queue.Queue = queue.Queue()

    def worker(model: str) -> None:
        try:
            out.put(("ok", model, attempt(model)))
        except Exception as e:
            out.put(("err", model, e))

    for m in models:
        threading.Thread(target=worker, args=(m,), name=f"ai-{m}", daemon=True).start()

    errors = []
    end = time.monotonic() + deadline
    for _ in range(len(models)):
        remaining = end - time.monotonic()
        if remaining <= 0:
            break
        try:
            status, model, payload = out.get(timeout=remaining)
        except queue.Empty:
            break
        if status == "ok":
            return {"content": payload, "model": model}
        errors.append(_describe_error(model, payload))

    raise AIUnavailable("Nenhum modelo válido no prazo — " + " | ".join(errors))


def extract_json(text: str) -> dict:
    """Extrai um objeto JSON de uma resposta de LLM, de forma tolerante.

    Varre TODOS os objetos `{...}` de nível superior (contagem de chaves,
    ignorando as que estão dentro de strings) e devolve o ÚLTIMO que faz parse.
    Modelos de raciocínio escrevem o "pensamento" antes e a resposta JSON por
    último, além de cercas markdown (```json … ```) — pegar o último objeto
    válido cobre todos esses casos. Levanta ValueError se nenhum existir.
    """
    if not text:
        raise ValueError("texto vazio")

    results: list[dict] = []
    n = len(text)
    i = 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc = 0, False, False
        j = i
        while j < n:
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        results.append(json.loads(text[i:j + 1]))
                    except Exception:
                        pass
                    break
            j += 1
        i = j + 1

    if not results:
        raise ValueError("nenhum objeto JSON válido encontrado")
    return results[-1]
