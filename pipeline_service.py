"""Serviços de integração da aplicação CHIRPS."""
from pathlib import Path
from datetime import date
from zipfile import BadZipFile, ZipFile

import pandas as pd
from matplotlib.figure import Figure

from main import (
    CHIRPS_DIR,
    END_DATE,
    START_DATE,
    STATION_METADATA_PATH,
)
from station_plots import Layout
from station_plots import PlotStyle
from station_plots import list_station_csvs
from station_plots import plot_station
from main import main as run_chirps_pipeline


ALL_MUNICIPALITIES: str = "TODOS"
EMPTY_STATION_METADATA: pd.DataFrame = pd.DataFrame(columns=["station_id", "station_name", "municipality", "filename", ])


# noinspection method-may-be-static
class PipelineService:
    """Coordena as operações entre a interface e o pipeline."""

    def __init__(self, logger):
        self.logger = logger

    def _load_station_metadata( self ) -> pd.DataFrame:
        """Carrega os metadados das estações disponíveis."""

        if not STATION_METADATA_PATH.is_file():
            # raise FileNotFoundError(f"Arquivo de metadados não encontrado: "
            #                         f"{STATION_METADATA_PATH}. "
            #                         "Execute a exportação das estações no pipeline.")
            return EMPTY_STATION_METADATA.copy()

        metadata: pd.DataFrame = pd.read_csv(STATION_METADATA_PATH, dtype={
            "station_id"  : str,
            "station_name": str,
            "municipality": str,
        }, )

        required_columns: set[str] = {"station_id", "station_name", "municipality", "filename"}

        missing_columns: set[str] = required_columns - set(metadata.columns)

        if missing_columns:
            raise ValueError("Colunas ausentes nos metadados: "
                             f"{', '.join(sorted(missing_columns))}")

        metadata = metadata.dropna(subset=["municipality"])
        metadata["municipality"] = metadata["municipality"].str.strip()
        metadata["station_name"] = metadata["station_name"].str.strip()
        metadata["station_id"] = metadata["station_id"].str.strip()

        return metadata


    def run_pipeline( self, years: list[int]) -> None:
        """Executa o pipeline CHIRPS para a interface gráfica."""
        run_chirps_pipeline(show_map=False, years=years)


    def are_chirps_downloads_complete( self ) -> bool:
        """Verifica se todos os ZIPs anuais necessários existem e são válidos."""
        for year in range(START_DATE.year, END_DATE.year + 1):
            first_day: date = max(date(year, 1, 1), START_DATE)
            last_day: date = min(date(year, 12, 31), END_DATE)

            if first_day > last_day:
                continue

            zip_path: Path = CHIRPS_DIR / f"chirps_{year}.zip"

            if not zip_path.is_file():
                return False

            try:
                with ZipFile(zip_path) as archive:
                    if archive.testzip() is not None:
                        return False
            except (BadZipFile, OSError):
                return False

        return True


    def are_station_csvs_complete( self ) -> bool:
        """Verifica se os CSVs registrados nos metadados são válidos."""
        if not STATION_METADATA_PATH.is_file():
            self.logger.warning(f"Metadados das estações não encontrados: {STATION_METADATA_PATH}")
            return False

        try:
            metadata: pd.DataFrame = self._load_station_metadata()
        except (OSError, ValueError, pd.errors.ParserError):
            self.logger.exception("Falha ao carregar os metadados das estações.")
            return False

        if metadata.empty:
            self.logger.warning("Os metadados das estações estão vazios.")
            return False

        if metadata["filename"].isna().any():
            self.logger.warning("Existem estações sem nome de arquivo nos metadados.")
            return False

        for filename in metadata["filename"]:
            csv_path: Path = STATION_METADATA_PATH.parent / filename

            if not csv_path.is_file():
                self.logger.warning(f"CSV de estação não encontrado: {csv_path}")
                return False

            if csv_path.resolve() == STATION_METADATA_PATH.resolve():
                self.logger.warning("Os metadados apontam para o próprio arquivo de metadados.")
                return False

            try:
                columns: pd.Index = pd.read_csv(csv_path, nrows=0).columns
            except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError):
                self.logger.exception(f"Falha ao ler o cabeçalho do CSV: {csv_path}")
                return False

            if not {"data", "chuva"}.issubset(columns):
                self.logger.warning(f"Colunas obrigatórias ausentes em {csv_path.name}: "
                               f"{columns.tolist()}")
                return False

            if csv_path.stat().st_size == 0:
                self.logger.warning(f"CSV vazio: {csv_path}")
                return False

        self.logger.info(f"Validação dos CSVs concluída: {len(metadata)} estações verificadas.")
        return True


    def list_available_municipalities( self ) -> list[str]:
        """Lista os municípios disponíveis e inclui a opção TODOS."""
        metadata: pd.DataFrame = self._load_station_metadata()

        municipalities: list[str] = sorted(metadata.loc[metadata["municipality"].ne(""), "municipality",].unique().tolist(), key=str.casefold, )

        return [ALL_MUNICIPALITIES, *municipalities]


    def list_available_stations( self, municipality: str = ALL_MUNICIPALITIES, ) -> list[str]:
        """Lista as estações com séries disponíveis no município selecionado."""
        metadata: pd.DataFrame = self._load_station_metadata()

        if municipality != ALL_MUNICIPALITIES:
            metadata = metadata.loc[metadata["municipality"].str.casefold() == municipality.strip().casefold()]

        available_csvs: set[str] = {path.stem for path in list_station_csvs()}

        metadata = metadata.copy()
        metadata["csv_stem"] = metadata["filename"].map(lambda filename: Path(filename).stem)

        metadata = metadata.loc[metadata["csv_stem"].isin(available_csvs)]

        return sorted(metadata["csv_stem"].unique().tolist(), key=str.casefold, )


    def generate_station_plot( self, station: str, years: list[int] | None = None, months: list[int] | None = None, style: PlotStyle | None = None, layout: Layout = Layout.TIMELINE, ) -> Figure:
        """Gera e retorna o gráfico da estação selecionada."""
        if not station.strip():
            raise ValueError("Selecione uma estação.")

        if months is not None and any(month not in range(1, 13) for month in months):
            raise ValueError("Os meses devem estar entre 1 e 12.")

        if years is not None and any(year < 1 for year in years):
            raise ValueError("Os anos informados são inválidos.")

        plot_style: PlotStyle = style or PlotStyle()

        return plot_station(station=station, years=years, months=months, layout=layout, style=plot_style, )
