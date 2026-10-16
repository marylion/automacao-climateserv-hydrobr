"""Plot isolado da precipitação de uma estação, com estilos configuráveis.

Uso típico no Jupyter:

    import station_plots as sp

    sp.plot_station("belem", years=2025)
    sp.plot_station(
        "belem",
        years=[2023, 2024, 2025],
        granularity=sp.Granularity.MONTHLY,
        layout=sp.Layout.OVERLAY,
        style=sp.PlotStyle(kind=sp.ChartKind.LINE),
    )
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import unicodedata
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from main import SERIES_DIR, load_station_series, logger

type Panel = list[tuple[str | None, pd.Series]]


# ============================================================
# 1. ENUMS DE ESTILO E DADOS
# ============================================================

class Granularity(StrEnum):
    """Resolução temporal dos dados. O valor é a frequência do pandas."""

    DAILY = "D"
    MONTHLY = "MS"
    YEARLY = "YS"


class Layout(StrEnum):
    """Como os anos selecionados são dispostos no gráfico."""

    TIMELINE = "timeline"
    OVERLAY = "overlay"
    STACKED = "stacked"


class ChartKind(StrEnum):
    """Tipos de representação gráfica."""

    BAR = "bar"
    LINE = "line"
    FILL = "fill"
    AREA = "area"


class TickUnit(StrEnum):
    """Unidade dos marcadores do eixo X."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class Theme(StrEnum):
    """Folha de estilo do matplotlib aplicada à figura."""

    CLEAN = "seaborn-v0_8-whitegrid"
    CLASSIC = "default"
    GGPLOT = "ggplot"
    BMH = "bmh"
    DARK = "dark_background"


class Palette(StrEnum):
    """Cor da série quando há apenas uma (layout TIMELINE)."""

    BLUE = "#1f77b4"
    TEAL = "#008080"
    GREEN = "#2ca02c"
    ORANGE = "#ff7f0e"
    PURPLE = "#7b4ea3"
    GRAY = "#6c757d"


@dataclass(frozen=True, slots=True)
class PlotStyle:
    """Parâmetros visuais do gráfico.

    Use `dataclasses.replace(style, ...)` para derivar variações.

    Attributes:
        kind: Tipo de desenho (barras, linha ou linha preenchida).
        theme: Folha de estilo do matplotlib.
        palette: Cor da série única (layout TIMELINE).
        multi_cmap: Colormap qualitativo usado com vários anos
            (OVERLAY e STACKED), por exemplo "tab10", "Set2", "Dark2".
        tick_unit: Unidade dos marcadores do eixo X.
        tick_step: Intervalo entre marcadores, em `tick_unit`.
        tick_format: Formato strftime dos rótulos; None usa o padrão da unidade.
        label_rotation: Rotação dos rótulos do eixo X, em graus.
        figsize: (largura, altura) por painel. No layout STACKED a altura
            total é multiplicada pelo número de anos.
        dpi: Resolução da figura e do arquivo salvo.
        line_width: Espessura da linha (LINE e AREA).
        fill_alpha: Transparência do preenchimento (AREA).
        bar_alpha: Transparência das barras (BAR).
        grid: Exibe a grade horizontal.
        share_y: Compartilha o eixo Y entre painéis (STACKED).
    """

    kind: ChartKind = ChartKind.AREA
    theme: Theme = Theme.CLEAN
    palette: Palette = Palette.BLUE
    multi_cmap: str = "tab10"
    tick_unit: TickUnit = TickUnit.MONTH
    tick_step: int = 1
    tick_format: str | None = None
    label_rotation: int = 45
    figsize: tuple[float, float] = (14, 5)
    dpi: int = 100
    line_width: float = 1.2
    fill_alpha: float = 0.35
    bar_alpha: float = 0.85
    grid: bool = True
    share_y: bool = True


# ============================================================
# 2. CONSTANTES
# ============================================================

COMMON_YEAR: Final[int] = 2000

TIMELINE_TICK_FORMATS: Final[dict[TickUnit, str]] = {TickUnit.DAY: "%d/%m", TickUnit.WEEK: "%d/%m", TickUnit.MONTH: "%b/%y", TickUnit.YEAR: "%Y", }

SEASONAL_TICK_FORMATS: Final[dict[TickUnit, str]] = {TickUnit.DAY: "%d/%m", TickUnit.WEEK: "%d/%m", TickUnit.MONTH: "%b", TickUnit.YEAR: "%Y", }

BAR_WIDTH_DAYS: Final[dict[Granularity, float]] = {Granularity.DAILY: 1.0, Granularity.MONTHLY: 25.0, Granularity.YEARLY: 330.0, }

Y_LABELS: Final[dict[Granularity, str]] = {Granularity.DAILY: "Precipitação diária (mm)", Granularity.MONTHLY: "Precipitação mensal acumulada (mm)", Granularity.YEARLY: "Precipitação anual acumulada (mm)", }

GRANULARITY_TITLES: Final[dict[Granularity, str]] = {Granularity.DAILY: "diária", Granularity.MONTHLY: "mensal", Granularity.YEARLY: "anual", }
BAR_WIDTH: Final[float] = 0.8


# ============================================================
# 3. LOCALIZAÇÃO DA ESTAÇÃO
# ============================================================

def _normalize(text: str) -> str:
    """Remove acentos e padroniza caixa para comparação de textos."""
    decomposed = unicodedata.normalize("NFKD", text)

    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def list_station_csvs() -> list[Path]:
    """Lista os CSVs de estações disponíveis em `SERIES_DIR`."""
    return sorted(SERIES_DIR.glob("*.csv"))


def find_station_csv(station: str | int | Path) -> Path:
    """Resolve uma estação para o caminho do CSV.

    Args:
        station: Caminho do CSV, ID da estação (int) ou trecho do nome do
            arquivo (texto, sem distinção de acentos e caixa).

    Raises:
        FileNotFoundError: Se nenhuma estação corresponder.
        ValueError: Se mais de uma estação corresponder ao texto informado.
    """
    if isinstance(station, Path):
        if not station.is_file():
            raise FileNotFoundError(f"CSV não encontrado: {station}")
        return station

    candidates = list_station_csvs()

    if isinstance(station, int):
        matches = [path for path in candidates if path.stem.split("_", 1)[0] == str(station)]
    else:
        exact = [path for path in candidates if path.stem == station]

        if exact:
            return exact[0]

        query = _normalize(station)
        matches = [path for path in candidates if query in _normalize(path.stem)]

    if not matches:
        raise FileNotFoundError(f"Nenhuma estação corresponde a {station!r} em {SERIES_DIR}.")

    if len(matches) > 1:
        raise ValueError(f"Mais de uma estação corresponde a {station!r}: "
                         f"{[path.stem for path in matches]}")

    return matches[0]


# ============================================================
# 4. PREPARAÇÃO DOS DADOS
# ============================================================

def _select_period(dataframe: pd.DataFrame, years: int | Sequence[int] | None, months: Sequence[int] | None, ) -> tuple[pd.Series, list[int]]:
    """Filtra a série pelos anos e meses solicitados.

    Raises:
        ValueError: Se algum mês for inválido ou não restarem dados.
    """
    series = dataframe.set_index("data")["chuva"].astype(float)

    available = sorted(series.index.year.unique().tolist())

    if years is None:
        requested = available
    elif isinstance(years, int):
        requested = [years]
    else:
        requested = sorted(set(years))

    missing = [year for year in requested if year not in available]

    if missing:
        logger.warning(f"Anos sem dados nesta estação, ignorados: {missing}")

    selected = [year for year in requested if year in available]

    if not selected:
        raise ValueError(f"Nenhum dos anos solicitados possui dados. Disponíveis: {available}")

    mask = series.index.year.isin(selected)

    if months is not None:
        invalid = [month for month in months if not 1 <= month <= 12]

        if invalid:
            raise ValueError(f"Meses inválidos: {invalid}")

        mask &= series.index.month.isin(months)

    series = series.loc[mask]

    if series.empty:
        raise ValueError("Nenhum dado após aplicar os filtros de ano e mês.")

    return series, selected


def _aggregate(series: pd.Series, granularity: Granularity) -> pd.Series:
    """Agrega a série diária (soma em mm) para a granularidade pedida."""
    if granularity is Granularity.DAILY:
        return series

    return series.resample(granularity.value).sum(min_count=1)


def _to_common_year(series: pd.Series) -> pd.Series:
    """Move as datas para um ano comum, permitindo sobrepor anos distintos."""
    shifted = series.copy()
    shifted.index = pd.DatetimeIndex(series.index.map(lambda stamp: stamp.replace(year=COMMON_YEAR)))

    return shifted


def _build_panels(series: pd.Series, years: list[int], granularity: Granularity, layout: Layout, ) -> list[Panel]:
    """Organiza as séries em painéis conforme o layout."""
    if layout is Layout.TIMELINE:
        full_range = pd.date_range(series.index.min(), series.index.max(), freq=granularity.value, )
        return [[(None, series.reindex(full_range))]]

    by_year: Panel = [(str(year), _to_common_year(series.loc[series.index.year == year])) for year in years]

    if layout is Layout.OVERLAY:
        return [by_year]

    return [[item] for item in by_year]


# ============================================================
# 5. DESENHO
# ============================================================

def _draw_series(axis: Axes, series: pd.Series, style: PlotStyle, granularity: Granularity, color: str, label: str | None, ) -> None:
    """Desenha uma série no eixo conforme o tipo de gráfico."""
    values = series.to_numpy()

    match style.kind:
        case ChartKind.BAR:
            axis.bar(series.index, series.values, width=BAR_WIDTH, alpha=style.bar_alpha, label=label, color=color, )
        case ChartKind.LINE:
            axis.plot(series.index, series.values, linewidth=style.line_width, label=label, color=color, )
        case ChartKind.FILL:
            axis.fill_between(series.index, series.values, alpha=style.fill_alpha, label=label, color=color, )

        case ChartKind.AREA:
            axis.fill_between(series.index, series.values, alpha=style.fill_alpha, color=color, )
            axis.plot(series.index, series.values, linewidth=style.line_width, label=label, color=color, )


def _apply_ticks(axis: Axes, style: PlotStyle, layout: Layout) -> None:
    """Configura localizador e formato dos marcadores do eixo X."""
    unit = style.tick_unit

    if layout is not Layout.TIMELINE and unit is TickUnit.YEAR:
        logger.warning(f"TickUnit.YEAR não se aplica ao layout {layout.value}; "
                       "usando MONTH.")
        unit = TickUnit.MONTH

    match unit:
        case TickUnit.DAY:
            locator = mdates.DayLocator(interval=style.tick_step)
        case TickUnit.WEEK:
            locator = mdates.WeekdayLocator(byweekday=mdates.MO, interval=style.tick_step, )
        case TickUnit.MONTH:
            locator = mdates.MonthLocator(interval=style.tick_step)
        case TickUnit.YEAR:
            locator = mdates.YearLocator(base=style.tick_step)

    formats = (TIMELINE_TICK_FORMATS if layout is Layout.TIMELINE else SEASONAL_TICK_FORMATS)

    axis.xaxis.set_major_locator(locator)
    axis.xaxis.set_major_formatter(mdates.DateFormatter(style.tick_format or formats[unit]))


def _format_years(years: list[int]) -> str:
    """Resume os anos para o título (2025, 2023–2025 ou 2021, 2025)."""
    if len(years) == 1:
        return str(years[0])

    if years == list(range(years[0], years[-1] + 1)):
        return f"{years[0]}–{years[-1]}"

    return ", ".join(map(str, years))


def _build_title(station_label: str, granularity: Granularity, years: list[int], months: Sequence[int] | None, ) -> str:
    """Monta o título padrão do gráfico."""
    title = (f"{station_label} | Precipitação {GRANULARITY_TITLES[granularity]} "
             f"| {_format_years(years)}")

    if months is not None:
        title += f" | meses {', '.join(f'{month:02d}' for month in sorted(months))}"

    return title


# ============================================================
# 6. FUNÇÃO PRINCIPAL
# ============================================================

def plot_station(station: str | int | Path, years: int | Sequence[int] | None = None, months: Sequence[
                                                                                                  int] | None = None, granularity: Granularity = Granularity.DAILY, layout: Layout = Layout.TIMELINE, style: PlotStyle = PlotStyle(), title: str | None = None, save_to: Path | None = None, ) -> Figure:
    """Plota a precipitação de uma estação.

    No Jupyter, deixe a chamada como última linha da célula para exibir a
    figura. Fora dele, use `save_to` ou `figure.show()`.

    Args:
        station: ID, trecho do nome ou caminho do CSV da estação.
        years: Um ano, vários anos ou None para todos.
        months: Meses (1-12) a manter; None mantém todos. Com um único mês e
            `TickUnit.DAY` o eixo mostra os dias do mês.
        granularity: DAILY, MONTHLY ou YEARLY (soma em mm por período).
        layout: TIMELINE (linha do tempo contínua), OVERLAY (anos sobrepostos
            no mesmo eixo, Jan–Dez) ou STACKED (um painel por ano). YEARLY
            só admite TIMELINE.
        style: Parâmetros visuais.
        title: Título customizado; None gera um título automático.
        save_to: Caminho do PNG a salvar; None não salva.

    Raises:
        FileNotFoundError: Se a estação ou o CSV não forem encontrados.
        ValueError: Se a estação for ambígua ou não houver dados no filtro.
        OSError: Se a gravação do arquivo falhar.
    """
    csv_path = find_station_csv(station)

    dataframe = load_station_series(csv_path)

    if dataframe is None:
        raise ValueError(f"Série inválida ou vazia: {csv_path.name}")

    series, selected_years = _select_period(dataframe, years, months)
    series = _aggregate(series, granularity)

    if granularity is Granularity.YEARLY and layout is not Layout.TIMELINE:
        logger.warning(f"Layout {layout.value} não se aplica a YEARLY; usando TIMELINE.")
        layout = Layout.TIMELINE

    logger.info(f"Plotando {csv_path.stem} | anos={selected_years} | meses={months} "
                f"| {granularity.name} | {layout.name} | {style.kind.name}")
    logger.debug(f"Período: {series.index.min():%d/%m/%Y} até "
                 f"{series.index.max():%d/%m/%Y} ({len(series)} pontos)")

    panels = _build_panels(series, selected_years, granularity, layout)
    panel_count = len(panels)
    width, height = style.figsize

    cmap = plt.get_cmap(style.multi_cmap)
    year_colors = {str(year): cmap(index % cmap.N) for index, year in enumerate(selected_years)}

    all_dates = [data.index for panel in panels for _, data in panel]
    lower = min(index.min() for index in all_dates)
    upper = max(index.max() for index in all_dates)
    padding = (pd.Timedelta(days=BAR_WIDTH_DAYS[granularity] / 2) if style.kind is ChartKind.BAR else pd.Timedelta(0))

    with plt.style.context(style.theme.value):
        figure, axes = plt.subplots(panel_count, 1, figsize=(width, height * panel_count), dpi=style.dpi, sharex=panel_count > 1, sharey=style.share_y and panel_count > 1, squeeze=False, )

        try:
            for axis, panel in zip(axes[:, 0], panels):
                for label, data in panel:
                    color = (style.palette.value if label is None else year_colors[label])
                    _draw_series(axis, data, style, granularity, color, label)

                _apply_ticks(axis, style, layout)
                axis.set_xlim(lower - padding, upper + padding)
                axis.set_ylim(bottom=0)
                axis.grid(style.grid, axis="y", alpha=0.3)
                axis.set_ylabel(Y_LABELS[granularity] if panel_count == 1 else "mm")

                if panel[0][0] is not None:
                    axis.legend(loc="upper right")

            axes[-1, 0].set_xlabel("Data" if layout is Layout.TIMELINE else "Mês / dia")

            figure.suptitle(title or _build_title(csv_path.stem, granularity, selected_years, months, ))
            figure.autofmt_xdate(rotation=style.label_rotation, ha="right" if style.label_rotation else "center", )
            figure.tight_layout()

            if save_to is not None:
                try:
                    save_to.parent.mkdir(parents=True, exist_ok=True)
                    figure.savefig(save_to, dpi=style.dpi, bbox_inches="tight", )
                except OSError:
                    logger.exception(f"Falha ao salvar o gráfico: {save_to}")
                    raise

                logger.info(f"Gráfico exportado: {save_to}")

        finally:
            plt.close(figure)

    return figure
