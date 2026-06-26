# Lote Pro — Arquitetura

## Visão geral

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (Leaflet + Esri World Imagery)  ── app/static/      │
│   upload AOI/zoneamento · roda detecção · vê polígonos · export│
└───────────────▲───────────────────────────────┬──────────────┘
                │ REST/JSON (token)              │
┌───────────────┴───────────────────────────────▼──────────────┐
│                       FastAPI  (app/main.py)                   │
│  /api/auth   /api/projects   /api/layers   /api/detect  /export│
├────────────────────────────────────────────────────────────── ┤
│  core/auth   core/store     core/io        core/geo            │
│  (token)     (projetos)     (read/write    (CRS, área,         │
│                              vetores+export) ocupação)          │
├────────────────────────────────────────────────────────────── ┤
│              providers/  (DetectionProvider)                   │
│   footprint.py  (default, local)   │   gee.py (opcional)       │
└──────────────────────────────────────────────────────────────┘
                │ persistência em arquivo
        data/projects/<id>/*.gpkg + meta.json
```

## Camadas

### `app/core/geo.py` — núcleo geoespacial
- `to_metric(gdf)` — reprojeta para UTM local (`estimate_utm_crs`) para medir em m².
- `area_m2(geom_metric)` — área em metros quadrados.
- `occupation_ratio(lot, buildings)` — razão área construída / área do lote.
- `classify_potential(ratio, area)` — faixa de potencial (alto/médio/baixo) → cor.
- `street_view_url(lat, lon)` — link gratuito do Street View.

### `app/providers/` — motor de detecção (Strategy pattern)
- `base.DetectionProvider` — contrato: `detect(aoi, buildings, params) -> GeoDataFrame` de candidatos.
- `footprint.FootprintProvider` — default; dois modos:
  - `gaps`: `AOI − união(buildings)` → polígonos vazios candidatos.
  - `parcels`: pontua lotes fornecidos pela ocupação.
- `gee.GEEProvider` — stub plugável; usa `earthengine-api` quando configurado (NDVI/NDBI Sentinel-2).
- `get_provider(name)` — fábrica.

### `app/core/osm.py` — fonte de dados REAL (OpenStreetMap)
- `suggest(query)` — **autocomplete** de endereços via Photon (Komoot); retorna label + lat/lon.
- `geocode(query)` — endereço/cidade → (lat, lon) via Nominatim (OSMnx).
- `fetch_buildings(...)` — footprints **reais** de edificações (Overpass).
- `_roads_polygon_m(...)` — malha viária real, com buffer, para recortar a AOI.
- `fetch_area(city, address, radius_m)` — pipeline: geocodifica → AOI (círculo − vias) →
  baixa edificações. Sem chave de API.

### `app/core/overture.py` — footprints de alta cobertura (opcional)
- `fetch_buildings_bbox(...)` — baixa edificações da **Overture Maps** por bbox via **DuckDB**
  (parquet público, sem chave). Cobertura muito maior que o OSM; mais lento. Escolhido pelo
  parâmetro `buildings_source="overture"` em `osm.fetch_area`.

### `app/core/report.py` — análise multi-cenário
- `build_report(results)` — a partir de UMA detecção (permissiva), deriva 3 cenários de
  prospecção (Conservador/Moderado/Amplo) + resumo (área total, por zoneamento, maiores lotes).
  Entrega "vários cenários de uma vez", sem reconfigurar e rodar de novo.

### `app/core/io.py` — I/O vetorial e exportação
- `read_vector(file)` — lê SHP(.zip)/KML/GeoJSON via **pyogrio**, normaliza para EPSG:4326.
- `to_geojson(gdf)` / `export_csv` / `export_xlsx` / `export_kml`.

### `app/core/store.py` — projetos e isolamento de dados (RNF03)
- Cada projeto = pasta em `data/projects/<project_id>/` com camadas `.gpkg` e `meta.json`.
- Camadas: `aoi`, `buildings`, `zoning`, `results`.

### `app/core/auth.py` — autenticação (RNF03)
- Token assinado HMAC (stdlib), sem dependências externas.
- Usuário/senha via variáveis de ambiente (`LOTEPRO_USER` / `LOTEPRO_PASSWORD`).

### `app/api/routes.py` — endpoints REST
| Método | Rota | Função |
|--------|------|--------|
| POST | `/api/auth/login` | login → token |
| GET | `/api/geocode/suggest?q=` | autocomplete de endereços (Photon) |
| POST | `/api/analyze` | **1 clique**: área real + detecção + relatório multi-cenário |
| GET/POST | `/api/projects` | listar / criar projeto |
| POST | `/api/projects/{id}/source/osm` | **dados reais**: cidade+endereço+raio → AOI+buildings |
| POST | `/api/projects/{id}/layers/{kind}` | upload de AOI/buildings/zoning |
| POST | `/api/projects/{id}/detect` | roda detecção e grava `results` |
| GET | `/api/projects/{id}/results` | GeoJSON dos resultados |
| GET | `/api/projects/{id}/export.{csv\|xlsx\|kml}` | exporta leads |

## Novos módulos (v0.2)

### `app/core/msbuildings.py` — edificações Microsoft (fonte DEFAULT)
Tiles por quadkey (zoom 9) do **GlobalMLBuildingFootprints**: índice CSV público
(~7 MB) → download do tile (.csv.gz de GeoJSONL) → parse via DuckDB → cache em
`data/cache/msbuildings/<quadkey>.fgb` (FlatGeobuf com índice espacial; leituras
seguintes filtram por bbox sem rede). Resolve o falso-positivo de "quadra cheia
de casas aparecendo vazia" causado pela cobertura parcial do OSM.

### `app/core/detect.py` — núcleo da detecção + filtros anti-falso-positivo
`find_gaps(blocks, buildings, params)`: por quadra (STRtree), subtrai os
footprints **dilatados** (`building_buffer_m`), aplica **abertura morfológica**
(`min_width_m` — mata vielas) e exige **frente para via** (`require_frontage` —
mata fundos de quintal). Compartilhado pelo provider `footprint` e pelo modo
cidade inteira.

### `app/core/citywide.py` — análise de CIDADE INTEIRA
Limite municipal exato (Nominatim por OSM ID) → malha viária completa
(`graph_from_polygon`) → exclusões (praças/escolas/água) → edificações (MS) →
particiona em **quadras** → `find_gaps` → `qualify` → score com contexto
pré-buscado e relevo limitado aos 150 maiores lotes (cota da API de elevação).
Municípios > 4.000 km² são recusados com orientação.

### `app/core/jobs.py` — jobs em background
Thread + dicionário de status; `POST /api/analyze/start` → `{job_id}`;
`GET /api/jobs/{id}` → `{status, stage, progress, detail, result}`. O frontend
mostra barra de progresso por estágio.

### `app/core/layout.py` — estudo de implantação (estilo TestFit)
`generate(geometry, LayoutParams)`: rotaciona o terreno para o eixo escolhido,
gera módulos viários *double-loaded* (fileira | via | fileira), corta lotes na
testada configurada, posiciona a casa com recuos e devolve lotes + casas + vias
+ verde (GeoJSON) e métricas (nº casas, casas/ha, aproveitamento). ~0,1 s por
chamada → o frontend re-gera a cada slider (`POST /api/layout/preview`).
O estudo escolhido é salvo na ficha do lote (`PATCH /lots/{id}` campo `layout`).

## Fluxo de detecção

1. Usuário cria projeto e envia AOI (e opcionalmente buildings/zoning).
2. `POST /detect` com `params` (provider, modo, `min_area_m2`, `max_occupation_ratio`).
3. Provider gera candidatos → `core/geo` mede área/ocupação em CRS métrico →
   aplica filtros → *spatial join* com zoneamento → classifica potencial.
4. Resultado salvo em `results.gpkg`; frontend renderiza e permite export.

## Pluggabilidade do GEE

`GEEProvider` segue o mesmo contrato. Para habilitar:
1. `pip install earthengine-api`
2. Definir `GEE_SERVICE_ACCOUNT` + `GEE_KEY_FILE` (ou `earthengine authenticate`).
3. `detect(provider="gee", ...)`. Sem credenciais, retorna erro 400 explicativo —
   o caminho `footprint` continua 100% funcional.

## Decisões e trade-offs

- **Arquivo vs PostGIS:** arquivo simplifica o MVP e roda sem infra. PostGIS entra quando houver
  concorrência/escala (no Render, usar **Supabase client**, pois a porta 5432 é bloqueada).
- **Determinístico vs espectral:** footprint dá resultado reprodutível sem custo; GEE agrega
  acurácia onde houver footprints faltando.
- **Sem fila assíncrona:** detecção é síncrona no MVP; jobs em background ficam no roadmap.
