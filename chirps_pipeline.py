# ============================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÕES
# ============================================================
import re
from datetime import date, datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Final, TypedDict
from zipfile import BadZipFile, ZipFile

import climateserv.api
import geopandas as gpd
import hydrobr
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import rasterio
from adjustText import adjust_text
from logger_standalone import build_logger
from rasterio.errors import RasterioIOError
from rasterio.plot import show
from shapely.geometry import box

type Coordinates = list[list[float]]


# ------------------------------------------------------------
# 1.1. Tipos enumerados e estruturas de dados
# ------------------------------------------------------------

class ClimateDataset(IntEnum):
    """Datasets identificados pela API ClimateSERV."""

    CHIRPS = 0


class ClimateOperation(StrEnum):
    """Operações utilizadas nas consultas ao ClimateSERV."""

    DOWNLOAD = "Download"


class PipelineResults(TypedDict):
    """Resultados principais retornados por `main`."""

    stations: gpd.GeoDataFrame
    stations_projected: gpd.GeoDataFrame
    area: gpd.GeoDataFrame
    zip_paths: list[Path]
    rasters: list[Path]
    latest_raster: Path
    station_csvs: list[Path]
    station_graphs: list[Path]
    station_period_graphs: list[Path]


# ------------------------------------------------------------
# 1.2. Diretórios e parâmetros
# ------------------------------------------------------------

def get_project_dir() -> Path:
    """Retorna a pasta do script ou a pasta atual no Jupyter."""
    if "__file__" in globals():
        return Path(__file__).resolve().parent

    return Path.cwd()


ROOT_DIR: Final[Path] = get_project_dir()
DATA_DIR: Final[Path] = ROOT_DIR / "data"
CHIRPS_DIR: Final[Path] = DATA_DIR / "chirps"
SERIES_DIR: Final[Path] = DATA_DIR / "series_estacoes"
GRAPHS_DIR: Final[Path] = DATA_DIR / "graficos_estacoes"
PERIOD_GRAPHS_DIR: Final[Path] = DATA_DIR / "graficos_estacoes_2025_2026"

STATE: Final[str] = "Pará"

START_DATE: Final[date] = date(2020, 1, 1)
END_DATE: Final[date] = date.today()

FOCUS_START_YEAR: Final[int] = 2025
FOCUS_END_YEAR: Final[int] = 2026

SOURCE_CRS: Final[str] = "EPSG:4674"
GEOGRAPHIC_CRS: Final[str] = "EPSG:4326"
PROJECTED_CRS: Final[str] = "EPSG:3857"

BOUNDING_BOX_MARGIN: Final[float] = 0.06
MAP_MARGIN: Final[float] = 0.10

LATITUDE_COLUMN: Final[str] = "Latitude"
LONGITUDE_COLUMN: Final[str] = "Longitude"
COORDINATE_COLUMNS: Final[list[str]] = [LATITUDE_COLUMN, LONGITUDE_COLUMN]
DATE_COLUMNS: Final[list[str]] = ["StartDate", "EndDate"]
CITY_COLUMN: Final[str] = "City"
NAME_COLUMN: Final[str] = "Name"
RESPONSIBLE_COLUMN: Final[str] = "Responsible"

DATASET_TYPE: Final[ClimateDataset] = ClimateDataset.CHIRPS
OPERATION_TYPE: Final[str] = ClimateOperation.DOWNLOAD.value

LOG_SEPARATOR: Final[str] = "=" * 65
PROGRESS_LOG_INTERVAL: Final[int] = 250

CHIRPS_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# 1.3. Logger
# ------------------------------------------------------------

logger = build_logger(
    name="ResumoApp",
    app_log_name="ResumoApp",
)


# ------------------------------------------------------------
# 1.4. Municípios do Nordeste Paraense
# ------------------------------------------------------------

MUNICIPIOS_NORDESTE_PARAENSE: Final[frozenset[str]] = frozenset(
    municipio.strip().upper()
    for municipio in (
        "Abaetetuba",
        "Acará",
        "Augusto Corrêa",
        "Aurora do Pará",
        "Baião",
        "Bonito",
        "Bragança",
        "Cachoeira do Piriá",
        "Cametá",
        "Capanema",
        "Capitão Poço",
        "Colares",
        "Concórdia do Pará",
        "Curuçá",
        "Garrafão do Norte",
        "Igarapé-Açu",
        "Igarapé-Miri",
        "Ipixuna do Pará",
        "Irituia",
        "Limoeiro do Ajuru",
        "Mãe do Rio",
        "Magalhães Barata",
        "Maracanã",
        "Marapanim",
        "Mocajuba",
        "Moju",
        "Nova Esperança do Piriá",
        "Nova Timboteua",
        "Oeiras do Pará",
        "Ourém",
        "Peixe-Boi",
        "Primavera",
        "Quatipuru",
        "Salinópolis",
        "Santa Luzia do Pará",
        "Santa Maria do Pará",
        "Santarém Novo",
        "São Caetano de Odivelas",
        "São Domingos do Capim",
        "São Francisco do Pará",
        "São João da Ponta",
        "São João de Pirabas",
        "São Miguel do Guamá",
        "Tailândia",
        "Terra Alta",
        "Tomé-Açu",
        "Tracuateua",
        "Vigia",
        "Viseu",
    )
)


# ============================================================
# 2. OBTENÇÃO E TRATAMENTO DAS ESTAÇÕES DA ANA
# ============================================================

def load_precipitation_stations() -> gpd.GeoDataFrame:
    """Consulta a ANA e retorna as estações dos municípios selecionados.

    Raises:
        KeyError: Se a resposta da ANA não contiver as colunas esperadas.
        ValueError: Se nenhuma estação válida for encontrada.
    """
    logger.info(f"Consultando estações pluviométricas da ANA em {STATE}.")

    try:
        stations = hydrobr.get_data.ANA.list_prec_stations(
            state=STATE.upper()
        )
    except Exception:
        logger.exception("Falha ao consultar as estações na ANA.")
        raise

    logger.info(f"Estações recebidas da ANA: {len(stations)}")
    logger.debug(f"Colunas recebidas: {stations.columns.tolist()}")

    required_columns = {
        *COORDINATE_COLUMNS,
        *DATE_COLUMNS,
        CITY_COLUMN,
        NAME_COLUMN,
    }
    missing_columns = required_columns.difference(stations.columns)

    if missing_columns:
        raise KeyError(
            "Colunas necessárias ausentes na resposta da ANA: "
            f"{sorted(missing_columns)}"
        )

    stations = stations.copy()

    stations[COORDINATE_COLUMNS] = stations[COORDINATE_COLUMNS].apply(
        pd.to_numeric,
        errors="coerce",
    )
    stations[DATE_COLUMNS] = stations[DATE_COLUMNS].apply(
        pd.to_datetime,
        errors="coerce",
    )

    normalized_cities = (
        stations[CITY_COLUMN].astype("string").str.strip().str.upper()
    )

    municipality_mask = normalized_cities.isin(MUNICIPIOS_NORDESTE_PARAENSE)
    coordinate_mask = stations[COORDINATE_COLUMNS].notna().all(axis=1)

    logger.debug(
        f"Estações nos municípios de interesse: {int(municipality_mask.sum())}"
    )
    logger.debug(
        f"Estações com coordenadas válidas: {int(coordinate_mask.sum())}"
    )

    stations = stations.loc[municipality_mask & coordinate_mask].copy()

    if stations.empty:
        raise ValueError(
            "Nenhuma estação com coordenadas válidas foi encontrada "
            "nos municípios selecionados."
        )

    found_cities = set(normalized_cities.loc[stations.index].dropna())
    missing_cities = MUNICIPIOS_NORDESTE_PARAENSE - found_cities

    logger.info(f"Estações selecionadas: {len(stations)}")
    logger.info(
        f"Municípios com estações: {len(found_cities)} de "
        f"{len(MUNICIPIOS_NORDESTE_PARAENSE)}"
    )
    logger.debug(f"Municípios sem estações: {sorted(missing_cities)}")

    stations_gdf = gpd.GeoDataFrame(
        stations,
        geometry=gpd.points_from_xy(
            stations[LONGITUDE_COLUMN],
            stations[LATITUDE_COLUMN],
        ),
        crs=SOURCE_CRS,
    )

    logger.debug(f"CRS das estações: {stations_gdf.crs}")
    logger.debug(f"Extensão geográfica: {stations_gdf.total_bounds.tolist()}")

    return stations_gdf


# ============================================================
# 3. CONVERSÃO PARA O SISTEMA DE COORDENADAS PROJETADAS
# ============================================================

def project_stations(stations: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Projeta as estações para o CRS utilizado no cálculo da margem."""
    logger.info(f"Projetando estações para {PROJECTED_CRS}.")

    stations_projected = stations.to_crs(PROJECTED_CRS)

    logger.debug(
        f"Extensão projetada: {stations_projected.total_bounds.tolist()}"
    )

    return stations_projected


# ============================================================
# 4. CONSTRUÇÃO DA ÁREA DE INTERESSE
# ============================================================

def build_area_of_interest(
    stations_projected: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, Coordinates]:
    """Cria o retângulo de interesse e suas coordenadas (lon, lat) para a API.

    Raises:
        ValueError: Se a extensão espacial das estações for degenerada.
    """
    logger.info("Construindo a área de interesse.")

    min_x, min_y, max_x, max_y = stations_projected.total_bounds

    width = max_x - min_x
    height = max_y - min_y

    if width <= 0 or height <= 0:
        raise ValueError(
            f"Extensão espacial inválida: largura={width}, altura={height}."
        )

    margin_x = width * BOUNDING_BOX_MARGIN
    margin_y = height * BOUNDING_BOX_MARGIN

    logger.debug(
        f"Margem horizontal: {margin_x:.2f} unidades "
        f"({BOUNDING_BOX_MARGIN:.1%})"
    )
    logger.debug(
        f"Margem vertical: {margin_y:.2f} unidades "
        f"({BOUNDING_BOX_MARGIN:.1%})"
    )

    area = gpd.GeoDataFrame(
        geometry=[
            box(
                min_x - margin_x,
                min_y - margin_y,
                max_x + margin_x,
                max_y + margin_y,
            )
        ],
        crs=PROJECTED_CRS,
    )

    polygon = area.to_crs(GEOGRAPHIC_CRS).geometry.iloc[0]

    geometry_coords: Coordinates = [
        [float(longitude), float(latitude)]
        for longitude, latitude in polygon.exterior.coords
    ]

    logger.info(f"Polígono criado com {len(geometry_coords) - 1} lados.")
    logger.debug(f"Coordenadas enviadas à API: {geometry_coords}")

    return area, geometry_coords


# ============================================================
# 5. DOWNLOAD ANUAL DOS DADOS CHIRPS
# ============================================================

def is_valid_zip(zip_path: Path) -> bool:
    """Verifica a integridade estrutural de um arquivo ZIP."""
    if not zip_path.is_file():
        return False

    try:
        with ZipFile(zip_path, "r") as archive:
            return archive.testzip() is None

    except (BadZipFile, OSError) as error:
        logger.debug(f"Falha na validação de {zip_path.name}: {error}")
        return False


def download_chirps_year(year: int, geometry_coords: Coordinates) -> Path:
    """Solicita e valida o ZIP CHIRPS de um ano.

    Reutiliza o arquivo existente quando íntegro e remove-o quando corrompido.

    Raises:
        ValueError: Se o intervalo do ano estiver fora do período configurado.
        FileNotFoundError: Se a API não gerar o arquivo esperado.
        BadZipFile: Se o arquivo retornado pela API não for um ZIP íntegro.
    """
    first_day = max(date(year, 1, 1), START_DATE)
    last_day = min(date(year, 12, 31), END_DATE)

    if first_day > last_day:
        raise ValueError(
            f"Intervalo anual inválido: {first_day} até {last_day}."
        )

    output_file = CHIRPS_DIR / f"chirps_{year}.zip"

    if is_valid_zip(output_file):
        logger.info(f"ZIP anual existente e válido: {output_file.name}")
        return output_file

    if output_file.exists():
        logger.warning(f"Removendo ZIP anual inválido: {output_file.name}")
        output_file.unlink()

    logger.info(
        f"Solicitando CHIRPS anual: "
        f"{first_day:%d/%m/%Y} até {last_day:%d/%m/%Y}"
    )
    logger.debug(f"Destino: {output_file.resolve()}")
    logger.debug(f"Dataset: {DATASET_TYPE.name} ({DATASET_TYPE.value})")
    logger.debug(f"Operação: {OPERATION_TYPE}")

    try:
        result = climateserv.api.request_data(
            DATASET_TYPE,
            OPERATION_TYPE,
            first_day.strftime("%m/%d/%Y"),
            last_day.strftime("%m/%d/%Y"),
            geometry_coords,
            "",
            "",
            str(output_file),
        )
    except Exception:
        logger.exception(f"Falha na requisição ao ClimateSERV (ano {year}).")
        raise

    logger.debug(f"Retorno da API para {output_file.name}: {result!r}")

    if not output_file.exists():
        raise FileNotFoundError(
            f"A API não criou o arquivo esperado: {output_file}. "
            f"Retorno: {result!r}"
        )

    if not is_valid_zip(output_file):
        output_file.unlink(missing_ok=True)
        raise BadZipFile(
            f"O arquivo retornado não é um ZIP íntegro: {output_file}"
        )

    logger.info(
        f"Download anual validado: {output_file.name} "
        f"({output_file.stat().st_size:,} bytes)"
    )

    return output_file


def download_all_years(geometry_coords: Coordinates) -> list[Path]:
    """Baixa ou reutiliza um ZIP para cada ano do período."""
    years = list(range(START_DATE.year, END_DATE.year + 1))

    logger.info(f"Anos no período solicitado: {len(years)}")

    zip_paths: list[Path] = []

    for index, year in enumerate(years, start=1):
        logger.info(f"Processando ano {index}/{len(years)}: {year}")
        zip_paths.append(download_chirps_year(year, geometry_coords))

    logger.info(f"ZIPs anuais disponíveis: {len(zip_paths)}")

    return zip_paths


# ============================================================
# 6. EXTRAÇÃO DOS ARQUIVOS RASTER
# ============================================================

def extract_zip(zip_path: Path) -> list[Path]:
    """Extrai um ZIP validado e retorna os GeoTIFFs encontrados.

    Raises:
        BadZipFile: Se o ZIP estiver corrompido.
        ValueError: Se o ZIP contiver caminhos que escapem do destino.
    """
    extract_dir = CHIRPS_DIR / zip_path.stem
    extract_dir.mkdir(parents=True, exist_ok=True)

    existing_rasters = sorted(extract_dir.rglob("*.tif"))

    if existing_rasters:
        logger.info(
            f"Rasters já extraídos em {extract_dir.name}: "
            f"{len(existing_rasters)}"
        )
        return existing_rasters

    if not is_valid_zip(zip_path):
        raise BadZipFile(
            f"Não é possível extrair um ZIP inválido: {zip_path}"
        )

    logger.info(f"Extraindo {zip_path.name}.")

    destination = extract_dir.resolve()

    with ZipFile(zip_path, "r") as archive:
        # Impede que caminhos internos escapem do diretório de extração.
        for member in archive.infolist():
            member_path = (destination / member.filename).resolve()

            if not member_path.is_relative_to(destination):
                raise ValueError(
                    f"Caminho inseguro encontrado no ZIP: {member.filename!r}"
                )

        archive.extractall(destination)

    rasters = sorted(extract_dir.rglob("*.tif"))

    logger.info(f"GeoTIFFs extraídos de {zip_path.name}: {len(rasters)}")

    if not rasters:
        logger.warning(f"Nenhum GeoTIFF encontrado em {zip_path.name}.")

    return rasters


def extract_all_rasters(zip_paths: list[Path]) -> list[Path]:
    """Extrai os ZIPs e reúne os caminhos dos GeoTIFFs."""
    rasters: list[Path] = []

    for index, zip_path in enumerate(zip_paths, start=1):
        logger.info(
            f"Extraindo arquivo {index}/{len(zip_paths)}: {zip_path.name}"
        )
        rasters.extend(extract_zip(zip_path))

    unique_rasters = sorted(set(rasters))

    logger.info(f"Total de GeoTIFFs encontrados: {len(unique_rasters)}")

    return unique_rasters


# ============================================================
# 7. LOCALIZAÇÃO DO RASTER MAIS RECENTE
# ============================================================

def get_raster_date(raster_path: Path) -> date | None:
    """Extrai uma data YYYYMMDD do nome do raster, quando disponível."""
    match = re.search(r"(?<!\d)(\d{8})(?!\d)", raster_path.stem)

    if match is None:
        return None

    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()

    except ValueError:
        logger.debug(f"Data inválida no nome do raster: {raster_path.name}")
        return None


def select_latest_raster(rasters: list[Path]) -> Path:
    """Seleciona o raster mais recente pela data contida no nome do arquivo.

    Quando nenhum nome possui data válida, usa a data de modificação.

    Raises:
        FileNotFoundError: Se a lista de rasters estiver vazia.
    """
    if not rasters:
        raise FileNotFoundError(
            f"Nenhum GeoTIFF encontrado em {CHIRPS_DIR.resolve()}."
        )

    dated_rasters = [
        (raster_date, raster_path)
        for raster_path in rasters
        if (raster_date := get_raster_date(raster_path)) is not None
    ]

    if dated_rasters:
        latest_date, latest_path = max(dated_rasters, key=lambda item: item[0])

        logger.info(
            f"Raster mais recente: {latest_path.name} "
            f"({latest_date:%d/%m/%Y})"
        )

        return latest_path

    logger.warning(
        "Nenhum nome de raster contém uma data YYYYMMDD válida. "
        "Será usado o arquivo com a modificação mais recente."
    )

    latest_path = max(rasters, key=lambda path: path.stat().st_mtime)

    logger.info(f"Raster selecionado pela modificação: {latest_path.name}")

    return latest_path


# ============================================================
# 8. VISUALIZAÇÃO DO RASTER E DAS ESTAÇÕES
# ============================================================

def plot_raster_and_stations(
    raster_path: Path,
    stations: gpd.GeoDataFrame,
    area: gpd.GeoDataFrame,
) -> None:
    """Plota o raster CHIRPS, a área de interesse e as estações.

    Raises:
        ValueError: Se o raster não possuir CRS definido.
        RasterioIOError: Se o raster não puder ser aberto.
    """
    logger.info(f"Preparando visualização de {raster_path.name}.")

    try:
        source = rasterio.open(raster_path)
    except RasterioIOError:
        logger.exception(f"Falha ao abrir o raster: {raster_path}")
        raise

    with source:
        if source.crs is None:
            raise ValueError(
                f"O raster não possui CRS definido: {raster_path}"
            )

        logger.debug(f"CRS do raster: {source.crs}")
        logger.debug(f"Dimensões: {source.width} x {source.height}")
        logger.debug(f"Resolução: {source.res}")
        logger.debug(f"Bandas: {source.count}")
        logger.debug(f"Tipos de dados: {source.dtypes}")
        logger.debug(f"Limites: {source.bounds}")

        stations_raster = stations.to_crs(source.crs)
        area_raster = area.to_crs(source.crs)

        figure, axis = plt.subplots(figsize=(12, 10))

        try:
            show(source, ax=axis, cmap="Blues")

            area_raster.boundary.plot(
                ax=axis,
                edgecolor="blue",
                linewidth=1.5,
                label="Área de interesse",
                zorder=2,
            )

            stations_raster.plot(
                ax=axis,
                color="red",
                markersize=25,
                label="Estações pluviométricas",
                zorder=3,
            )

            texts = []

            for _, row in stations_raster.iterrows():
                station_name = str(row.get(NAME_COLUMN, "Sem nome")).title()
                responsible = row.get(RESPONSIBLE_COLUMN, "Não informado")

                if pd.isna(responsible) or not str(responsible).strip():
                    responsible = "Não informado"

                texts.append(
                    axis.text(
                        row.geometry.x,
                        row.geometry.y,
                        f"[{responsible}] {station_name}",
                        fontsize=7,
                        zorder=4,
                    )
                )

            logger.debug(f"Ajustando a posição de {len(texts)} rótulos.")

            if texts:
                adjust_text(
                    texts,
                    ax=axis,
                    arrowprops={
                        "arrowstyle": "-",
                        "color": "gray",
                        "lw": 0.5,
                    },
                )

            min_x, min_y, max_x, max_y = area_raster.total_bounds

            margin_x = (max_x - min_x) * MAP_MARGIN
            margin_y = (max_y - min_y) * MAP_MARGIN

            axis.set_xlim(min_x - margin_x, max_x + margin_x)
            axis.set_ylim(min_y - margin_y, max_y + margin_y)

            axis.set_title(f"CHIRPS | {raster_path.name}")
            axis.set_xlabel(f"Coordenada X ({source.crs})")
            axis.set_ylabel(f"Coordenada Y ({source.crs})")
            axis.legend()
            axis.set_aspect("equal")

            figure.tight_layout()

            logger.info("Exibindo o mapa.")
            plt.show()

        finally:
            plt.close(figure)


# ============================================================
# 9. EXTRAÇÃO E EXPORTAÇÃO DA PRECIPITAÇÃO POR ESTAÇÃO
# ============================================================

def build_station_filename(station_id: str, station_name: str) -> str:
    """Gera um nome de arquivo CSV seguro a partir do ID e nome da estação."""
    safe_name = re.sub(r"[^\w-]+", "_", station_name).strip("_")

    return f"{station_id}_{safe_name or 'sem_nome'}.csv"


def sort_rasters_by_date(rasters: list[Path]) -> list[tuple[date, Path]]:
    """Retorna os rasters com data reconhecível em ordem cronológica."""
    dated_rasters: list[tuple[date, Path]] = []

    for raster_path in rasters:
        raster_date = get_raster_date(raster_path)

        if raster_date is None:
            logger.warning(
                f"Raster ignorado: data não identificada em {raster_path.name}"
            )
            continue

        dated_rasters.append((raster_date, raster_path))

    dated_rasters.sort(key=lambda item: item[0])

    return dated_rasters


def export_station_precipitation(
    stations: gpd.GeoDataFrame,
    rasters: list[Path],
) -> list[Path]:
    """Extrai a precipitação diária e exporta um CSV por estação.

    Rasters ilegíveis ou sem CRS são ignorados com aviso no log.

    Raises:
        ValueError: Se não houver estações ou rasters com data reconhecível.
        FileNotFoundError: Se a lista de rasters estiver vazia.
    """
    if stations.empty:
        raise ValueError("Nenhuma estação disponível para extração.")

    if not rasters:
        raise FileNotFoundError("Nenhum raster disponível para extração.")

    SERIES_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Iniciando extração da precipitação por estação.")
    logger.debug(f"Diretório de saída: {SERIES_DIR.resolve()}")

    station_records: dict[str, list[dict[str, str | float]]] = {}
    station_filenames: dict[str, str] = {}

    for station_index, station in stations.iterrows():
        station_id = str(station_index)

        station_records[station_id] = []
        station_filenames[station_id] = build_station_filename(
            station_id,
            str(station.get(NAME_COLUMN, "sem_nome")),
        )

    dated_rasters = sort_rasters_by_date(rasters)

    if not dated_rasters:
        raise ValueError(
            "Nenhum raster possui uma data YYYYMMDD reconhecível."
        )

    total_rasters = len(dated_rasters)

    for index, (raster_date, raster_path) in enumerate(
        dated_rasters, start=1
    ):
        if index % PROGRESS_LOG_INTERVAL == 0 or index == total_rasters:
            logger.info(
                f"Extraindo rasters: {index}/{total_rasters} "
                f"(último: {raster_date:%d/%m/%Y})"
            )

        try:
            raster = rasterio.open(raster_path)
        except RasterioIOError:
            logger.exception(f"Raster ilegível, ignorado: {raster_path.name}")
            continue

        with raster:
            if raster.crs is None:
                logger.warning(f"Raster sem CRS, ignorado: {raster_path.name}")
                continue

            stations_raster = stations.to_crs(raster.crs)

            coordinates = [
                (geometry.x, geometry.y)
                for geometry in stations_raster.geometry
            ]

            sampled_values = raster.sample(
                coordinates,
                indexes=1,
                masked=True,
            )

            for station_index, sampled in zip(
                stations_raster.index,
                sampled_values,
            ):
                value = sampled[0]

                precipitation = (
                    float(value) if not pd.isna(value) else float("nan")
                )

                station_records[str(station_index)].append(
                    {
                        "data": raster_date.isoformat(),
                        "chuva": precipitation,
                    }
                )

    exported_files: list[Path] = []

    for station_id, records in station_records.items():
        dataframe = (
            pd.DataFrame(records, columns=["data", "chuva"])
            .drop_duplicates(subset=["data"], keep="last")
            .sort_values("data")
        )

        output_file = SERIES_DIR / station_filenames[station_id]

        try:
            dataframe.to_csv(
                output_file,
                index=False,
                encoding="utf-8",
                na_rep="",
            )
        except OSError:
            logger.exception(f"Falha ao gravar o CSV: {output_file}")
            raise

        exported_files.append(output_file)

        logger.info(
            f"CSV exportado: {output_file.name} | {len(dataframe)} registros"
        )

    logger.info(f"Exportação concluída: {len(exported_files)} estações.")

    return exported_files


# ============================================================
# 10. GERAÇÃO E EXPORTAÇÃO DOS GRÁFICOS POR ESTAÇÃO
# ============================================================

def load_station_series(csv_path: Path) -> pd.DataFrame | None:
    """Lê o CSV de uma estação e retorna a série ordenada por data.

    Retorna None quando o arquivo for ilegível, vazio ou sem as colunas
    esperadas, registrando o motivo no log.
    """
    try:
        dataframe = pd.read_csv(csv_path, parse_dates=["data"])
    except (OSError, ValueError, pd.errors.ParserError):
        logger.exception(f"Falha ao ler o CSV, ignorado: {csv_path}")
        return None

    if dataframe.empty:
        logger.warning(f"CSV vazio, gráfico ignorado: {csv_path.name}")
        return None

    if "chuva" not in dataframe.columns:
        logger.warning(
            f"Coluna 'chuva' ausente, gráfico ignorado: {csv_path.name}"
        )
        return None

    return dataframe.sort_values("data")


def plot_station_precipitation(csv_paths: list[Path]) -> list[Path]:
    """Gera e salva um gráfico de barras da precipitação diária por estação."""
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)

    logger.debug(f"Diretório de saída: {GRAPHS_DIR.resolve()}")

    exported_images: list[Path] = []

    for index, csv_path in enumerate(csv_paths, start=1):
        logger.info(
            f"Gerando gráfico {index}/{len(csv_paths)}: {csv_path.stem}"
        )

        dataframe = load_station_series(csv_path)

        if dataframe is None:
            continue

        output_file = GRAPHS_DIR / f"{csv_path.stem}.png"

        figure, axis = plt.subplots(figsize=(14, 5))

        try:
            axis.bar(
                dataframe["data"],
                dataframe["chuva"],
                width=1.0,
                linewidth=0,
            )

            axis.set_title(f"Precipitação diária | {csv_path.stem}")
            axis.set_xlabel("Data")
            axis.set_ylabel("Precipitação (mm)")
            axis.grid(axis="y", alpha=0.3)

            figure.autofmt_xdate()
            figure.tight_layout()

            figure.savefig(output_file, dpi=200, bbox_inches="tight")

        except OSError:
            logger.exception(f"Falha ao salvar o gráfico: {output_file}")
            continue

        finally:
            plt.close(figure)

        exported_images.append(output_file)

        logger.info(f"Gráfico exportado: {output_file}")

    logger.info(f"Gráficos exportados: {len(exported_images)}")

    return exported_images


def plot_station_period_precipitation(
    csv_paths: list[Path],
    start_year: int = FOCUS_START_YEAR,
    end_year: int = FOCUS_END_YEAR,
) -> list[Path]:
    """Gera um gráfico de linha preenchida por estação para um intervalo de anos.

    O eixo X exibe um marcador por mês. Estações sem dados no intervalo são
    ignoradas com aviso no log.
    """
    PERIOD_GRAPHS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Gerando gráficos do período {start_year}-{end_year}.")
    logger.debug(f"Diretório de saída: {PERIOD_GRAPHS_DIR.resolve()}")

    exported_images: list[Path] = []

    for index, csv_path in enumerate(csv_paths, start=1):
        logger.info(
            f"Gerando gráfico {start_year}-{end_year} "
            f"{index}/{len(csv_paths)}: {csv_path.stem}"
        )

        dataframe = load_station_series(csv_path)

        if dataframe is None:
            continue

        period = dataframe.loc[
            dataframe["data"].dt.year.between(start_year, end_year)
        ]

        if period.empty:
            logger.warning(
                f"Sem dados em {start_year}-{end_year}, "
                f"gráfico ignorado: {csv_path.name}"
            )
            continue

        output_file = PERIOD_GRAPHS_DIR / f"{csv_path.stem}.png"

        figure, axis = plt.subplots(figsize=(14, 5))

        try:
            axis.fill_between(
                period["data"],
                period["chuva"],
                alpha=0.4,
            )
            axis.plot(
                period["data"],
                period["chuva"],
                linewidth=1.0,
            )

            axis.xaxis.set_major_locator(mdates.MonthLocator())
            axis.xaxis.set_major_formatter(mdates.DateFormatter("%b/%y"))
            axis.set_xlim(period["data"].min(), period["data"].max())
            axis.set_ylim(bottom=0)

            axis.set_title(
                f"Precipitação diária {start_year}-{end_year} | "
                f"{csv_path.stem}"
            )
            axis.set_xlabel("Mês")
            axis.set_ylabel("Precipitação (mm)")
            axis.grid(axis="y", alpha=0.3)

            figure.autofmt_xdate()
            figure.tight_layout()

            figure.savefig(output_file, dpi=200, bbox_inches="tight")

        except OSError:
            logger.exception(f"Falha ao salvar o gráfico: {output_file}")
            continue

        finally:
            plt.close(figure)

        exported_images.append(output_file)

        logger.info(f"Gráfico exportado: {output_file}")

    logger.info(
        f"Gráficos {start_year}-{end_year} exportados: {len(exported_images)}"
    )

    return exported_images


# ============================================================
# 11. EXECUÇÃO DO FLUXO COMPLETO
# ============================================================

def main() -> PipelineResults:
    """Executa o fluxo completo e retorna os resultados principais."""
    logger.info(LOG_SEPARATOR)
    logger.info("INÍCIO DO PROCESSAMENTO CHIRPS")
    logger.info(f"Diretório do projeto: {ROOT_DIR}")
    logger.info(f"Período: {START_DATE:%d/%m/%Y} até {END_DATE:%d/%m/%Y}")
    logger.info(f"Diretório de dados: {CHIRPS_DIR.resolve()}")
    logger.info(LOG_SEPARATOR)

    stations = load_precipitation_stations()
    stations_projected = project_stations(stations)
    area, geometry_coords = build_area_of_interest(stations_projected)

    zip_paths = download_all_years(geometry_coords)
    rasters = extract_all_rasters(zip_paths)
    latest_raster = select_latest_raster(rasters)

    plot_raster_and_stations(latest_raster, stations, area)

    station_csvs = export_station_precipitation(
        stations=stations,
        rasters=rasters,
    )
    station_graphs = plot_station_precipitation(csv_paths=station_csvs)
    station_period_graphs = plot_station_period_precipitation(
        csv_paths=station_csvs,
    )

    results: PipelineResults = {
        "stations": stations,
        "stations_projected": stations_projected,
        "area": area,
        "zip_paths": zip_paths,
        "rasters": rasters,
        "latest_raster": latest_raster,
        "station_csvs": station_csvs,
        "station_graphs": station_graphs,
        "station_period_graphs": station_period_graphs,
    }

    logger.info(LOG_SEPARATOR)
    logger.info("PROCESSAMENTO CONCLUÍDO")
    logger.info(f"Estações utilizadas: {len(stations)}")
    logger.info(f"ZIPs processados: {len(zip_paths)}")
    logger.info(f"GeoTIFFs encontrados: {len(rasters)}")
    logger.info(f"CSVs por estação: {len(station_csvs)}")
    logger.info(f"Gráficos por estação: {len(station_graphs)}")
    logger.info(
        f"Gráficos {FOCUS_START_YEAR}-{FOCUS_END_YEAR} por estação: "
        f"{len(station_period_graphs)}"
    )
    logger.info(f"Raster visualizado: {latest_raster}")
    logger.info(LOG_SEPARATOR)

    return results


if __name__ == "__main__":
    RESULTS = main()
