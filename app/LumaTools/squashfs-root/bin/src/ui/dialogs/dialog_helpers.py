from PyQt6.QtWidgets import QDialogButtonBox


def create_standard_buttons(on_accept, on_reject):
    buttons = QDialogButtonBox()
    buttons.addButton(QDialogButtonBox.StandardButton.Ok)
    buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(on_accept)
    buttons.rejected.connect(on_reject)
    return buttons
