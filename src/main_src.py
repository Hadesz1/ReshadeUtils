#! /usr/bin/env python3
# |*****************************************************
# * Copyright         : Copyright (C) 2019
# * Author            : ddc
# * License           : GPL v3
# * Python            : 3.6
# |*****************************************************
# # -*- coding: utf-8 -*-

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from src.utils.create_files import CreateFiles
from src.utils import constants, messages, utilities
import logging.handlers
import sys
import os
from src.sql.initial_tables_sql import InitialTablesSql
from src.sql.triggers_sql import TriggersSql
from src.sql.configs_sql import ConfigsSql
from src.sql.games_sql import GamesSql
from src.game_configs import UiGameConfigForm
import requests
import urllib.request
from bs4 import BeautifulSoup
from src.form_events import FormEvents


class MainSrc:
    def __init__(self, qtObj, form):
        self.qtObj = qtObj
        self.form = form
        self.settings = None
        self.selected_game = None
        self.game_config_form = None
        self.reshade_version = None
        self.use_dark_theme = None
        self.update_shaders = None
        self.check_program_updates = None
        self.check_reshade_updates = None
        self.create_screenshots_folder = None
        self.reset_reshade_files = None
        self.need_apply = False
        self.new_version = None
        self.db_conn = None
        self.remote_reshade_version = None

    ################################################################################
    def init(self):
        sys.excepthook = utilities.log_uncaught_exceptions
        self.qtObj.programs_tableWidget.horizontalHeader().setDefaultAlignment(Qt.AlignLeft)
        self._check_dirs()
        self._setup_logging()
        self._check_files()
        self.settings = utilities.get_all_ini_file_settings(constants.db_settings_filename)
        self._check_db_connection()
        self._set_default_database_configs()
        self._set_all_configs()
        self._register_form_events()
        self._check_new_program_version()
        self._check_new_reshade_version()
        self.qtObj.main_tabWidget.setCurrentIndex(0)
        self.qtObj.architecture_groupBox.setEnabled(False)
        self.qtObj.api_groupBox.setEnabled(False)
        self.enable_widgets(False)

    ################################################################################
    def _register_form_events(self):
        self.qtObj.add_button.clicked.connect(lambda: FormEvents.add_game(self))
        self.qtObj.delete_button.clicked.connect(lambda: FormEvents.delete_game(self))
        self.qtObj.edit_path_button.clicked.connect(lambda: FormEvents.edit_game_path(self))
        self.qtObj.open_config_button.clicked.connect(lambda: FormEvents.open_reshade_config_file(self))
        self.qtObj.update_button.clicked.connect(lambda: FormEvents.update_program(self))
        self.qtObj.apply_button.clicked.connect(lambda: FormEvents.apply(self))
        self.qtObj.edit_default_config_button.clicked.connect(lambda: FormEvents.edit_default_config_file(self))
        #########
        self.qtObj.programs_tableWidget.clicked.connect(self._programs_tableWidget_clicked)
        self.qtObj.programs_tableWidget.itemDoubleClicked.connect(self._programs_tableWidget_double_clicked)
        #########
        self.qtObj.yes_dark_theme_radioButton.clicked.connect(lambda: FormEvents.dark_theme_clicked(self, "YES"))
        self.qtObj.no_dark_theme_radioButton.clicked.connect(lambda: FormEvents.dark_theme_clicked(self, "NO"))
        #########
        self.qtObj.yes_check_program_updates_radioButton.clicked.connect(
            lambda: FormEvents.check_program_updates_clicked(self, "YES"))
        self.qtObj.no_check_program_updates_radioButton.clicked.connect(
            lambda: FormEvents.check_program_updates_clicked(self, "NO"))
        #########
        self.qtObj.yes_check_reshade_updates_radioButton.clicked.connect(
            lambda: FormEvents.check_reshade_updates_clicked(self, "YES"))
        self.qtObj.no_check_reshade_updates_radioButton.clicked.connect(
            lambda: FormEvents.check_reshade_updates_clicked(self, "NO"))
        #########
        self.qtObj.yes_update_shaders_radioButton.clicked.connect(
            lambda: FormEvents.update_shaders_clicked(self, "YES"))
        self.qtObj.no_update_shaders_radioButton.clicked.connect(
            lambda: FormEvents.update_shaders_clicked(self, "NO"))
        #########
        self.qtObj.yes_screenshots_folder_radioButton.clicked.connect(
            lambda: FormEvents.create_screenshots_folder_clicked(self, "YES"))
        self.qtObj.no_screenshots_folder_radioButton.clicked.connect(
            lambda: FormEvents.create_screenshots_folder_clicked(self, "NO"))
        #########
        self.qtObj.yes_reset_reshade_radioButton.clicked.connect(
            lambda: FormEvents.reset_reshade_files_clicked(self, "YES"))
        self.qtObj.no_reset_reshade_radioButton.clicked.connect(
            lambda: FormEvents.reset_reshade_files_clicked(self, "NO"))

    ################################################################################
    def _check_new_program_version(self):
        self.qtObj.updateAvail_label.clear()
        self.qtObj.update_button.setVisible(False)
        if self.check_program_updates:
            new_version_obj = utilities.check_new_program_version(self, False)
            if new_version_obj.new_version_available:
                self.new_version = new_version_obj.new_version
                self.qtObj.update_button.setFocus()
                self.qtObj.updateAvail_label.clear()
                self.qtObj.updateAvail_label.setText(new_version_obj.new_version_msg)
                self.qtObj.update_button.setVisible(True)

    ################################################################################
    def _check_new_reshade_version(self):
        self.remote_reshade_version = None
        if self.check_reshade_updates:
            try:
                utilities.show_progress_bar(self, messages.checking_new_reshade_version, 0)
                response = requests.get(constants.reshade_website_url)
                utilities.show_progress_bar(self, messages.checking_new_reshade_version, 50)
                if response.status_code != 200:
                    self.log.error(messages.reshade_page_error)
                else:
                    html = str(response.text)
                    soup = BeautifulSoup(html, "html.parser")
                    body = soup.body
                    blist = str(body).split("<p>")

                    for content in blist:
                        if content.startswith('<strong>Version '):
                            self.remote_reshade_version = content.split()[1].strip("</strong>")
                            break
                utilities.show_progress_bar(self, messages.checking_new_reshade_version, 100)
            except requests.exceptions.ConnectionError as e:
                self.log.error(f"{messages.reshade_website_unreacheable} {e}")
                utilities.show_message_window("error", "ERROR", messages.reshade_website_unreacheable)
                return

            if self.remote_reshade_version is not None:
                if self.reshade_version != self.remote_reshade_version:
                    self.need_apply = True
                    self._download_new_reshade_version()

    ################################################################################
    def _download_new_reshade_version(self):
        old_reshade_version = self.reshade_version
        self.reshade_version = None
        exe_download_url = None
        download_path = f"{constants.program_path}\ReShade_Setup_"

        # get new version number
        try:
            utilities.show_progress_bar(self, messages.downloading_new_reshade_version, 0)
            response = requests.get(constants.reshade_website_url)
            if response.status_code != 200:
                self.log.error(messages.reshade_page_error)
            else:
                html = str(response.text)
                soup = BeautifulSoup(html, "html.parser")
                body = soup.body
                blist = str(body).split("<p>")

                utilities.show_progress_bar(self, messages.downloading_new_reshade_version, 0)
                for content in blist:
                    if content.startswith('<strong>Version '):
                        self.reshade_version = content.split()[1].strip("</strong>")
                        exe_download_url = f"{constants.reshade_exe_url}{self.reshade_version}.exe"
                        break
                utilities.show_progress_bar(self, messages.downloading_new_reshade_version, 20)
        except requests.exceptions.ConnectionError as e:
            self.log.error(f"{messages.reshade_website_unreacheable} {e}")
            utilities.show_message_window("error", "ERROR", messages.reshade_website_unreacheable)
            return

        # download new version exe
        try:
            utilities.show_progress_bar(self, messages.downloading_new_reshade_version, 40)
            local_reshade_exe = f"{download_path}{self.reshade_version}.exe"
            urllib.request.urlretrieve(exe_download_url, local_reshade_exe)
        except Exception as e:
            if e.errno == 13:
                utilities.show_message_window("error", "ERROR", messages.error_permissionError)
            else:
                self.log.error(f"{messages.error_check_new_reshade_version} {e}")
            return

        if old_reshade_version != self.reshade_version:
            # remove old version
            old_local_reshade_exe = f"{download_path}{old_reshade_version}.exe"
            if os.path.isfile(old_local_reshade_exe):
                os.remove(old_local_reshade_exe)
            if os.path.isfile(constants.reshade32_path):
                os.remove(constants.reshade32_path)
            if os.path.isfile(constants.reshade64_path):
                os.remove(constants.reshade64_path)

        # unzip reshade
        utilities.show_progress_bar(self, messages.downloading_new_reshade_version, 60)
        self._unzip_reshade(local_reshade_exe)

        # save version to sql table
        utilities.show_progress_bar(self, messages.downloading_new_reshade_version, 80)
        configSql = ConfigsSql(self)
        configsObj = utilities.Object()
        configsObj.reshade_version = self.reshade_version
        configSql.update_reshade_version(configsObj)

        # set version label
        self.qtObj.reshade_version_label.clear()
        self.qtObj.reshade_version_label.setText(f"{messages.info_reshade_version}{self.reshade_version}")
        utilities.show_progress_bar(self, messages.downloading_new_reshade_version, 100)

        if self.need_apply:
            utilities.show_message_window("info", "INFO",
                                      f"{messages.new_reshade_version}\nVersion: {self.reshade_version}")
            self.need_apply = False

    ################################################################################
    def _unzip_reshade(self, local_reshade_exe):
        try:
            out_path = constants.program_path
            utilities.unzip_file(local_reshade_exe, out_path)
        # except FileNotFoundError as e:
        #    self.log.error(f"{e}")
        # except zipfile.BadZipFile as e:
        #    self.log.error(f"{e}")
        except Exception as e:
            self.log.error(f"{e}")

    ################################################################################
    def _check_dirs(self):
        try:
            if not os.path.exists(constants.program_path):
                os.makedirs(constants.program_path)
        except OSError as e:
            self.log.error(f"{e}")

    ################################################################################
    def _setup_logging(self):
        logger = logging.getLogger()
        logger.setLevel(constants.LOG_LEVEL)
        file_hdlr = logging.handlers.RotatingFileHandler(
            filename=constants.error_logs_filename,
            maxBytes=10 * 1024 * 1024,
            encoding="utf-8",
            backupCount=5,
            mode='a')
        file_hdlr.setFormatter(constants.LOG_FORMATTER)
        logger.addHandler(file_hdlr)
        self.log = logging.getLogger(__name__)

    ################################################################################
    def _check_files(self):
        create_files = CreateFiles(self)

        try:
            if not os.path.exists(constants.db_settings_filename):
                create_files.create_settings_file()
        except Exception as e:
            self.log.error(f"{e}")

        try:
            if not os.path.exists(constants.style_qss_filename):
                create_files.create_style_file()
        except Exception as e:
            self.log.error(f"{e}")

        try:
            if not os.path.exists(constants.reshade_plugins_filename):
                create_files.create_reshade_plugins_ini_file()
        except Exception as e:
            self.log.error(f"{e}")

    ################################################################################
    def _check_db_connection(self):
        db_conn = utilities.check_database_connection(self)
        if db_conn is None:
            error_db_conn = messages.error_db_connection
            msg_exit = messages.exit_program
            utilities.show_message_window("error", "ERROR", f"{error_db_conn}\n\n{msg_exit}")
            sys.exit(0)

    ################################################################################
    def _en_dis_apply_button(self):
        len_programs = self.qtObj.programs_tableWidget.rowCount()
        if len_programs == 0:
            self.qtObj.apply_button.setEnabled(False)
        else:
            self.qtObj.apply_button.setEnabled(True)

    ################################################################################
    def _programs_tableWidget_clicked(self, item):
        FormEvents.programs_tableWidget_clicked(self, item)

    ################################################################################
    def _programs_tableWidget_double_clicked(self):
        self._show_game_config_form(self.selected_game.rs[0]["name"])

    ################################################################################
    def _set_default_database_configs(self):
        initialTablesSql = InitialTablesSql(self)
        it = initialTablesSql.create_initial_tables()
        if it is not None:
            err_msg = messages.error_create_sql_config_msg
            self.log.error(err_msg)
            print(err_msg)
            # sys.exit()

        configSql = ConfigsSql(self)
        rsConfig = configSql.get_configs()

        if rsConfig is not None and len(rsConfig) == 0:
            configsObj = utilities.Object()
            configsObj.use_dark_theme = "Y"
            configsObj.update_shaders = "Y"
            configsObj.check_program_updates = "Y"
            configsObj.check_reshade_updates = "Y"
            configsObj.create_screenshots_folder = "Y"
            configSql.set_default_configs(configsObj)

        triggersSql = TriggersSql(self)
        tr = triggersSql.create_triggers()
        if tr is not None:
            err_msg = messages.error_create_sql_config_msg
            self.log.error(err_msg)
            print(err_msg)
            # sys.exit()
    ################################################################################
    def _check_reshade_files(self, rsConfig):
        if rsConfig[0]["reshade_version"] is not None and len(rsConfig[0]["reshade_version"]) > 0:
            self.reshade_version = rsConfig[0]["reshade_version"]
            self.qtObj.reshade_version_label.setText(f"{messages.info_reshade_version}{self.reshade_version}")
            self.enable_form(True)
            local_reshade_exe = f"{constants.program_path}\ReShade_Setup_{self.reshade_version}.exe"
        else:
            self._download_new_reshade_version()
            return

        try:
            if not os.path.exists(local_reshade_exe):
                self._download_new_reshade_version()
        except OSError as e:
            self.log.error(f"{e}")

        try:
            if not os.path.exists(constants.reshade32_path):
                if not os.path.exists(local_reshade_exe):
                    self._download_new_reshade_version()
                else:
                    self._unzip_reshade(local_reshade_exe)
        except OSError as e:
            self.log.error(f"{e}")

        try:
            if not os.path.exists(constants.reshade64_path):
                if not os.path.exists(local_reshade_exe):
                    self._download_new_reshade_version()
                else:
                    self._unzip_reshade(local_reshade_exe)
        except OSError as e:
            self.log.error(f"{e}")

    ################################################################################
    def _set_all_configs(self):
        configSql = ConfigsSql(self)
        rsConfig = configSql.get_configs()

        self.populate_programs_listWidget()

        if rsConfig is not None and len(rsConfig) > 0:
            self._check_reshade_files(rsConfig)

            if rsConfig[0]["use_dark_theme"].upper() == "N":
                self.use_dark_theme = False
                self.set_style_sheet(False)
                self.qtObj.yes_dark_theme_radioButton.setChecked(False)
                self.qtObj.no_dark_theme_radioButton.setChecked(True)
            else:
                self.use_dark_theme = True
                self.set_style_sheet(True)
                self.qtObj.yes_dark_theme_radioButton.setChecked(True)
                self.qtObj.no_dark_theme_radioButton.setChecked(False)

            if rsConfig[0]["update_shaders"].upper() == "N":
                self.update_shaders = False
                self.qtObj.yes_update_shaders_radioButton.setChecked(False)
                self.qtObj.no_update_shaders_radioButton.setChecked(True)
            else:
                self.update_shaders = True
                self.qtObj.yes_update_shaders_radioButton.setChecked(True)
                self.qtObj.no_update_shaders_radioButton.setChecked(False)

            if rsConfig[0]["check_program_updates"].upper() == "N":
                self.check_program_updates = False
                self.qtObj.yes_check_program_updates_radioButton.setChecked(False)
                self.qtObj.no_check_program_updates_radioButton.setChecked(True)
            else:
                self.check_program_updates = True
                self.qtObj.yes_check_program_updates_radioButton.setChecked(True)
                self.qtObj.no_check_program_updates_radioButton.setChecked(False)

            if rsConfig[0]["check_reshade_updates"].upper() == "N":
                self.check_reshade_updates = False
                self.qtObj.yes_check_reshade_updates_radioButton.setChecked(False)
                self.qtObj.no_check_reshade_updates_radioButton.setChecked(True)
            else:
                self.check_reshade_updates = True
                self.qtObj.yes_check_reshade_updates_radioButton.setChecked(True)
                self.qtObj.no_check_reshade_updates_radioButton.setChecked(False)

            if rsConfig[0]["create_screenshots_folder"].upper() == "N":
                self.create_screenshots_folder = False
                self.qtObj.yes_screenshots_folder_radioButton.setChecked(False)
                self.qtObj.no_screenshots_folder_radioButton.setChecked(True)
            else:
                self.create_screenshots_folder = True
                self.qtObj.yes_screenshots_folder_radioButton.setChecked(True)
                self.qtObj.no_screenshots_folder_radioButton.setChecked(False)

            if rsConfig[0]["reset_reshade_files"].upper() == "N":
                self.reset_reshade_files = False
                self.qtObj.yes_reset_reshade_radioButton.setChecked(False)
                self.qtObj.no_reset_reshade_radioButton.setChecked(True)
            else:
                self.reset_reshade_files = True
                self.qtObj.yes_reset_reshade_radioButton.setChecked(True)
                self.qtObj.no_reset_reshade_radioButton.setChecked(False)

    ################################################################################
    def _show_game_config_form(self, game_name: str):
        self.game_config_form = QtWidgets.QWidget()
        _translate = QtCore.QCoreApplication.translate
        qtObj = UiGameConfigForm()
        qtObj.setupUi(self.game_config_form)
        self.game_config_form.qtObj = qtObj
        if self.use_dark_theme:
            self.game_config_form.setStyleSheet(open(constants.style_qss_filename, "r").read())
        self.game_config_form.qtObj.game_name_lineEdit.setFocus()
        self.game_config_form.show()
        QtWidgets.QApplication.processEvents()

        self.game_config_form.qtObj.ok_pushButton.clicked.connect(lambda: FormEvents.game_config_form(self, "OK"))
        self.game_config_form.qtObj.cancel_pushButton.clicked.connect(
            lambda: FormEvents.game_config_form(self, "CANCEL"))

        if self.selected_game is not None:
            self.game_config_form.qtObj.game_name_lineEdit.setText(self.selected_game.rs[0]["name"])
            if self.selected_game.rs[0]["architecture"] == "32bits":
                self.game_config_form.qtObj.radioButton_32bits.setChecked(True)
                self.game_config_form.qtObj.radioButton_64bits.setChecked(False)
            else:
                self.game_config_form.qtObj.radioButton_32bits.setChecked(False)
                self.game_config_form.qtObj.radioButton_64bits.setChecked(True)

            if self.selected_game.rs[0]["api"] == "DX9":
                self.game_config_form.qtObj.dx9_radioButton.setChecked(True)
                self.game_config_form.qtObj.dx11_radioButton.setChecked(False)
            else:
                self.game_config_form.qtObj.dx9_radioButton.setChecked(False)
                self.game_config_form.qtObj.dx11_radioButton.setChecked(True)
        else:
            self.game_config_form.qtObj.game_name_lineEdit.setText(game_name)

    ################################################################################
    def set_style_sheet(self, status: bool):
        if status:
            self.form.setStyleSheet(open(constants.style_qss_filename, "r").read())
        else:
            self.form.setStyleSheet("")

    ################################################################################
    def populate_programs_listWidget(self):
        self.qtObj.programs_tableWidget.setRowCount(0)
        games_sql = GamesSql(self)
        rs_all_games = games_sql.get_all_games()
        if rs_all_games is not None and len(rs_all_games) > 0:
            for i in range(len(rs_all_games)):
                num_rows = self.qtObj.programs_tableWidget.rowCount()
                self.qtObj.programs_tableWidget.insertRow(num_rows)
                self.qtObj.programs_tableWidget.setItem(num_rows, 0,
                                                        QtWidgets.QTableWidgetItem(rs_all_games[i]["name"]))
                self.qtObj.programs_tableWidget.setItem(num_rows, 1,
                                                        QtWidgets.QTableWidgetItem(rs_all_games[i]["path"]))

    ################################################################################
    def enable_form(self, status: bool):
        self.qtObj.add_button.setEnabled(status)
        num_pages = self.qtObj.main_tabWidget.count()

        if status:
            self.qtObj.main_tabWidget.setCurrentIndex(0)  # set to first tab
        else:
            self.selected_game = None
            self.qtObj.main_tabWidget.setCurrentIndex(num_pages - 1)  # set to last tab (about)

        for x in range(0, num_pages):
            self.qtObj.main_tabWidget.setTabEnabled(x, status)

    ################################################################################
    def enable_widgets(self, status: bool):
        if not status:
            self.selected_game = None

            self.qtObj.radioButton_32bits.setAutoExclusive(False)
            self.qtObj.radioButton_32bits.setChecked(False)
            self.qtObj.radioButton_32bits.setAutoExclusive(True)

            self.qtObj.radioButton_64bits.setAutoExclusive(False)
            self.qtObj.radioButton_64bits.setChecked(False)
            self.qtObj.radioButton_64bits.setAutoExclusive(True)

            self.qtObj.dx9_radioButton.setAutoExclusive(False)
            self.qtObj.dx9_radioButton.setChecked(False)
            self.qtObj.dx9_radioButton.setAutoExclusive(True)

            self.qtObj.dx11_radioButton.setAutoExclusive(False)
            self.qtObj.dx11_radioButton.setChecked(False)
            self.qtObj.dx11_radioButton.setAutoExclusive(True)

        self._en_dis_apply_button()
        self.qtObj.delete_button.setEnabled(status)
        self.qtObj.edit_path_button.setEnabled(status)
        self.qtObj.open_config_button.setEnabled(status)
