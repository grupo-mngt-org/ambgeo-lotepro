# Lote Pro — Especificação de Requisitos (refinada)

> Refinamento técnico do `espec.md`, organizado para guiar o desenvolvimento do MVP.
> Projeto: **Lote Pro — Prospecção Inteligente de Áreas** (inspirado no know-how da AmbGEO).

## 1. Objetivo

Plataforma de inteligência geográfica para **identificar e qualificar terrenos baldios ou
subutilizados** em perímetros urbanos, cruzando dados vetoriais (zoneamento / expansão urbana)
com a área efetivamente construída, para acelerar a prospecção imobiliária.

## 2. Princípios de decisão deste MVP

- **Open-source / dados gratuitos primeiro.** Evitamos serviços pagos ou freemium.
  - Basemap de satélite: **Esri World Imagery** (gratuito, sem chave) em vez do Google Satellite (pago via Maps API).
  - Footprints de edificações: **Microsoft / Google Open Buildings** (dados abertos) ou GeoJSON enviado pelo usuário.
  - StreetView entra apenas como **link** (gratuito de linkar), não como tile pago.
- **Motor de detecção plugável.** Interface `DetectionProvider`:
  - `footprint` (default, roda 100% local, sem credenciais) — subtração de footprints.
  - `gee` (opcional) — índices espectrais NDVI/NDBI sobre Sentinel-2 via Google Earth Engine (tier de pesquisa gratuito; exige credenciais).
- **Executável agora.** O caminho default não exige nenhuma API key.

## 3. Requisitos Funcionais (RF)

### RF01 — Gestão de Áreas de Interesse (AOI)
- **Fonte de dados REAL (default):** campos de **cidade** e **endereço inicial** + **raio**.
  O sistema geocodifica (Nominatim) e baixa **edificações e malha viária reais** do
  OpenStreetMap (Overpass), montando a AOI automaticamente (quadras = AOI − vias).
- **Alternativa:** upload de vetores **Shapefile (.zip), KML ou GeoJSON**.
- Seleção de uma AOI como filtro primário do processamento.

### RF02 — Processamento e Identificação de Vazios
- **Modo `gaps` (default):** vazio = `AOI − união(footprints)`. As lacunas resultantes,
  acima da área mínima, são os lotes candidatos. Não exige cadastro de lotes.
- **Modo `parcels`:** dado um conjunto de lotes, calcular a taxa de ocupação de cada um.
- **Modo `gee` (opcional):** classificar solo exposto/vegetação x construído via NDBI/NDVI.

### RF03 — Filtros de Qualificação (regras de negócio, todos parametrizáveis)
- **Área mínima:** excluir áreas < **500 m²** (`min_area_m2`).
- **Ocupação máxima:** aceitar pequenas construções desde que área construída < **15%**
  da área total (`max_occupation_ratio`).
- **Cruzamento de zoneamento:** rotular cada área com a zona em que se encontra
  (ex.: "ZRE — Zona Residencial Especial") via *spatial join*.

### RF04 — Visualização Map-Centric
- Mapa interativo com basemap de satélite (Esri World Imagery).
- Polígonos coloridos por **potencial de aproveitamento** (faixa de ocupação/área).
- Clique no polígono exibe: **coordenadas (centroide), área total (m²), ocupação (%),
  zoneamento e link direto para o Google Street View**.

### RF05 — Exportação de Leads
- Relatório em **CSV / Excel** com lista de áreas (id, lat, lon, área m², ocupação %, zona, potencial).
- Exportação dos polígonos em **KML** para uso em campo.

## 4. Requisitos Não Funcionais (RNF)

| ID | Requisito | Como o MVP atende |
|----|-----------|-------------------|
| RNF01 | Processar cidade média (~500k hab.) em ≤ 2h | Operações vetoriais com índice espacial (STRtree do Shapely) via GeoPandas; GEE para escala maior |
| RNF02 | Falso-positivo < 10% | Filtros de área mínima + ocupação; modo `gee` agrega NDVI/NDBI; calibração via parâmetros |
| RNF03 | Acesso autenticado por login/senha; isolamento por projeto | Auth com token assinado (stdlib); dados separados por `project_id` |
| RNF04 | Imagens dos últimos 6 meses | GEE filtra coleção por data; basemap Esri sempre atual |

## 5. Stack adotada

- **Python 3.14 + FastAPI** (backend e API REST).
- **GeoPandas / Shapely / pyproj / pyogrio** (geoprocessamento e I/O vetorial — sem fiona).
- **simplekml / openpyxl** (exportação KML / Excel).
- **Frontend:** HTML + **Leaflet** + Esri World Imagery (servido como estático pela própria API).
- **Persistência:** arquivos GeoPackage/GeoJSON em `data/` (default). PostGIS é opcional/futuro.
- **GEE:** `earthengine-api` (opcional, plugável).

## 6. Fora de escopo do MVP (roadmap)

- Treinamento de modelo de visão computacional (YOLO/Mask R-CNN) para muros/lajes.
- ETL de dados de zoneamento em formatos legados (CAD/DWG).
- Processamento distribuído em nuvem e fila de jobs assíncrona.
- PostGIS/multiusuário em produção e RBAC granular.
