"""Motor de Bolhas — qual "Bolha Incrível" desenvolver num terreno.

Codifica a *prateleira de produtos* do Plano Incrível (Área Incrível, jun/2026):
linhas, arquétipos de bolha, programas acopláveis e as faixas do Minha Casa,
Minha Vida (2026). Sobre as variáveis JÁ medidas de um lote (área, declividade,
testada, formato, infraestrutura do entorno e acesso — vindas de enrich.py/
score.py), este módulo:

  1. ranqueia as bolhas de forma DETERMINÍSTICA (`score_fit`) — serve de
     fundamento para a IA e de FALLBACK quando a IA está indisponível;
  2. infere a faixa MCMV provável a partir do entorno (`infer_faixa`);
  3. estima a viabilidade econômica dentro do teto da faixa
     (`viabilidade_economica`);
  4. monta o estudo de viabilidade completo via IA (`analisar`) — a "caixa de
     produto" do documento: bolha recomendada, score de aplicabilidade, público,
     promessa, módulos, programas, riscos, checklist e próximos passos.

Honestidade do método (igual ao score técnico): isto automatiza a TRIAGEM de
produto que a equipe faz hoje à mão. A decisão final de comitê, a due diligence
e o orçamento real continuam etapas obrigatórias.
"""
from __future__ import annotations

import json
import re

from . import ai

# ---------------------------------------------------------------------------
# Minha Casa, Minha Vida — faixas de 2026 (documento, item 8).
# `preco_ref`: valor de referência por unidade. F3/F4 são os TETOS oficiais do
# programa; F1/F2 são referências de mercado ajustáveis (o programa não fixa
# teto explícito nessas faixas no documento) — rotuladas como tal na saída.
# ---------------------------------------------------------------------------
MCMV_FAIXAS_2026 = {
    1: {"renda_max": 3_200, "preco_ref": 200_000, "teto_oficial": False,
        "label": "Faixa 1 (renda até R$ 3.200)"},
    2: {"renda_max": 5_000, "preco_ref": 264_000, "teto_oficial": False,
        "label": "Faixa 2 (renda até R$ 5.000)"},
    3: {"renda_max": 9_600, "preco_ref": 400_000, "teto_oficial": True,
        "label": "Faixa 3 (renda até R$ 9.600 · teto R$ 400 mil)"},
    4: {"renda_max": 13_000, "preco_ref": 600_000, "teto_oficial": True,
        "label": "Faixa 4 (renda até R$ 13.000 · teto R$ 600 mil)"},
}

# Linhas de produto (documento, item 10.3).
LINHAS = {
    "Área Conquista": "Porta de entrada para a casa própria: clareza, dignidade, "
                      "segurança e acessibilidade máxima.",
    "Área Conforto": "Produto familiar de custo-benefício, previsibilidade, "
                     "segurança e lazer simples.",
    "Área Detalhe": "Aspiracional dentro do MCMV/classe média: qualidade "
                    "percebida, refúgio, lazer e fachada sem virar alto padrão.",
    "Área Estilo": "Identidade, design e comportamento — jovem, urbano e "
                   "digital; pertencimento, não preço alto.",
    "Área +Vida": "Momento de vida 50+/60+ ativo: autonomia, segurança, "
                  "comunidade, bem-estar e baixa manutenção.",
}

# Programas acopláveis (institucionais) — item 10.3.
PROGRAMAS = {
    "area_segura": {
        "nome": "Área Segura",
        "desc": "Segurança de contexto: câmeras, iluminação, controle de acesso, "
                "desenho menos exposto e integração com sistemas públicos quando aplicável.",
    },
    "arte_incrivel": {
        "nome": "Arte Incrível",
        "desc": "Ressignificação estética e simbólica do território por arte, "
                "grafite e intervenções que criam orgulho e identidade.",
    },
}

# Arquétipos de bolha (documento, item 10.4). `urbanidade_ideal` (0..1) é um
# proxy do quão consolidado/servido o entorno deve estar para o produto fazer
# sentido — usado só no ranking determinístico.
BOLHAS = {
    "conquista_seguranca_discreta": {
        "linha": "Área Conquista", "nome": "Conquista Segurança Discreta",
        "tese": "Contexto periférico ou sensível, onde o cliente quer conquistar "
                "a casa própria sem se sentir exposto. Conquista segura, acessível e discreta.",
        "faixa_mcmv": [1, 2], "publico": "1ª casa própria, saindo do aluguel, renda baixa.",
        "area_ideal_m2": [2_000, 40_000], "max_slope_pct": 18.0, "urbanidade_ideal": 0.35,
        "promessa": "Conquistar a casa própria com segurança e dignidade, sem ostentação.",
        "modulos": ["módulo de segurança", "iluminação", "fachada coerente", "portaria"],
        "programas": ["area_segura"],
        "cuidados": "Custo extremamente controlado; segurança e iluminação proporcionais; "
                    "não criar ostentação nem lazer exposto.",
    },
    "conquista_bosque": {
        "linha": "Área Conforto", "nome": "Conquista/Conforto Bosque",
        "tese": "Produto de entrada ou familiar que usa natureza simples, sombra e "
                "convivência verde como valor percebido central.",
        "faixa_mcmv": [1, 2, 3], "publico": "Famílias em formação que valorizam verde e sossego.",
        "area_ideal_m2": [5_000, 80_000], "max_slope_pct": 22.0, "urbanidade_ideal": 0.45,
        "promessa": "Morar com verde, sombra e convivência — natureza como protagonista.",
        "modulos": ["bosque/área verde", "praça", "playground", "quiosque"],
        "programas": ["arte_incrivel"],
        "cuidados": "Evitar paisagismo caro ou manutenção complexa; o bosque precisa ser "
                    "protagonista, não decoração genérica.",
    },
    "detalhe_santorini": {
        "linha": "Área Detalhe", "nome": "Detalhe Santorini",
        "tese": "Aspiracional que transforma estética, fachada, cor, praça, varandas e "
                "narrativa em sensação de férias, detalhe e pertencimento.",
        "faixa_mcmv": [3, 4], "publico": "Classe média acessível que busca refúgio e estética.",
        "area_ideal_m2": [8_000, 120_000], "max_slope_pct": 20.0, "urbanidade_ideal": 0.65,
        "promessa": "Sensação de férias o ano todo: estética, cor e detalhe acessíveis.",
        "modulos": ["fachada autoral", "praça", "varanda gourmet", "lazer", "paisagismo"],
        "programas": ["arte_incrivel", "area_segura"],
        "cuidados": "Piloto de aprendizado; separar essência de acessório; medir custo e "
                    "construtibilidade. Não confundir com alto padrão.",
    },
    "detalhe_minha_praia": {
        "linha": "Área Detalhe", "nome": "Detalhe Minha Praia, Minha Vida",
        "tese": "Resort popular / férias acessíveis dentro da restrição econômica, "
                "possivelmente dependente de grande escala.",
        "faixa_mcmv": [3, 4], "publico": "Famílias que querem lazer tipo resort cabendo no bolso.",
        "area_ideal_m2": [30_000, 300_000], "max_slope_pct": 15.0, "urbanidade_ideal": 0.55,
        "promessa": "Resort acessível: lazer de férias dentro da conta do MCMV.",
        "modulos": ["lazer aquático", "praça central", "quiosques", "academia", "salão"],
        "programas": ["area_segura"],
        "cuidados": "Não executar em escala pequena sem a conta fechar; não confundir com alto padrão.",
    },
    "estilo_compacto_autoral": {
        "linha": "Área Estilo", "nome": "Estilo Compacto Autoral",
        "tese": "Casas/sobrados compactos jovens, digitais, urbanos e identitários; "
                "design acessível e espaços compartilhados simples no térreo.",
        "faixa_mcmv": [2, 3, 4], "publico": "Jovens/solo/casais urbanos, perfil digital e identitário.",
        "area_ideal_m2": [1_000, 20_000], "max_slope_pct": 20.0, "urbanidade_ideal": 0.85,
        "promessa": "Viver com estilo e identidade num endereço urbano e conectado.",
        "modulos": ["casa compacta autoral", "coworking térreo", "fachada autoral",
                    "bicicletário", "praça de convivência"],
        "programas": ["arte_incrivel"],
        "cuidados": "Não confundir estilo com acabamento caro; localização e público precisam "
                    "estar muito bem aderentes. Mantém-se horizontal (casas/sobrados), nunca torre.",
    },
    "mais_vida_bem_estar": {
        "linha": "Área +Vida", "nome": "+Vida Vila de Bem-estar",
        "tese": "Autonomia, segurança, convivência e baixa manutenção para 50+/60+ ativo.",
        "faixa_mcmv": [3, 4], "publico": "50+/60+ ativos buscando autonomia, segurança e bem-estar.",
        "area_ideal_m2": [10_000, 120_000], "max_slope_pct": 8.0, "urbanidade_ideal": 0.6,
        "promessa": "Envelhecer com autonomia, segurança e convivência, com baixa manutenção.",
        "modulos": ["acessibilidade universal", "área de convivência", "saúde/bem-estar",
                    "horta", "segurança"],
        "programas": ["area_segura"],
        "cuidados": "Cuidado com custo de operação, condomínio, acessibilidade e credibilidade "
                    "da promessa. Terreno plano é decisivo.",
    },
}

AVISO_METODO = (
    "Estudo gerado por IA a partir das variáveis medidas do terreno e do entorno. "
    "Automatiza a triagem de produto que a equipe faz à mão — não substitui a "
    "decisão de comitê, a due diligence legal, o orçamento real nem o projeto executivo."
)


# ---------------------------------------------------------------------------
# Catálogo público (para o frontend / endpoint GET /api/bolhas)
# ---------------------------------------------------------------------------
def catalogo() -> dict:
    return {
        "linhas": [{"nome": k, "desc": v} for k, v in LINHAS.items()],
        "programas": [{"key": k, **v} for k, v in PROGRAMAS.items()],
        "faixas_mcmv": [{"faixa": f, **info} for f, info in MCMV_FAIXAS_2026.items()],
        "bolhas": [{"key": k, **{kk: vv for kk, vv in b.items()}} for k, b in BOLHAS.items()],
    }


# ---------------------------------------------------------------------------
# Métricas do lote a partir das propriedades do resultado (GeoJSON/colunas)
# ---------------------------------------------------------------------------
def metrics_from_props(props: dict) -> dict:
    """Extrai as variáveis relevantes de um lote (feature de resultado).

    `infra`/`access` (0..1) saem do score_breakdown salvo por score.py — são o
    melhor proxy disponível de urbanização do entorno sem nova consulta.
    """
    infra = access = None
    bd = props.get("score_breakdown")
    if bd:
        try:
            bd = json.loads(bd) if isinstance(bd, str) else bd
            infra = (bd.get("infra") or {}).get("score")
            access = (bd.get("access") or {}).get("score")
        except Exception:
            pass
    return {
        "area_m2": float(props.get("area_m2") or 0.0),
        "slope_pct": props.get("slope_pct"),
        "frontage_m": props.get("frontage_m"),
        "compactness": props.get("compactness"),
        "infra": infra,
        "access": access,
        "viab_score": props.get("score"),
        "zoning": props.get("zoning"),
        "flags": props.get("flags") or "",
    }


def _urbanidade(metrics: dict) -> float:
    """Proxy 0..1 de consolidação urbana do entorno (infra + acesso)."""
    infra = metrics.get("infra")
    access = metrics.get("access")
    vals = [v for v in (infra, access) if v is not None]
    if not vals:
        return 0.4  # neutro quando não há dado
    # infra pesa mais que acesso para "renda/urbanização" do entorno
    if infra is not None and access is not None:
        return round(infra * 0.7 + access * 0.3, 3)
    return round(sum(vals) / len(vals), 3)


def _fit_area(area: float, lo: float, hi: float) -> float:
    if area <= 0:
        return 0.0
    if lo <= area <= hi:
        return 1.0
    return round(max(0.0, area / lo) if area < lo else max(0.0, hi / area), 3)


def score_fit(bolha: dict, metrics: dict, faixa: int | None = None) -> float:
    """Aderência DETERMINÍSTICA (0..100) de uma bolha a um lote.

    Combina: área-alvo (35%), declividade vs teto (20%), urbanidade do entorno
    vs ideal da bolha (35%), testada/acesso (10%). Critérios sem dado não punem.
    `faixa` (1..4): penaliza bolha cuja faixa-alvo não inclui a faixa do contexto.
    """
    area = _fit_area(metrics["area_m2"], *bolha["area_ideal_m2"])

    slope = metrics.get("slope_pct")
    if slope is None:
        slope_fit = 0.7  # sem dado: neutro levemente positivo
    else:
        slope_fit = 1.0 if slope <= bolha["max_slope_pct"] else \
            max(0.0, 1.0 - (slope - bolha["max_slope_pct"]) / 15.0)

    urb = _urbanidade(metrics)
    urb_fit = round(1.0 - abs(urb - bolha["urbanidade_ideal"]), 3)

    acc = metrics.get("access")
    acc_fit = acc if acc is not None else 0.6
    if "encravado" in (metrics.get("flags") or ""):
        acc_fit = min(acc_fit, 0.2)

    final = area * 0.35 + slope_fit * 0.20 + urb_fit * 0.35 + acc_fit * 0.10
    # Compatibilidade de faixa: uma bolha aspiracional (F3/F4) não deve liderar
    # num contexto de F1. Penaliza (sem zerar — segue aparecendo como alternativa).
    if faixa and faixa not in bolha["faixa_mcmv"]:
        final *= 0.6
    return round(final * 100.0, 1)


def rank_bolhas(metrics: dict, faixa: int | None = None) -> list[dict]:
    """Todas as bolhas ordenadas por aderência determinística ao lote.

    `faixa` (1..4): quando informada, prioriza bolhas compatíveis com a faixa
    MCMV do contexto — evita parear produto aspiracional com renda baixa."""
    out = [{"key": k, "nome": b["nome"], "linha": b["linha"],
            "score": score_fit(b, metrics, faixa)} for k, b in BOLHAS.items()]
    return sorted(out, key=lambda x: x["score"], reverse=True)


def infer_faixa(metrics: dict) -> int:
    """Faixa MCMV provável (1..4) pelo proxy de urbanização do entorno."""
    urb = _urbanidade(metrics)
    if urb >= 0.75:
        return 4
    if urb >= 0.55:
        return 3
    if urb >= 0.35:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Viabilidade econômica (módulo) — "a conta fecha?" (Apêndice A)
# ---------------------------------------------------------------------------
def viabilidade_economica(faixa: int, units: int | None,
                          area_m2: float, margem_alvo: float = 0.18) -> dict:
    """Estimativa de VGV e custo-alvo dentro do teto da faixa MCMV.

    `units`: do Estudo de Implantação salvo, se houver; senão estima por
    densidade (~1 unidade / 250 m² de gleba) — claramente rotulado como estimativa.
    Tudo é referência ajustável: o custo-alvo é o MÁXIMO admissível para atingir
    a `margem_alvo`, não uma promessa de margem.
    """
    info = MCMV_FAIXAS_2026.get(faixa, MCMV_FAIXAS_2026[2])
    preco = info["preco_ref"]
    estimado = units is None
    if estimado:
        units = max(1, int(area_m2 / 250.0)) if area_m2 else None
    vgv = (units or 0) * preco
    custo_alvo = round(vgv * (1.0 - margem_alvo))
    return {
        "faixa": faixa,
        "faixa_label": info["label"],
        "preco_unidade_ref": preco,
        "preco_teto_oficial": info["teto_oficial"],
        "unidades": units,
        "unidades_estimadas": estimado,
        "vgv_estimado": vgv,
        "margem_alvo": margem_alvo,
        "custo_alvo_max": custo_alvo,
        "observacao": (
            "Valores de REFERÊNCIA ajustáveis. "
            + ("Nº de unidades estimado por densidade — rode o Estudo de Implantação "
               "para precisar. " if estimado else "Nº de unidades vindo do Estudo de Implantação. ")
            + ("Preço = TETO oficial do programa nesta faixa. " if info["teto_oficial"]
               else "Preço-unidade é referência de mercado (a faixa não fixa teto explícito). ")
            + f"Custo-alvo = máximo (terreno+obra+indiretos) para margem de "
              f"{int(margem_alvo*100)}%."
        ),
    }


# ---------------------------------------------------------------------------
# Orquestrador: estudo de viabilidade completo (IA + determinístico)
# ---------------------------------------------------------------------------
def _prateleira_resumo() -> str:
    linhas = []
    for k, b in BOLHAS.items():
        faixas = "/".join(f"F{f}" for f in b["faixa_mcmv"])
        linhas.append(
            f"- {k} | {b['nome']} ({b['linha']}, {faixas}): {b['tese']} "
            f"NÃO-USO: {b['cuidados']}")
    return "\n".join(linhas)


def _build_messages(metrics: dict, endereco: dict, lote: dict,
                    ranking: list[dict], faixa_sugerida: int,
                    target_faixa: int | None) -> list[dict]:
    addr = ", ".join(str(x) for x in (
        endereco.get("logradouro"), endereco.get("bairro"),
        endereco.get("cidade"), endereco.get("uf")) if x) or "endereço não disponível"

    sistema = (
        "Você é o analista de Produtos da Área Incrível, empresa que constrói "
        "BOLHAS INCRÍVEIS (contextos completos de moradia acessível) sob o Plano "
        "Incrível. Você substitui a equipe que busca terrenos e estuda qual bolha "
        "desenvolver.\n\n"
        "O QUE A ÁREA INCRÍVEL CONSTRÓI — REGRA ABSOLUTA: moradia 100% HORIZONTAL — "
        "condomínios fechados de CASAS (térreas ou sobrados), casas modulares que "
        "ampliam, e LOTES/loteamentos. NUNCA, em hipótese alguma, recomende prédios, "
        "torres, edifícios, apartamentos, pavimentos ou qualquer tipologia VERTICAL. "
        "A 'tipologia' que você propor é sempre horizontal: ex. 'casas térreas "
        "geminadas de 2 dormitórios', 'sobrados de 3 dormitórios', 'lotes de 200 m² + "
        "casa modular'. Empreendimentos reais da empresa: Residencial Siena, Ravena, "
        "Di Napoli (casas e lotes em condomínio). Diferenciais: portaria e segurança "
        "24h, estética contemporânea, casa modular ampliável, áreas comuns simples "
        "(piscina, quadra, playground, salão).\n\n"
        "Regras inegociáveis do plano: (1) o produto começa no "
        "CONTEXTO, não na planta; (2) toda promessa precisa caber na conta do "
        "Minha Casa, Minha Vida; (3) toda complexidade precisa pagar aluguel — só "
        "entra se aumenta valor percebido, reduz custo, reduz risco ou acelera "
        "venda; (4) dignidade não é luxo. Faixas MCMV 2026: F1 renda≤3.200; F2≤5.000; "
        "F3≤9.600 (teto R$400k); F4≤13.000 (teto R$600k).\n\n"
        "PRATELEIRA DE BOLHAS disponível (escolha exatamente uma chave existente):\n"
        + _prateleira_resumo()
        + "\n\nResponda SOMENTE com um objeto JSON (sem texto fora dele), no formato:\n"
        '{"bolha_key": "<chave da prateleira>", "bolha_nome": "", "linha": "", '
        '"score_aplicabilidade": <0-100 int>, "faixa_mcmv": <1-4 int>, '
        '"publico_alvo": "", "promessa_central": "", "narrativa": "", "tipologia": "", '
        '"modulos_sugeridos": ["", ""], '
        '"programas": {"area_segura": {"incluir": true, "motivo": ""}, '
        '"arte_incrivel": {"incluir": false, "motivo": ""}}, '
        '"riscos": ["", ""], '
        '"checklist": {"contexto": "", "conta_fecha": "", "cliente_entende": "", '
        '"obra_executa": "", "repetivel": ""}, '
        '"justificativa": "amarre cada ponto às variáveis medidas do terreno", '
        '"proximos_passos": ["", ""], '
        '"alternativas": [{"bolha_nome": "", "score": <0-100>, "porque": ""}]}'
    )

    flags = lote.get("flags") or "nenhuma"
    user = (
        f"TERRENO #{lote.get('id')} — {addr}.\n"
        f"Variáveis medidas:\n"
        f"- Área: {metrics['area_m2']:.0f} m²\n"
        f"- Declividade: {metrics.get('slope_pct') if metrics.get('slope_pct') is not None else 's/ dado'}%\n"
        f"- Testada (frente p/ via): {metrics.get('frontage_m') if metrics.get('frontage_m') is not None else 's/ dado'} m\n"
        f"- Compacidade do formato (0-1): {metrics.get('compactness') if metrics.get('compactness') is not None else 's/ dado'}\n"
        f"- Infraestrutura do entorno (0-1): {metrics.get('infra') if metrics.get('infra') is not None else 's/ dado'}\n"
        f"- Qualidade de acesso (0-1): {metrics.get('access') if metrics.get('access') is not None else 's/ dado'}\n"
        f"- Score técnico de viabilidade (0-100): {metrics.get('viab_score')}\n"
        f"- Zoneamento: {metrics.get('zoning')}\n"
        f"- Alertas: {flags}\n\n"
        f"Pré-ranking determinístico (aderência por bolha): "
        + "; ".join(f"{r['nome']}={r['score']}" for r in ranking[:4]) + ".\n"
        f"Faixa MCMV sugerida pelo entorno: F{faixa_sugerida}.\n"
    )
    if target_faixa:
        user += (f"\nRESTRIÇÃO DO USUÁRIO: o produto DEVE ser da Faixa F{target_faixa} "
                 f"({MCMV_FAIXAS_2026[target_faixa]['label']}). Respeite essa faixa.")
    user += ("\nDecida a melhor bolha, pontue a aplicabilidade e preencha a caixa de "
             "produto. Use o pré-ranking como apoio, mas decida pelo contexto.")
    return [{"role": "system", "content": sistema}, {"role": "user", "content": user}]


def _valida_bolha_key(key: str | None, nome: str | None) -> str:
    if key and key in BOLHAS:
        return key
    if nome:  # tenta casar pelo nome
        for k, b in BOLHAS.items():
            if b["nome"].lower() == str(nome).strip().lower():
                return k
    return ""


def _estudo_heuristico(metrics: dict, endereco: dict, lote: dict,
                       ranking: list[dict], faixa: int, units: int | None,
                       motivo: str) -> dict:
    best = ranking[0]
    b = BOLHAS[best["key"]]
    return {
        "modo": "heuristico",
        "modelo": None,
        "aviso_ia": f"IA indisponível ({motivo}). Recomendação por regras determinísticas.",
        "bolha_key": best["key"], "bolha_nome": b["nome"], "linha": b["linha"],
        "score_aplicabilidade": best["score"],
        "faixa_mcmv": faixa,
        "publico_alvo": b["publico"],
        "promessa_central": b["promessa"],
        "narrativa": b["tese"],
        "tipologia": "",
        "modulos_sugeridos": list(b["modulos"]),
        "programas": {
            p: {"incluir": p in b["programas"],
                "motivo": PROGRAMAS[p]["desc"] if p in b["programas"] else "Não prioritário aqui."}
            for p in PROGRAMAS
        },
        "riscos": [b["cuidados"]],
        "checklist": {},
        "justificativa": (
            f"Melhor aderência determinística ({best['score']}/100) considerando "
            f"área {metrics['area_m2']:.0f} m², declividade e urbanização do entorno."),
        "proximos_passos": ["Validar contexto em campo", "Rodar Estudo de Implantação",
                            "Levar à reunião de comitê de produto"],
        "alternativas": [{"bolha_nome": r["nome"], "score": r["score"],
                          "porque": "Aderência determinística próxima."}
                         for r in ranking[1:3]],
    }


def analisar(lote: dict, endereco: dict | None = None,
             target_faixa: int | None = None,
             layout_stats: dict | None = None,
             progress=None) -> dict:
    """Estudo de viabilidade de bolha para um lote. Núcleo do Motor de Bolhas.

    `lote`: propriedades da feature do lote (id, area_m2, slope_pct, frontage_m,
            compactness, score, score_breakdown, zoning, flags, lat, lon).
    `endereco`: dict de registry.lookup_point(...)['endereco'] (opcional).
    `target_faixa`: override do usuário (1..4) — restringe a faixa do produto.
    `layout_stats`: stats do Estudo de Implantação salvo (units), se houver.
    """
    progress = progress or (lambda *a, **k: None)
    endereco = endereco or {}

    progress("Lendo contexto do terreno", 10)
    metrics = metrics_from_props(lote)
    faixa_sugerida = target_faixa or infer_faixa(metrics)
    ranking = rank_bolhas(metrics, faixa_sugerida)  # ranking ciente da faixa
    units = (layout_stats or {}).get("units")

    estudo: dict
    if ai.is_configured():
        progress("Consultando IA (contexto → bolha)", 35)
        msgs = _build_messages(metrics, endereco, lote, ranking, faixa_sugerida, target_faixa)
        try:
            # max_tokens alto: alguns modelos free "raciocinam" antes do JSON.
            # validate rejeita modelo que não devolve JSON → tenta o próximo.
            res = ai.chat(msgs, json_mode=True, max_tokens=5000, temperature=0.3,
                          validate=ai.extract_json)
            progress("Montando estudo", 80)
            data = ai.extract_json(res["content"])
            key = _valida_bolha_key(data.get("bolha_key"), data.get("bolha_nome"))
            if not key:
                key = ranking[0]["key"]
            b = BOLHAS[key]
            score_ia = data.get("score_aplicabilidade")
            try:
                score_ia = max(0, min(100, int(round(float(score_ia)))))
            except (TypeError, ValueError):
                score_ia = ranking[0]["score"]
            faixa_ia = faixa_sugerida  # robusto a "F3"/"3"/3
            mm = re.search(r"[1-4]", str(data.get("faixa_mcmv", "")))
            if mm:
                faixa_ia = int(mm.group())
            estudo = {
                "modo": "ia",
                "modelo": res["model"],
                "bolha_key": key,
                "bolha_nome": b["nome"],
                "linha": b["linha"],
                "score_aplicabilidade": score_ia,
                "faixa_mcmv": faixa_ia,
                "publico_alvo": data.get("publico_alvo") or b["publico"],
                "promessa_central": data.get("promessa_central") or b["promessa"],
                "narrativa": data.get("narrativa") or b["tese"],
                "tipologia": data.get("tipologia") or "",
                "modulos_sugeridos": data.get("modulos_sugeridos") or list(b["modulos"]),
                "programas": data.get("programas") or {},
                "riscos": data.get("riscos") or [b["cuidados"]],
                "checklist": data.get("checklist") or {},
                "justificativa": data.get("justificativa") or "",
                "proximos_passos": data.get("proximos_passos") or [],
                "alternativas": data.get("alternativas") or [],
            }
        except ai.AIUnavailable as e:
            estudo = _estudo_heuristico(metrics, endereco, lote, ranking,
                                        faixa_sugerida, units, str(e))
        except Exception as e:  # JSON inválido / formato inesperado
            estudo = _estudo_heuristico(metrics, endereco, lote, ranking,
                                        faixa_sugerida, units, f"resposta inválida: {e}")
    else:
        estudo = _estudo_heuristico(metrics, endereco, lote, ranking,
                                    faixa_sugerida, units, "OpenRouter não configurado")

    # Anexos comuns (IA ou heurístico)
    faixa_final = int(estudo.get("faixa_mcmv") or faixa_sugerida)
    estudo["faixa_label"] = MCMV_FAIXAS_2026.get(faixa_final, {}).get("label", "")
    estudo["viabilidade"] = viabilidade_economica(faixa_final, units, metrics["area_m2"])
    estudo["fit_deterministico"] = ranking[:4]
    estudo["aviso"] = AVISO_METODO
    estudo["lote"] = {
        "id": lote.get("id"), "area_m2": metrics["area_m2"],
        "slope_pct": metrics.get("slope_pct"), "frontage_m": metrics.get("frontage_m"),
        "zoning": metrics.get("zoning"), "lat": lote.get("lat"), "lon": lote.get("lon"),
        "viab_score": metrics.get("viab_score"),
    }
    endr = ", ".join(str(x) for x in (
        endereco.get("logradouro"), endereco.get("bairro"),
        endereco.get("cidade"), endereco.get("uf")) if x)
    estudo["endereco"] = endr

    # Sinaliza divergência grande entre IA e o melhor determinístico (transparência)
    det_best = ranking[0]
    if estudo["modo"] == "ia" and estudo["bolha_key"] != det_best["key"] \
            and abs(estudo["score_aplicabilidade"] - det_best["score"]) >= 25:
        estudo["divergencia"] = (
            f"IA escolheu {estudo['bolha_nome']}; o ranking determinístico preferia "
            f"{det_best['nome']} ({det_best['score']}/100). Revise no comitê.")

    progress("Concluído", 99)
    return estudo
