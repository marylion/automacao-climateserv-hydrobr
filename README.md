# RESUMO: CHIRPS Pipeline — Nordeste Paraense

Baixa dados de precipitação **CHIRPS** (ClimateSERV) para a área das estações pluviométricas da **ANA** no Nordeste
Paraense e exporta séries e gráficos diários por estação.

---

## O que faz

| Etapa                  | Descrição                                                          |
|------------------------|--------------------------------------------------------------------|
|  **Estações**          | Consulta a ANA e filtra os municípios do Nordeste Paraense         |
|  **Área de interesse** | Gera o retângulo com margem a partir das estações                  |
|  **Download**          | Um ZIP CHIRPS por ano, com reaproveitamento de arquivos íntegros   |
|  **Extração**          | Descompacta os GeoTIFFs diários com validação de segurança         |
|  **Séries**            | Um CSV de precipitação diária por estação                          |
|  **Gráficos**          | Barras do período completo + linha preenchida de 2025–2026         |

---

## Instalação (Windows)

**1. Instale o [uv](https://docs.astral.sh/uv/)** no PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**2. Clone o projeto e crie o ambiente:**

```powershell
git clone <url-do-repositorio>
cd <pasta-do-projeto>
uv venv --python 3.12
.venv\Scripts\activate
```

**3. Instale as dependências:**

```powershell
uv pip install climateserv geopandas hydrobr matplotlib pandas rasterio adjustText shapely
```

> O módulo `logger_standalone` deve estar na mesma pasta do script.

---

## ▶️ Como executar

```powershell
uv run chirps_pipeline.py
```

Ou no **Jupyter**: importe o arquivo e chame `RESULTS = main()`.

---

## Configuração

Ajuste as constantes no topo de `chirps_pipeline.py`:

| Constante                             | Função                         |
|---------------------------------------|--------------------------------|
| `START_DATE` / `END_DATE`             | Período dos dados              |
| `FOCUS_START_YEAR` / `FOCUS_END_YEAR` | Anos do gráfico de linha       |
| `BOUNDING_BOX_MARGIN`                 | Margem da área de download     |
| `PROGRESS_LOG_INTERVAL`               | Frequência do log de progresso |

---

## Saídas

```text
data/
├── chirps/                        # ZIPs e GeoTIFFs
├── series_estacoes/               # CSV por estação
├── graficos_estacoes/             # Barras, período completo
└── graficos_estacoes_2025_2026/   # Linha preenchida, 2025–2026
```

---

## ⚠️ Atenção

- ZIPs já baixados são **reaproveitados**. Para atualizar um ano, apague `chirps_{ano}.zip` e a pasta `chirps_{ano}/`.
- Requer **Python 3.12+**.
