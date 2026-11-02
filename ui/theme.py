STYLE = """
QWidget { background: #10131d; color: #e8ebf5; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QStackedWidget { background: #10131d; }
QFrame#card { background: #191e2d; border: 1px solid #2a3146; border-radius: 16px; }
QFrame#card QLabel, QFrame#card QCheckBox { background: transparent; }
QLabel#eyebrow { color: #92a3ff; font-size: 11px; font-weight: 700; }
QLabel#title { font-size: 29px; font-weight: 700; }
QLabel#heading { font-size: 20px; font-weight: 650; background: transparent; }
QLabel#muted { color: #9ca8c2; background: transparent; }
QLabel#metric { font-size: 32px; color: #a9b6ff; font-weight: 700; }
QLabel#status { color: #b1bfff; background: #252d49; padding: 7px 12px; border-radius: 12px; }
QLineEdit, QDateEdit, QDoubleSpinBox { background: #111725; border: 1px solid #343e57; border-radius: 8px; padding: 9px; selection-background-color: #5364d8; }
QLineEdit:focus, QDateEdit:focus, QDoubleSpinBox:focus { border-color: #8899ff; }
QPushButton { background: #29334f; border: 1px solid #3a4666; border-radius: 9px; padding: 10px 17px; font-weight: 600; }
QPushButton:hover { background: #354466; border-color: #788bd4; }
QPushButton:pressed { background: #202943; }
QPushButton#primary { background: #6575ef; color: white; border: 1px solid #7b8aff; }
QPushButton#primary:hover { background: #7787ff; }
QPushButton#danger { background: #803c58; border-color: #b15c7f; }
QPushButton#danger:hover { background: #9c466b; }
QPushButton:disabled { background: #202635; color: #67728a; border-color: #2a3246; }
QPushButton#primary:disabled, QPushButton#danger:disabled { background: #202635; color: #67728a; border-color: #2a3246; }
QListWidget, QTableWidget, QPlainTextEdit { background: #111725; border: 1px solid #2a344b; border-radius: 8px; padding: 5px; selection-background-color: #33447c; }
QListWidget::item { padding: 12px 8px; border-radius: 6px; }
QListWidget::item:selected { background: #303f74; color: white; }
QHeaderView::section { background: #20283b; color: #a9b6d2; padding: 8px; border: none; }
QTableWidget::item { padding: 6px; }
QProgressBar { border: none; background: #252e45; border-radius: 5px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #8292ff; border-radius: 5px; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QSplitter::handle { background: #10131d; width: 12px; }
QScrollBar:vertical { background: #161d2b; width: 10px; border-radius: 4px; }
QScrollBar::handle:vertical { background: #3c4865; min-height: 25px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #26314b; border: 1px solid #6172a5; color: white; padding: 5px; }
"""
