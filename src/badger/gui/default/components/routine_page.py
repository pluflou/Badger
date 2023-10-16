import sqlite3
from typing import List

import numpy as np
import pandas as pd
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGroupBox, QLineEdit, QLabel, QMessageBox, QSizePolicy
from PyQt5.QtWidgets import QListWidgetItem, QWidget, QVBoxLayout, QHBoxLayout
from PyQt5.QtWidgets import QTableWidgetItem
from coolname import generate_slug
from xopt import VOCS

from .algo_cbox import BadgerAlgoBox
from .constraint_item import constraint_item
from .data_table import get_table_content_as_dict, set_init_data_table
from .env_cbox import BadgerEnvBox
from .filter_cbox import BadgerFilterBox
from .state_item import state_item
from ..windows.docs_window import BadgerDocsWindow
from ..windows.edit_script_dialog import BadgerEditScriptDialog
from ..windows.lim_vrange_dialog import BadgerLimitVariableRangeDialog
from ..windows.review_dialog import BadgerReviewDialog
from ..windows.var_dialog import BadgerVariableDialog
from ....db import save_routine, remove_routine
from ....environment import instantiate_env
from ....errors import BadgerRoutineError
from ....factory import list_algo, list_env, get_algo, get_env
from ....routine import Routine
from ....settings import read_value
from ....utils import ystring, load_config, strtobool

CONS_RELATION_DICT = {
    '>': 'GREATER_THAN',
    '<': 'LESS_THAN',
    '=': 'EQUAL_TO',
}


class BadgerRoutinePage(QWidget):
    def __init__(self):
        super().__init__()

        self.algos = list_algo()
        self.envs = list_env()
        self.env = None
        self.routine = None
        self.script = ''
        self.window_docs = BadgerDocsWindow(self, '')

        # Limit variable ranges
        self.limit_option = None

        self.init_ui()
        self.config_logic()

    def init_ui(self):
        # Set up the layout
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(11, 11, 19, 11)

        # Meta group
        group_meta = QGroupBox('Metadata')
        group_meta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vbox_meta = QVBoxLayout(group_meta)

        # Name
        name = QWidget()
        hbox_name = QHBoxLayout(name)
        hbox_name.setContentsMargins(0, 0, 0, 0)
        label = QLabel('Name')
        label.setFixedWidth(64)
        self.edit_save = edit_save = QLineEdit()
        edit_save.setPlaceholderText(generate_slug(2))
        hbox_name.addWidget(label)
        hbox_name.addWidget(edit_save, 1)
        vbox_meta.addWidget(name, alignment=Qt.AlignTop)

        # Tags
        self.cbox_tags = cbox_tags = BadgerFilterBox(title=' Tags')
        if not strtobool(read_value('BADGER_ENABLE_ADVANCED')):
            cbox_tags.hide()
        vbox_meta.addWidget(cbox_tags, alignment=Qt.AlignTop)
        # vbox_meta.addStretch()

        vbox.addWidget(group_meta)

        # Algo box
        self.algo_box = BadgerAlgoBox(None, self.algos)
        self.algo_box.expand()  # expand the box initially
        vbox.addWidget(self.algo_box)

        # Env box
        self.env_box = BadgerEnvBox(None, self.envs)
        self.env_box.expand()  # expand the box initially
        vbox.addWidget(self.env_box)

        vbox.addStretch()

    def config_logic(self):
        self.algo_box.cb.currentIndexChanged.connect(self.select_algo)
        self.algo_box.btn_docs.clicked.connect(self.open_algo_docs)
        self.algo_box.check_use_script.stateChanged.connect(self.toggle_use_script)
        self.algo_box.btn_edit_script.clicked.connect(self.edit_script)
        self.env_box.cb.currentIndexChanged.connect(self.select_env)
        self.env_box.btn_env_play.clicked.connect(self.open_playground)
        self.env_box.btn_add_var.clicked.connect(self.add_var)
        self.env_box.btn_lim_vrange.clicked.connect(self.limit_variable_ranges)
        self.env_box.btn_add_con.clicked.connect(self.add_constraint)
        self.env_box.btn_add_sta.clicked.connect(self.add_state)
        self.env_box.btn_add_curr.clicked.connect(self.fill_curr_in_init_table)
        self.env_box.btn_clear.clicked.connect(self.clear_init_table)
        self.env_box.btn_add_row.clicked.connect(self.add_row_to_init_table)

    def refresh_ui(self, routine: Routine):
        self.routine = routine  # save routine for future reference

        self.algos = list_algo()
        self.envs = list_env()
        # Clean up the constraints/states list
        self.env_box.list_con.clear()
        self.env_box.list_sta.clear()

        if routine is None:
            # Reset the algo and env configs
            self.algo_box.cb.setCurrentIndex(-1)
            self.env_box.cb.setCurrentIndex(-1)

            # Reset the routine configs check box status
            self.env_box.check_only_var.setChecked(False)
            self.env_box.check_only_obj.setChecked(False)

            # Reset the save settings
            name = generate_slug(2)
            self.edit_save.setText('')
            self.edit_save.setPlaceholderText(name)

            return

        # Fill in the algo and env configs
        name_algo = routine.generator.name
        idx_algo = self.algos.index(name_algo)
        self.algo_box.cb.setCurrentIndex(idx_algo)
        self.algo_box.edit.setPlainText(ystring(
            routine.generator.model_dump()))
        self.script = routine.script
        params_scaling = None
        idx_scaling = -1
        self.algo_box.cb_scaling.setCurrentIndex(idx_scaling)
        self.algo_box.edit_scaling.setPlainText(ystring(params_scaling))

        idx_env = self.envs.index(routine.environment.name)
        self.env_box.cb.setCurrentIndex(idx_env)
        self.env_box.edit.setPlainText(
            ystring(routine.environment.model_dump()))

        # Config the vocs panel
        self.env_box.check_only_var.setChecked(True)
        self.env_box.edit_var.clear()
        self.env_box.var_table.set_selected(routine.vocs.variable_names)
        self.env_box.var_table.set_bounds(routine.vocs.variables)

        set_init_data_table(self.env_box.init_table, routine.initial_points)

        self.env_box.check_only_obj.setChecked(True)
        self.env_box.edit_obj.clear()
        self.env_box.obj_table.set_selected(routine.vocs.objective_names)
        self.env_box.obj_table.set_rules(routine.vocs.objectives)

        if routine.vocs.constraints:  # constraints should be an ordered dict
            for i in range(len(routine['config']['constraints'])):
                name = next(iter(routine['config']['constraints'][i]))
                relation, thres = routine['config']['constraints'][i][name][:2]
                try:
                    routine['config']['constraints'][i][name][2]
                    critical = True
                except:
                    critical = False
                relation = ['GREATER_THAN', 'LESS_THAN',
                            'EQUAL_TO'].index(relation)
                self.add_constraint(name, relation, thres, critical)

        try:
            config_states = routine.states
        except AttributeError:
            config_states = None
        if config_states is not None:
            for name_sta in config_states:
                self.add_state(name_sta)

        # Config the metadata
        self.edit_save.setPlaceholderText(generate_slug(2))
        self.edit_save.setText(routine.name)

        tags = routine.tags
        try:
            self.cbox_tags.cb_obj.setCurrentText(tags['objective'])
        except:
            self.cbox_tags.cb_obj.setCurrentIndex(0)
        try:
            self.cbox_tags.cb_reg.setCurrentText(tags['region'])
        except:
            self.cbox_tags.cb_reg.setCurrentIndex(0)
        try:
            self.cbox_tags.cb_gain.setCurrentText(tags['gain'])
        except:
            self.cbox_tags.cb_gain.setCurrentIndex(0)

        self.algo_box.check_use_script.setChecked(not not self.script)

    def select_algo(self, i):
        # Reset the script
        self.script = ''
        self.algo_box.check_use_script.setChecked(False)

        if i == -1:
            self.algo_box.edit.setPlainText('')
            self.algo_box.cb_scaling.setCurrentIndex(-1)
            return

        name = self.algos[i]
        try:
            _, configs = get_algo(name)
            self.algo_box.edit.setPlainText(ystring(configs['params']))

            # Update the docs
            self.window_docs.update_docs(name)
        except Exception as e:
            self.algo_box.cb.setCurrentIndex(-1)
            return QMessageBox.critical(self, 'Error!', str(e))

    def toggle_use_script(self):
        if self.algo_box.check_use_script.isChecked():
            self.algo_box.btn_edit_script.show()
            self.algo_box.edit.setReadOnly(True)
            self.refresh_params_algo()
        else:
            self.algo_box.btn_edit_script.hide()
            self.algo_box.edit.setReadOnly(False)

    def edit_script(self):
        algo = self.algo_box.cb.currentText()
        dlg = BadgerEditScriptDialog(self, algo, self.script, self.script_updated)
        dlg.exec()

    def script_updated(self, text):
        self.script = text
        self.refresh_params_algo()

    def create_env(self):
        env_params = load_config(self.env_box.edit.toPlainText())
        try:
            intf_name = self.configs['interface'][0]
        except KeyError:
            intf_name = None
        configs = {
            'params': env_params,
            'interface': [intf_name]
        }
        env = instantiate_env(self.env, configs)

        return env

    def refresh_params_algo(self):
        if not self.script:
            return

        try:
            tmp = {}
            exec(self.script, tmp)
            try:
                tmp['generate']  # test if generate function is defined
            except Exception as e:
                QMessageBox.warning(self, 'Please define a valid generate function!', str(e))
                return

            env = self.create_env()
            # Get vocs
            try:
                vocs = self._compose_vocs()
            except Exception:
                vocs = None
            # Function generate comes from the script
            params_algo = tmp['generate'](env, vocs)
            self.algo_box.edit.setPlainText(ystring(params_algo))
        except Exception as e:
            QMessageBox.warning(self, 'Invalid script!', str(e))

    def select_env(self, i):
        if i == -1:
            self.env_box.edit.setPlainText('')
            self.env_box.edit_var.clear()
            self.env_box.var_table.update_variables(None)
            self.env_box.edit_obj.clear()
            self.env_box.obj_table.update_objectives(None)
            self.configs = None
            self.env = None
            self.env_box.btn_add_con.setDisabled(True)
            self.env_box.btn_add_sta.setDisabled(True)
            self.env_box.btn_add_var.setDisabled(True)
            self.env_box.btn_lim_vrange.setDisabled(True)
            self.routine = None
            return

        name = self.envs[i]
        try:
            env, configs = get_env(name)
            self.configs = configs
            self.env = env
            self.env_box.edit_var.clear()
            self.env_box.edit_obj.clear()
            self.env_box.btn_add_con.setDisabled(False)
            self.env_box.btn_add_sta.setDisabled(False)
            self.env_box.btn_add_var.setDisabled(False)
            self.env_box.btn_lim_vrange.setDisabled(False)
            if self.algo_box.check_use_script.isChecked():
                self.refresh_params_algo()
        except Exception as e:
            self.configs = None
            self.env = None
            self.env_box.cb.setCurrentIndex(-1)
            self.env_box.btn_add_con.setDisabled(True)
            self.env_box.btn_add_sta.setDisabled(True)
            self.env_box.btn_add_var.setDisabled(True)
            self.env_box.btn_lim_vrange.setDisabled(True)
            self.routine = None
            return QMessageBox.critical(self, 'Error!', str(e))

        self.env_box.edit.setPlainText(ystring(configs['params']))

        vars_env = configs['variables']
        vars_combine = [*vars_env]
        if self.routine:  # check for the temp variables in vocs
            var_names_vocs = self.routine.vocs.variable_names
            var_names_env = [next(iter(var)) for var in vars_env]
            for name in var_names_vocs:
                if name in var_names_env:
                    continue

                _var = {}
                _var[name] = [-100, 100]  # TODO: how to get better default bounds?
                vars_combine.append(_var)
        self.env_box.check_only_var.setChecked(False)
        self.env_box.var_table.update_variables(vars_combine)

        _objs_env = configs['observations']
        objs_env = []
        for name in _objs_env:
            obj = {}
            obj[name] = 'MINIMIZE'  # default rule
            objs_env.append(obj)
        self.env_box.check_only_obj.setChecked(False)
        self.env_box.obj_table.update_objectives(objs_env)

        self.env_box.list_con.clear()
        self.env_box.list_sta.clear()
        self.env_box.fit_content()
        self.routine = None

    def get_init_table_header(self):
        table = self.env_box.init_table
        header_list = []
        for col in range(table.columnCount()):
            item = table.horizontalHeaderItem(col)
            if item:
                header_list.append(item.text())
            else:
                header_list.append('')  # Handle the case where the header item is None
        return header_list

    def fill_curr_in_init_table(self):
        env = self.create_env()
        table = self.env_box.init_table
        vname_selected = self.get_init_table_header()
        var_curr = env._get_variables(vname_selected)

        # Iterate through the rows
        for row in range(table.rowCount()):
            # Check if the row is empty
            if np.all([not table.item(row, col).text() for col in range(table.columnCount())]):
                # Fill the row with content_list
                for col, name in enumerate(vname_selected):
                    item = QTableWidgetItem(str(var_curr[name]))
                    table.setItem(row, col, item)
                break  # Stop after filling the first non-empty row

    def clear_init_table(self):
        table = self.env_box.init_table
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item:
                    item.setText('')  # Set the cell content to an empty string

    def add_row_to_init_table(self):
        table = self.env_box.init_table
        row_position = table.rowCount()
        table.insertRow(row_position)

        for col in range(table.columnCount()):
            item = QTableWidgetItem('')
            table.setItem(row_position, col, item)

    def open_playground(self):
        pass

    def open_algo_docs(self):
        self.window_docs.show()

    def add_var(self):
        # TODO: Use a cached env
        env_params = load_config(self.env_box.edit.toPlainText())
        try:
            intf_name = self.configs['interface'][0]
        except KeyError:
            intf_name = None
        configs = {
            'params': env_params,
            'interface': [intf_name]
        }

        dlg = BadgerVariableDialog(self, self.env, configs, self.add_var_to_list)
        dlg.exec()

    def limit_variable_ranges(self):
        dlg = BadgerLimitVariableRangeDialog(
            self, self.set_vrange,
            self.save_limit_option,
            self.limit_option,
        )
        dlg.exec()

    def set_vrange(self):
        vname_selected = []
        vrange = []

        for var in self.env_box.var_table.all_variables:
            name = next(iter(var))
            if self.env_box.var_table.is_checked(name):
                vname_selected.append(name)
                vrange.append({name: var[name]})

        env = self.create_env()
        var_curr = env._get_variables(vname_selected)

        option_idx = self.limit_option['limit_option_idx']
        if option_idx:
            ratio = self.limit_option['ratio_full']
            for i, name in enumerate(vname_selected):
                hard_bounds = vrange[i][name]
                delta = 0.5 * ratio * (hard_bounds[1] - hard_bounds[0])
                bounds = [var_curr[name] - delta, var_curr[name] + delta]
                bounds = np.clip(bounds, hard_bounds[0], hard_bounds[1]).tolist()
                vrange[i][name] = bounds
        else:
            ratio = self.limit_option['ratio_curr']
            for i, name in enumerate(vname_selected):
                hard_bounds = vrange[i][name]
                sign = np.sign(var_curr[name])
                bounds = [var_curr[name] * (1 - 0.5 * sign * ratio),
                          var_curr[name] * (1 + 0.5 * sign * ratio)]
                bounds = np.clip(bounds, hard_bounds[0], hard_bounds[1]).tolist()
                vrange[i][name] = bounds

        self.env_box.var_table.set_bounds(vrange)

    def save_limit_option(self, limit_option):
        self.limit_option = limit_option

    def add_var_to_list(self, name, lb, ub):
        # Check if already in the list
        ok = False
        try:
            self.env_box.var_table.bounds[name]
        except KeyError:
            ok = True
        if not ok:
            QMessageBox.warning(self, 'Variable already exists!', f'Variable {name} already exists!')
            return 1

        self.env_box.add_var(name, lb, ub)
        return 0

    def add_constraint(self, name=None, relation=0, threshold=0, critical=False):
        if self.configs is None:
            return

        options = self.configs['observations']
        item = QListWidgetItem(self.env_box.list_con)
        con_item = constraint_item(options,
                                   lambda: self.env_box.list_con.takeItem(
                                       self.env_box.list_con.row(item)),
                                   name, relation, threshold, critical)
        item.setSizeHint(con_item.sizeHint())
        self.env_box.list_con.addItem(item)
        self.env_box.list_con.setItemWidget(item, con_item)
        # self.env_box.dict_con[''] = item
        self.env_box.fit_content()

    def add_state(self, name=None):
        if self.configs is None:
            return

        var_names = [next(iter(d)) for d in self.configs['variables']]
        options = self.configs['observations'] + var_names
        item = QListWidgetItem(self.env_box.list_sta)
        sta_item = state_item(options,
                              lambda: self.env_box.list_sta.takeItem(
                                  self.env_box.list_sta.row(item)), name)
        item.setSizeHint(sta_item.sizeHint())
        self.env_box.list_sta.addItem(item)
        self.env_box.list_sta.setItemWidget(item, sta_item)
        self.env_box.fit_content()

    def _compose_vocs(self) -> (VOCS, List[str]):
        # Compose the VOCS settings
        variables = self.env_box.var_table.export_variables()
        objectives = self.env_box.obj_table.export_objectives()

        constraints = {}
        critical_constraints = []
        for i in range(self.env_box.list_con.count()):
            item = self.env_box.list_con.item(i)
            item_widget = self.env_box.list_con.itemWidget(item)
            critical = item_widget.check_crit.isChecked()
            con_name = item_widget.cb_obs.currentText()
            relation = CONS_RELATION_DICT[item_widget.cb_rel.currentText()]
            value = item_widget.sb.value()
            constraints[con_name] = [relation, value]
            if critical:
                critical_constraints.append(con_name)

        states = {}
        for i in range(self.env_box.list_sta.count()):
            raise NotImplementedError("constants/states has not been implemented yet!")
            #item = self.env_box.list_sta.item(i)
            #item_widget = self.env_box.list_sta.itemWidget(item)
            #sta_name = item_widget.cb_sta.currentText()
            #states[sta_name] =

        vocs = VOCS(
            variables=variables,
            objectives=objectives,
            constraints={},
            constants={}
        )

        return vocs, critical_constraints

    def _compose_routine(self) -> Routine:
        # Compose the routine
        name = self.edit_save.text() or self.edit_save.placeholderText()

        if self.algo_box.cb.currentIndex() == -1:
            raise BadgerRoutineError("no algorithm selected")
        if self.env_box.cb.currentIndex() == -1:
            raise BadgerRoutineError("no environment selected")

        algo_name = self.algos[self.algo_box.cb.currentIndex()]
        env_name = self.envs[self.env_box.cb.currentIndex()]
        algo_params = load_config(self.algo_box.edit.toPlainText())
        env_params = load_config(self.env_box.edit.toPlainText())

        # VOCS
        vocs, critical_constraints = self._compose_vocs()

        # Generator
        generator_class = get_generator(algo_name)
        algo_params_copy = copy.deepcopy(algo_params)
        try:
            del algo_params_copy['start_from_current']
        except KeyError:
            pass
        # Note! The following line will remove all the name fields in
        # generator params. That's why we make a copy here so the modification
        # will not affect the routine to be saved (in archive)
        generator = generator_class(vocs=vocs, **algo_params_copy)

        # Initial points
        init_points_df = pd.DataFrame.from_dict(
            get_table_content_as_dict(self.env_box.init_table))
        init_points_df = init_points_df.replace('', pd.NA)
        init_points_df = init_points_df.dropna(subset=init_points_df.columns,
                                               how='all')
        contains_na = init_points_df.isna().any().any()
        if contains_na:
            raise BadgerRoutineError(
                'Initial points are not valid, please fill in the missing values'
            )

        # Script that generates algo params
        if self.algo_box.check_use_script.isChecked():
            script = self.script
        else:
            script = None

        return Routine(
            # Xopt part
            vocs=vocs,
            generator={"name": algo_name} | algo_params,
            # Badger part
            name=name,
            initial_points=init_points_df.astype("double"),
            tags=None,
            environment_name=env_name,
            environment=env_params,
            critical_constraint_names=critical_constraints,
            script=script,
        )

    def review(self):
        try:
            routine = self._compose_routine()
        except Exception as e:
            return QMessageBox.critical(self, 'Error!', str(e))

        dlg = BadgerReviewDialog(self, routine)
        dlg.exec()

    def save(self):
        try:
            routine = self._compose_routine()
        except Exception as e:
            return QMessageBox.critical(self, 'Error!', str(e))

        try:
            save_routine(routine)
        except sqlite3.IntegrityError:
            return QMessageBox.critical(
                self, 'Error!',
                f'Routine {routine.name} already existed in the database! Please choose another name.')

        return 0

    def delete(self):
        name = self.edit_save.text() or self.edit_save.placeholderText()
        remove_routine(name)

        return 0
