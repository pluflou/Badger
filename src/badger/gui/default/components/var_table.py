from PyQt5.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QCheckBox,
    QApplication,
    QLineEdit
)
from PyQt5.QtCore import pyqtSignal, Qt
from .robust_spinbox import RobustSpinBox


class VariableTable(QTableWidget):
    sig_sel_changed = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Reorder the rows by dragging around
        # self.setSelectionBehavior(self.SelectRows)
        # self.setSelectionMode(self.SingleSelection)
        # self.setShowGrid(False)
        # self.setDragDropMode(self.InternalMove)
        # self.setDragDropOverwriteMode(False)

        self.setRowCount(0)
        self.setColumnCount(4)
        self.setAlternatingRowColors(True)
        self.setStyleSheet("alternate-background-color: #262E38;")
        #self.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        # header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        # header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.setColumnWidth(0, 20)
        self.setColumnWidth(2, 96)
        self.setColumnWidth(3, 96)

        self.all_variables = []
        self.variables = []
        self.selected = {}  # track var selected status
        self.bounds = {}  # track var bounds
        self.checked_only = False

        self.config_logic()

    def config_logic(self):
        self.horizontalHeader().sectionClicked.connect(self.header_clicked)

    def is_all_checked(self):
        for i in range(self.rowCount()):
            item = self.cellWidget(i, 0)
            if not item.isChecked():
                return False

        return True

    def header_clicked(self, idx):
        if idx:
            return

        all_checked = self.is_all_checked()

        for i in range(self.rowCount()):
            item = self.cellWidget(i, 0)
            # Doing batch update
            item.blockSignals(True)
            item.setChecked(not all_checked)
            item.blockSignals(False)
        self.update_selected(0)

    def update_bounds(self):
        for i in range(self.rowCount()):
            name = self.item(i, 1).text()
            sb_lower = self.cellWidget(i, 2)
            sb_upper = self.cellWidget(i, 3)
            self.bounds[name] = [sb_lower.value(), sb_upper.value()]

    def set_bounds(self, variables: dict):
        for name in variables:
            self.bounds[name] = variables[name]

        self.update_variables(self.variables, 2)

    def update_selected(self, _):
        for i in range(self.rowCount()):
            _cb = self.cellWidget(i, 0)
            name = self.item(i, 1).text()
            print(name)
            self.selected[name] = _cb.isChecked()

        self.sig_sel_changed.emit()

        if self.checked_only:
            self.show_checked_only()

    def set_selected(self, variable_names):
        self.selected = {}
        for vname in variable_names:
            self.selected[vname] = True

        self.update_variables(self.variables, 2)

    def toggle_show_mode(self, checked_only):
        self.checked_only = checked_only
        if checked_only:
            self.show_checked_only()
        else:
            self.show_all()

    def show_checked_only(self):
        checked_variables = []
        for var in self.variables:
            name = next(iter(var))
            if self.is_checked(name):
                checked_variables.append(var)
        self.update_variables(checked_variables, 2)

    def show_all(self):
        self.update_variables(self.variables, 2)

    def is_checked(self, name):
        try:
            _checked = self.selected[name]
        except KeyError:
            _checked = False

        return _checked

    def update_variables(self, variables, filtered=0):
        # filtered = 0: completely refresh
        # filtered = 1: filtered by keyword
        # filtered = 2: just rerender based on check status

        self.setRowCount(0)
        self.horizontalHeader().setVisible(False)

        if not filtered:
            self.all_variables = variables or []
            self.variables = self.all_variables
            self.selected = {}
            self.bounds = {}
            for var in self.variables:
                name = next(iter(var))
                self.bounds[name] = var[name]
        elif filtered == 1:
            self.variables = variables or []

        if not variables:
            return

        _variables = []
        if self.checked_only:
            for var in variables:
                name = next(iter(var))
                if self.is_checked(name):
                    _variables.append(var)
        else:
            _variables = variables

        n = len(_variables) + 1
        self.setRowCount(n)
        for i, var in enumerate(_variables):
            name = next(iter(var))
            vrange = var[name]

            self.setCellWidget(i, 0, QCheckBox())

            _cb = self.cellWidget(i, 0)
            _cb.setChecked(self.is_checked(name))
            _cb.stateChanged.connect(self.update_selected)
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() | ~Qt.ItemIsEditable) # TODO: not working
            self.setItem(i, 1, item)

            _bounds = self.bounds[name]
            sb_lower = RobustSpinBox(
                default_value=_bounds[0], lower_bound=vrange[0], upper_bound=vrange[1]
            )
            sb_lower.valueChanged.connect(self.update_bounds)
            sb_upper = RobustSpinBox(
                default_value=_bounds[1], lower_bound=vrange[0], upper_bound=vrange[1]
            )
            sb_upper.valueChanged.connect(self.update_bounds)
            self.setCellWidget(i, 2, sb_lower)
            self.setCellWidget(i, 3, sb_upper)
        try:
            for i in range(self.rowCount()):
                print("final items ", self.item(i, 1).text())
        except AttributeError:
            pass

        # Make extra editable row
        item = QTableWidgetItem("Enter new PV here") # TODO make gray-ish color
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.setItem(i+1, 1, item)
        # self.setCellWidget(i+1, 0, QCheckBox())
        # _cb = self.cellWidget(i+1, 0)
        # _cb.setChecked(False)
        # _cb.stateChanged.connect(self.update_selected)



        self.setHorizontalHeaderLabels(["", "Name", "Min", "Max"])
        self.setVerticalHeaderLabels([str(i) for i in range(n)])

        header = self.horizontalHeader()
        # header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setVisible(True)

        self.sig_sel_changed.emit()
        # self.add_new_variable()

    def add_new_variable(self):
        # Check last row for new variable added
        idx = self.rowCount()
        try:
            name = self.item(idx, 1).text()
            print("string ", name)

            # TODO: check if name is valid first
            # _cb = self.cellWidget(idx, 0)
            # _cb.setChecked(True)
            # _cb.stateChanged.connect(self.update_selected)

            self.variables.append(name)
        except AttributeError:
            # No text in cell
            return

    def add_variable(self, name, lb, ub):
        var = {}
        var[name] = [lb, ub]

        self.all_variables.append(var)
        self.bounds[name] = [lb, ub]

    def export_variables(self) -> dict:
        variables_exported = {}
        for var in self.all_variables:
            name = next(iter(var))
            if self.is_checked(name):
                variables_exported[name] = self.bounds[name]

        return variables_exported
