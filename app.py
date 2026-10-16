"""Interface gráfica do pipeline CHIRPS."""
from datetime import datetime
from pathlib import Path
from queue import Empty
from queue import Queue
from threading import Thread
from time import perf_counter
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from logger_standalone import build_logger
from pipeline_service import PipelineService
from station_plots import ChartKind
from station_plots import Layout
from station_plots import PlotStyle


SIZE_MOD: int = 1
BACKGROUND: str = "#f4f7fa"
SURFACE: str = "#ffffff"
TEXT: str = "#1d2b36"
MUTED: str = "#5d6d7a"
BORDER: str = "#d5dde4"
ACCENT: str = "#1f77b4"

WINDOW_TITLE: str = "CHIRPS - Nordeste Paraense"
WINDOW_GEOMETRY: str = "1200x820"
WINDOW_MIN_WIDTH: int = 900
WINDOW_MIN_HEIGHT: int = 650

SPACE_XS: int = 4
SPACE_SM: int = 8
SPACE_MD: int = 12
SPACE_LG: int = 20

# noinspection SpellCheckingInspection
FONT_FAMILY: str = "Segoe UI"
FONT_SIZE: int = 14
FONT_SIZE_TITLE: int = 24
FONT_SIZE_SECTION: int = 16

CONTROL_HEIGHT: int = 36
SIDEBAR_WIDTH: int = 280
GRAPH_DPI: int = 100


# noinspection method-may-be-static,unresolved-references
class ChirpsApp(ctk.CTk):
    """Janela principal para visualizar séries CHIRPS."""


    def __init__( self ) -> None:
        super().__init__()

        self._status_queue: Queue[tuple[bool | Exception, bool | Exception]] = Queue()
        self._pipeline_queue: Queue[Exception | None] = Queue()
        self._pipeline_started_at: float | None = None

        self._selected_years: list[int] = []

        # noinspection SpellCheckingInspection
        log_file_name = "AutomatacaAnalisePluviometrica"
        self.logger = build_logger(name=log_file_name, app_log_name=log_file_name)
        self.service: PipelineService = PipelineService(self.logger)
        self.canvas: FigureCanvasTkAgg | None = None
        self.current_figure: Figure | None = None
        self.station_names: list[str] = []

        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_GEOMETRY)
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.configure(fg_color=BACKGROUND)

        self._configure_theme()
        self._create_widgets()
        self._load_assets()
        self._layout_widgets()
        self._load_stations()
        self._start_data_status_check()
        self._apply_dropdown_style()


    def _configure_theme( self ) -> None:
        """Configura o tema visual."""
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")


    def _start_loading_state( self ) -> None:
        """Inicia a animação da barra e o cronômetro."""
        self._pipeline_started_at = perf_counter()

        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.progress_bar.set(0)

        self.elapsed_time_label.configure(text="Tempo decorrido: 00:00")
        self._update_elapsed_time()


    def _update_elapsed_time( self ) -> None:
        """Atualiza o cronômetro pela thread da interface."""

        if self._pipeline_started_at is None:
            return

        elapsed_seconds: int = int(perf_counter() - self._pipeline_started_at)
        minutes, seconds = divmod(elapsed_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if hours:
            elapsed_text: str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            elapsed_text = f"{minutes:02d}:{seconds:02d}"

        self.elapsed_time_label.configure(text=f"Tempo decorrido: {elapsed_text}")
        self.after(250, self._update_elapsed_time)


    def _stop_loading_state( self, success: bool ) -> None:
        """Encerra a animação e finaliza o cronômetro."""
        self._update_elapsed_time()

        self._pipeline_started_at = None
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")

        self.progress_bar.set(1 if success else 0)


    def _apply_dropdown_style( self ):
        dropdown_style = {
            "fg_color"            : ("#F9F9FA", "#343638"),
            "button_color"        : ("#3B8ED0", "#1F6AA5"),
            "button_hover_color"  : ("#36719F", "#144870"),
            "border_color"        : ("#979DA2", "#565B5E"),
            "text_color"          : ("#000000", "#DCE4EE"),
            "dropdown_fg_color"   : ("#F9F9FA", "#343638"),
            "dropdown_hover_color": ("#3B8ED0", "#1F6AA5"),
            "dropdown_text_color" : ("#000000", "#DCE4EE"),
        }

        self.state_selector.configure(**dropdown_style)
        self.station_selector.configure(**dropdown_style)

    def _create_widgets( self ) -> None:
        """Cria os componentes da interface."""

        # Cabeçalho
        self.header = ctk.CTkFrame(self, fg_color="transparent")

        # Informações do programa, alinhadas à esquerda.
        self.header_info = ctk.CTkFrame(self.header, fg_color="transparent", )
        self.title_label = ctk.CTkLabel(self.header_info, text=WINDOW_TITLE, font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold"), text_color=TEXT, )
        self.subtitle_label = ctk.CTkLabel(self.header_info, text="Análise e visualização de séries temporais de precipitação", font=(FONT_FAMILY, FONT_SIZE), text_color=MUTED, )

        # Ações e indicadores, alinhados à direita.
        self.header_actions = ctk.CTkFrame(self.header, fg_color="transparent", )

        # Indicador 1: download dos dados.
        self.download_status_frame = ctk.CTkFrame(self.header_actions, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER, )
        self.download_status_text = ctk.CTkFrame(self.download_status_frame, fg_color="transparent", )
        self.download_status_title = ctk.CTkLabel(self.download_status_text, text="Dados Baixados", font=(FONT_FAMILY, FONT_SIZE, "bold"), text_color=TEXT, )
        self.download_status_label = ctk.CTkLabel(self.download_status_text, text="Aguardando verificação", font=(FONT_FAMILY, FONT_SIZE - 2), text_color=MUTED, )

        # Indicador 2: geração dos CSVs.
        self.csv_status_frame = ctk.CTkFrame(self.header_actions, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER, )
        self.csv_status_text = ctk.CTkFrame(self.csv_status_frame, fg_color="transparent", )
        self.csv_status_title = ctk.CTkLabel(self.csv_status_text, text="CSVs Gerados", font=(FONT_FAMILY, FONT_SIZE, "bold"), text_color=TEXT, )
        self.csv_status_label = ctk.CTkLabel(self.csv_status_text, text="Aguardando verificação", font=(FONT_FAMILY, FONT_SIZE - 2), text_color=MUTED, )

        # Área de ação e progresso
        self.action_progress_frame = ctk.CTkFrame(self.header_actions, fg_color="transparent", )
        # Botão principal
        self.generate_data_button = ctk.CTkButton(self.action_progress_frame, text="Baixar e Gerar Dados", height=CONTROL_HEIGHT, font=(FONT_FAMILY, FONT_SIZE, "bold"), fg_color=ACCENT, hover_color="#185d8c", state="disabled", command=self._on_generate_data_clicked, )
        # Barra de progresso
        self.progress_bar = ctk.CTkProgressBar(self.action_progress_frame, mode="determinate", height=8, )
        self.progress_bar.set(0)
        # Tempo decorrido
        self.elapsed_time_label = ctk.CTkLabel(self.action_progress_frame, text="Tempo decorrido: 00:00", font=(FONT_FAMILY, FONT_SIZE - 3), text_color=MUTED, )

        # Área principal
        self.content = ctk.CTkFrame(self, fg_color="transparent")

        # Faixa de controles
        self.controls = ctk.CTkFrame(self.content, fg_color="transparent", corner_radius=0, border_width=0, border_color=BORDER, )

        # Frames 1, 2, 3
        self.station_controls = ctk.CTkFrame(self.controls, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER, )
        self.chart_controls = ctk.CTkFrame(self.controls, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER, )
        self.date_controls = ctk.CTkFrame(self.controls, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER, )

        self.station_controls_inner = ctk.CTkFrame(self.station_controls, fg_color="transparent", corner_radius=0, border_width=0, border_color=BORDER, )
        self.chart_controls_inner = ctk.CTkFrame(self.chart_controls, fg_color="transparent", corner_radius=0, border_width=0, border_color=BORDER, )
        self.date_controls_inner = ctk.CTkFrame(self.date_controls, fg_color="transparent", corner_radius=0, border_width=0, border_color=BORDER, )

        # Frame 1: Estado e estação
        self.state_label = ctk.CTkLabel(self.station_controls_inner, text="Município", font=(FONT_FAMILY, FONT_SIZE, "bold"), text_color=TEXT, )
        self.state_selector = ctk.CTkComboBox(self.station_controls_inner, values=[], state="readonly", height=CONTROL_HEIGHT, font=(FONT_FAMILY, FONT_SIZE), dropdown_font=(FONT_FAMILY, FONT_SIZE), command=self._on_municipality_selected, )

        self.station_label = ctk.CTkLabel(self.station_controls_inner, text="Estação", font=(FONT_FAMILY, FONT_SIZE, "bold"), text_color=TEXT, )
        self.station_selector = ctk.CTkComboBox(self.station_controls_inner, values=[], state="readonly", height=CONTROL_HEIGHT, font=(FONT_FAMILY, FONT_SIZE), dropdown_font=(FONT_FAMILY, FONT_SIZE), command=self._on_station_selected, )

        # Frame 2: Visualização e atualização
        self.chart_label = ctk.CTkLabel(self.chart_controls_inner, text="Visualização", font=(FONT_FAMILY, FONT_SIZE, "bold"), text_color=TEXT, )
        self.fill_checkbox = ctk.CTkCheckBox(self.chart_controls_inner, text="Área preenchida", font=(FONT_FAMILY, FONT_SIZE), text_color=TEXT, checkbox_width=18, checkbox_height=18, command=self._update_plot, )
        self.line_checkbox = ctk.CTkCheckBox(self.chart_controls_inner, text="Linha", font=(FONT_FAMILY, FONT_SIZE), text_color=TEXT, checkbox_width=18, checkbox_height=18, command=self._update_plot, )
        self.fill_checkbox.select()
        self.line_checkbox.select()
        self.update_button = ctk.CTkButton(self.chart_controls_inner, text="Atualizar gráfico", height=CONTROL_HEIGHT, font=(FONT_FAMILY, FONT_SIZE, "bold"), fg_color=ACCENT, hover_color="#185d8c", command=self._update_plot, )

        # Frame 3: Datas
        # Anos
        self.year_controls = ctk.CTkFrame(self.date_controls_inner, fg_color="transparent", )
        self.year_label = ctk.CTkLabel(self.year_controls, text="Anos", font=(FONT_FAMILY, FONT_SIZE, "bold"), text_color=TEXT, )
        self.year_frame = ctk.CTkFrame(self.year_controls, fg_color="transparent", )
        self.year_checkboxes: dict[int, ctk.CTkCheckBox] = {}
        self.year_rows: list[ctk.CTkFrame] = []

        current_year = datetime.now().year
        available_years = list(range(current_year, current_year - 21, -1))

        for row_start in range(0, len(available_years), 7):
            row_frame = ctk.CTkFrame(self.year_frame, fg_color="transparent", )
            self.year_rows.append(row_frame)

            for year in available_years[row_start:row_start + 7]:
                checkbox = ctk.CTkCheckBox(row_frame, text=str(year), font=(FONT_FAMILY, FONT_SIZE), text_color=TEXT, command=self._on_year_selection_changed, )
                self.year_checkboxes[year] = checkbox

        # Meses
        # self.month_controls = ctk.CTkFrame(self.date_controls_inner, fg_color="transparent", )
        # self.month_label = ctk.CTkLabel(self.month_controls, text="Meses", font=(FONT_FAMILY, FONT_SIZE, "bold"), text_color=TEXT, )
        # self.month_frame = ctk.CTkFrame(self.month_controls, fg_color="transparent", )
        # self.month_checkboxes: dict[int, ctk.CTkCheckBox] = {}
        # for month_number, month_name in enumerate(MONTHS, start=1):
        #     checkbox = ctk.CTkCheckBox(self.month_frame, text=month_name[:3], font=(FONT_FAMILY, FONT_SIZE), text_color=TEXT, command=self._update_plot, )
        #     self.month_checkboxes[month_number] = checkbox
        # Painel do gráfico
        self.graph_panel = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER, )

        self.graph_title = ctk.CTkLabel(self.graph_panel, text="Série temporal de precipitação", font=(FONT_FAMILY, FONT_SIZE_SECTION, "bold"), text_color=TEXT, )

        self.graph_container = ctk.CTkFrame(self.graph_panel, fg_color="transparent", )

        # Barra de status
        self.status_label = ctk.CTkLabel(self, text="Pronto", font=(FONT_FAMILY, FONT_SIZE - 1), text_color=MUTED, anchor="w", )


    def _layout_widgets( self ) -> None:
        """Organiza os componentes usando exclusivamente pack()."""

        # Cabeçalho: informações à esquerda e ações à direita.
        self.header.pack(side=ctk.TOP, fill="x", padx=SPACE_LG, pady=(SPACE_LG, SPACE_MD), )
        self.header_actions.pack(side=ctk.RIGHT, anchor="ne", )
        self.header_info.pack(side=ctk.LEFT, anchor="nw", )
        self.title_label.pack(side=ctk.TOP, anchor="w", )
        self.subtitle_label.pack(side=ctk.TOP, anchor="w", pady=(SPACE_XS, 0), )

        # Indicador de download.
        self.download_status_frame.pack(side=ctk.LEFT, padx=(0, SPACE_SM), pady=0, )
        self.download_status_text.pack(side=ctk.LEFT, padx=(SPACE_SM, SPACE_XS), pady=SPACE_SM * SIZE_MOD, )
        self.download_status_title.pack(side=ctk.TOP, anchor="w", )
        self.download_status_label.pack(side=ctk.TOP, anchor="w", )
        self.download_status_image.pack(side=ctk.LEFT, padx=(SPACE_XS, SPACE_SM), pady=SPACE_SM, )

        # Indicador de CSVs.
        self.csv_status_frame.pack(side=ctk.LEFT, padx=(0, SPACE_SM), pady=0, )
        self.csv_status_text.pack(side=ctk.LEFT, padx=(SPACE_SM, SPACE_XS), pady=SPACE_SM * SIZE_MOD, )
        self.csv_status_title.pack(side=ctk.TOP, anchor="w", )
        self.csv_status_label.pack(side=ctk.TOP, anchor="w", )
        self.csv_status_image.pack(side=ctk.LEFT, padx=(SPACE_XS, SPACE_SM), pady=SPACE_SM, )

        # Área de ação: botão, progresso e cronômetro.
        self.action_progress_frame.pack(side=ctk.LEFT, padx=(0, 0), pady=0, )
        self.generate_data_button.pack(side=ctk.TOP, anchor="e", fill="x", pady=(0, SPACE_SM), )
        self.progress_bar.pack(side=ctk.TOP, fill="x", )
        self.elapsed_time_label.pack(side=ctk.TOP, anchor="w", pady=(SPACE_XS, 0), )

        # Área principal
        self.content.pack(side=ctk.TOP, fill="both", expand=True, padx=SPACE_LG, pady=(0, SPACE_MD), )

        # Faixa dos controles
        self.controls.pack(side=ctk.TOP, fill="x", pady=(0, 0), padx=(0, 0))

        # Três frames principais lado a lado
        # for frame in (self.station_controls, self.chart_controls, self.date_controls,):
        #     frame.pack(side=ctk.LEFT, fill="both", expand=True, padx=SPACE_SM, pady=SPACE_SM)
        self.station_controls.pack(side=ctk.LEFT, fill="both", expand=True, padx=(0, SPACE_SM), pady=(SPACE_SM, SPACE_SM * 2))
        self.chart_controls.pack(side=ctk.LEFT, fill="both", expand=True, padx=SPACE_SM, pady=(SPACE_SM, SPACE_SM * 2))
        self.date_controls.pack(side=ctk.LEFT, fill="both", expand=True, padx=(SPACE_SM, 0), pady=(SPACE_SM, SPACE_SM * 2))

        self.station_controls_inner.pack(padx=SPACE_SM, pady=SPACE_SM, fill="x")
        self.chart_controls_inner.pack(padx=SPACE_SM, pady=SPACE_SM, fill="x")
        self.date_controls_inner.pack(padx=SPACE_SM, pady=SPACE_SM, fill="x")

        # Frame 1: Estado e estação
        self.state_label.pack(side=ctk.TOP, anchor="w", pady=(0, SPACE_XS), )
        self.state_selector.pack(side=ctk.TOP, fill="x", pady=(0, SPACE_MD), )
        self.station_label.pack(side=ctk.TOP, anchor="w", pady=(0, SPACE_XS), )
        self.station_selector.pack(side=ctk.TOP, fill="x", )

        # Frame 2: Visualização e botão
        self.chart_label.pack(side=ctk.TOP, anchor="w", pady=(0, SPACE_SM), )
        self.fill_checkbox.pack(side=ctk.TOP, anchor="w", pady=SPACE_XS, )
        self.line_checkbox.pack(side=ctk.TOP, anchor="w", pady=SPACE_XS, )
        self.update_button.pack(side=ctk.TOP, fill="x", pady=(SPACE_MD, 0), )

        # Frame 3: Anos
        self.year_controls.pack(side=ctk.TOP, fill="x", pady=(0, 0), )
        self.year_label.pack(side=ctk.TOP, anchor="w", pady=(0, SPACE_SM), )
        self.year_frame.pack(side=ctk.TOP, fill="x", )

        for row_frame in self.year_rows:
            row_frame.pack(side=ctk.TOP, fill="x", expand=True, pady=(0, 14))

            for checkbox in row_frame.winfo_children():
                checkbox.pack(side=ctk.LEFT, fill="x", expand=True)

        self.graph_panel.pack(side=ctk.TOP, fill="both", expand=True, )
        self.graph_title.pack(side=ctk.TOP, anchor="w", padx=SPACE_MD, pady=(SPACE_MD, SPACE_SM), )
        self.graph_container.pack(side=ctk.TOP, fill="both", expand=True, padx=SPACE_SM, pady=(0, SPACE_SM), )

        # Barra de status
        self.status_label.pack(side=ctk.BOTTOM, fill="x", padx=SPACE_LG, pady=(0, SPACE_SM), )


    def _run_pipeline_worker( self ) -> None:
        """Executa o pipeline e envia o resultado à interface."""
        try:
            self.service.run_pipeline(years=self._selected_years)
        except Exception as error:
            self.logger.exception("Falha durante a execução do pipeline CHIRPS.")
            self._pipeline_queue.put(error)
        else:
            self.logger.info("Pipeline CHIRPS concluído com sucesso.")
            self._pipeline_queue.put(None)


    def _poll_pipeline_queue( self ) -> None:
        """Processa o resultado do pipeline na thread gráfica."""
        try:
            error: Exception | None = self._pipeline_queue.get_nowait()
        except Empty:
            self.after(100, self._poll_pipeline_queue)
            return

        # A fila respondeu lá no get_nowait() então o pipeline terminou.
        self._stop_loading_state(success=error is None)

        self.generate_data_button.configure(state="normal", text="Baixar e Gerar Dados", )

        if error is not None:
            self.logger.error(f"Pipeline encerrado com erro: {error}")
            self._start_data_status_check()
            return

        self._load_stations()
        self._start_data_status_check()


    def _poll_data_status_queue( self ) -> None:
        """Aplica os resultados recebidos na thread da interface."""
        try:
            chirps_result, csvs_result = (self._status_queue.get_nowait())
        except Empty:
            self.after(100, self._poll_data_status_queue)
            return

        chirps_complete: bool | None = (chirps_result if isinstance(chirps_result, bool) else None)

        csvs_complete: bool | None = (csvs_result if isinstance(csvs_result, bool) else None)

        self._apply_data_status(chirps_complete=chirps_complete, csvs_complete=csvs_complete, )
        self.generate_data_button.configure(state="normal")


    def _apply_data_status( self, chirps_complete: bool | None, csvs_complete: bool | None, ) -> None:
        """Atualiza os textos e ícones dos indicadores de dados."""
        statuses: list[tuple[bool | None, ctk.CTkLabel, ctk.CTkLabel]] = [(chirps_complete, self.download_status_label, self.download_status_image,), (csvs_complete, self.csv_status_label, self.csv_status_image,), ]

        for complete, status_label, status_image in statuses:
            if complete is None:
                status_label.configure(text="Falha na verificação")
                image_name: str = "error"
            elif complete:
                status_label.configure(text="Dados disponíveis")
                image_name = "done"
            else:
                status_label.configure(text="Dados pendentes")
                image_name = "waiting"

            status_image.configure(image=self.status_images[image_name])


    def _check_data_status_worker( self ) -> None:
        """Verifica os dados sem bloquear a thread da interface."""
        try:
            chirps_result: bool | Exception = (self.service.are_chirps_downloads_complete())
        except Exception as error:
            self.logger.exception("Falha ao verificar os downloads CHIRPS.")
            chirps_result = error

        try:
            csvs_result: bool | Exception = (self.service.are_station_csvs_complete())
        except Exception as error:
            self.logger.exception("Falha ao verificar os CSVs das estações.")
            csvs_result = error

        self._status_queue.put((chirps_result, csvs_result))


    def _start_data_status_check( self ) -> None:
        """Inicia a verificação dos arquivos sem bloquear a interface."""
        self.download_status_label.configure(text="Verificando...")
        self.csv_status_label.configure(text="Verificando...")

        self.download_status_image.configure(image=self.status_images["waiting"])
        self.csv_status_image.configure(image=self.status_images["waiting"])

        worker: Thread = Thread(target=self._check_data_status_worker, daemon=True, name="DataStatusCheck", )
        worker.start()

        self.after(100, self._poll_data_status_queue)


    def _refresh_data_status( self ) -> None:
        """Atualiza os indicadores conforme o estado dos arquivos."""
        chirps_complete: bool = self.service.are_chirps_downloads_complete()
        csvs_complete: bool = self.service.are_station_csvs_complete()
        self.download_status_label.configure(text="Dados disponíveis" if chirps_complete else "Dados pendentes")
        self.csv_status_label.configure(text="CSVs disponíveis" if csvs_complete else "CSVs pendentes")
        self.generate_data_button.configure(state="normal")


    def _load_assets( self ):
        # Imagens dos estados dos indicadores.
        assets_dir = Path(__file__).resolve().parent / "assets"

        self.status_images: dict[str, ctk.CTkImage] = {
            "done"   : ctk.CTkImage(light_image=Image.open(assets_dir / "check-done.png"), size=(32, 32), ),
            "waiting": ctk.CTkImage(light_image=Image.open(assets_dir / "check-waiting.png"), size=(32, 32), ),
            "error"  : ctk.CTkImage(light_image=Image.open(assets_dir / "check-error.png"), size=(32, 32), ),
        }
        self.download_status_image = ctk.CTkLabel(self.download_status_frame, text="", image=self.status_images["waiting"], )
        self.csv_status_image = ctk.CTkLabel(self.csv_status_frame, text="", image=self.status_images["waiting"], )


    def _load_stations( self ) -> None:
        """Carrega os municípios e as estações disponíveis."""
        try:
            self._set_analysis_controls_enabled(enabled=False)
            municipalities: list[str] = (self.service.list_available_municipalities())

            self.state_selector.configure(values=municipalities)

            if not municipalities:
                self.state_selector.set("")
                self.station_selector.configure(values=[])
                self.station_selector.set("")
                self.station_names = []
                self.status_label.configure(text="Baixe os dados para habilitar a análise")
                return

            self.state_selector.set(municipalities[0])
            self._on_municipality_selected(municipalities[0])

            if self.station_names:
                self.station_selector.set(self.station_names[0])
                self._on_station_name_selected(self.station_names[0])
                self._set_analysis_controls_enabled(enabled=True)
            else:
                self._set_analysis_controls_enabled(enabled=False)


        except Exception as error:
            self._set_analysis_controls_enabled(False)
            self.logger.exception("Falha ao carregar municípios e estações")
            self.status_label.configure(text="Erro ao carregar municípios")
            messagebox.showerror("Erro", f"Não foi possível carregar os municípios e as estações.\n{error}", parent=self, )


    def _on_station_name_selected( self, station: str ) -> None:
        """Atualiza a interface após selecionar uma estação."""
        station = station.strip()

        if not station:
            self.status_label.configure(text="Selecione uma estação disponível.")
            return

        self.station_selector.set(station)

        self._on_station_selected(station)


    def _on_municipality_selected( self, municipality: str ) -> None:
        """Filtra as estações pelo município selecionado."""
        try:
            self.station_names = self.service.list_available_stations(municipality=municipality)

            self.station_selector.configure(values=self.station_names)

            if self.station_names:
                self.station_selector.set(self.station_names[0])
                self._on_station_selected(self.station_names[0])

                self.status_label.configure(text=(f"{len(self.station_names)} estações disponíveis "
                                                  f"em {municipality}"))
            else:
                self.station_selector.set("")
                self.graph_title.configure(text="Série temporal de precipitação")
                self.status_label.configure(text=f"Nenhuma estação disponível em {municipality}")

        except Exception as error:
            self._set_analysis_controls_enabled(False)
            self.logger.exception(f"Falha ao carregar estações do município {municipality}")
            self.status_label.configure(text="Erro ao filtrar estações")
            messagebox.showerror("Erro", f"Não foi possível carregar as estações.\n{error}", parent=self, )


    def _on_station_selected( self, station: str ) -> None:
        """Atualiza o título da estação selecionada."""
        self.graph_title.configure(text=station or "Gráfico da estação")


    def _on_generate_data_clicked( self ) -> None:
        """Inicia o pipeline em segundo plano."""

        years: list[int] = self._get_selected_years()

        if not years:
            self.status_label.configure(text="Selecione pelo menos um ano para download")
            return

        self._selected_years = years

        self.generate_data_button.configure(state="disabled")
        self.generate_data_button.configure(text="Processando...")

        self.progress_bar.set(0)
        self._start_loading_state()

        self.logger.info("Execução do pipeline CHIRPS iniciada pela interface.")

        worker: Thread = Thread(target=self._run_pipeline_worker, daemon=True, name="ChirpsPipeline", )
        worker.start()

        self.after(100, self._poll_pipeline_queue)


    def _on_year_selection_changed( self ):
        years: list[int] = [year for year, checkbox in self.year_checkboxes.items() if checkbox.get()]
        if years:
            self.state_label.configure(text=f"{len(years)} ano(s) selecionado(s) para download")
        else:
            self.status_label.configure(text="Selecione os anos para download")


    def _set_analysis_controls_enabled( self, enabled: bool ):
        """Habilita ou desabilita os controles de análise."""
        state: str = "normal" if enabled else "disabled"
        selector_state: str = "readonly" if enabled else "disabled"

        self.state_selector.configure(state=selector_state)
        self.station_selector.configure(state=selector_state)

        self.fill_checkbox.configure(state=state)
        self.line_checkbox.configure(state=state)
        self.update_button.configure(state=state)


    def _get_selected_years( self ) -> list[int]:
        """Retorna os anos selecionados na interface."""
        return [int(year) for year, checkbox in self.year_checkboxes.items() if checkbox.get()]


    def _get_chart_kind( self ) -> ChartKind:
        """Retorna o tipo de gráfico selecionado."""
        fill: bool = bool(self.fill_checkbox.get())
        line: bool = bool(self.line_checkbox.get())

        if fill and line:
            return ChartKind.AREA

        if fill:
            return ChartKind.FILL

        if line:
            return ChartKind.LINE

        raise ValueError("Selecione linha, preenchimento ou ambos.")


    def _update_plot( self ) -> None:
        """Gera e exibe o gráfico selecionado."""
        station: str = self.station_selector.get().strip()
        years: list[int] = [year for year, checkbox in self.year_checkboxes.items() if checkbox.get()]

        if not station or not self.station_names:
            self.status_label.configure(text="Baixe os dados antes de analisar as estações")
            return

        if not years:
            messagebox.showwarning("Anos", "Selecione pelo menos um ano.", parent=self, )
            return

        try:
            chart_kind: ChartKind = self._get_chart_kind()
            self.status_label.configure(text="Gerando gráfico...")
            self.update_idletasks()

            style = PlotStyle(kind=chart_kind)
            figure: Figure = self.service.generate_station_plot(station=station, years=years, style=style, layout=Layout.TIMELINE, )

            self._display_figure(figure)
            self.graph_title.configure(text=station)
            self.status_label.configure(text="Gráfico atualizado")

        except Exception as error:
            self.logger.exception("Falha ao gerar gráfico")
            self.status_label.configure(text="Erro ao gerar gráfico")
            messagebox.showerror("Erro ao gerar gráfico", str(error), parent=self, )


    def _display_figure( self, figure: Figure ) -> None:
        """Exibe uma figura Matplotlib dentro da janela."""
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()

        self.current_figure = figure
        self.canvas = FigureCanvasTkAgg(figure, master=self.graph_container, )
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True, )


def main() -> None:
    """Inicia a aplicação."""
    app = ChirpsApp()
    app.mainloop()


if __name__ == "__main__":
    main()
