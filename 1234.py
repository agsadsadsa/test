import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QListWidget, QMessageBox, QLabel, QDialog, QListWidgetItem, QSystemTrayIcon, QMenu,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtGui import QIcon, QAction, QPixmap
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QUrl
from PySide6.QtMultimedia import QSoundEffect


class AlarmNotifier(QObject):
    alarm_triggered = Signal(str, str, list)


class AlarmDialog(QDialog):
    def __init__(self, time_str, note, links, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\u23f0 \u5f39\u6846\u63d0\u9192")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: #f3e6ff; font-weight: bold;")
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"\u65f6\u95f4：{time_str}"))

        btn = QPushButton(note or "（无）")
        btn.clicked.connect(lambda: QMessageBox.information(self, "\u5907\u6ce8", f"\u5185\u5bb9：{note or '无'}"))
        layout.addWidget(btn)

        for title, link in links:
            if link:
                link_label = QLabel(f"<b>{title or '（无标题）'}</b>: <a href=\"{link}\">{link}</a>")
                link_label.setTextFormat(Qt.RichText)
                link_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
                link_label.setOpenExternalLinks(True)
                layout.addWidget(link_label)

        ok_btn = QPushButton("\u77e5\u9053\u4e86")
        ok_btn.clicked.connect(self.accept)
        layout.addWidget(ok_btn)
        self.setLayout(layout)
        self.resize(400, 300)


class HistoryDialog(QDialog):
    def __init__(self, db_cursor, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\u5386\u53f2\u8bb0\u5f55")
        self.resize(500, 400)
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["\u65f6\u95f4", "\u5907\u6ce8"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        db_cursor.execute("SELECT time, note FROM alarm_history ORDER BY time DESC")
        records = db_cursor.fetchall()
        self.table.setRowCount(len(records))
        for row, (time_str, note) in enumerate(records):
            self.table.setItem(row, 0, QTableWidgetItem(time_str))
            self.table.setItem(row, 1, QTableWidgetItem(note))

        layout.addWidget(self.table)
        close_btn = QPushButton("\u5173\u95ed")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)


class AlarmApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("\ud83d\udccc \u63d0\u9192\u5de5\u5177")
        self.resize(500, 600)
        self.layout = QVBoxLayout(self)
        self.db = sqlite3.connect("alarms.db")
        self.cursor = self.db.cursor()

        self.init_db()
        self.build_ui()
        self.load_saved_links()
        self.load_alarms()

        self.notifier = AlarmNotifier()
        self.notifier.alarm_triggered.connect(self.show_alarm)

        self.sound = QSoundEffect()
        sound_path = Path("reminder.wav")
        if sound_path.exists():
            self.sound.setSource(QUrl.fromLocalFile(str(sound_path)))
        else:
            print("⚠️ 未找到 sound 文件")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_alarms)
        self.timer.start(1000)

        self.init_tray()

    def init_db(self):
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS alarms (id INTEGER PRIMARY KEY, time TEXT, note TEXT);
            CREATE TABLE IF NOT EXISTS alarm_links (id INTEGER PRIMARY KEY, idx INTEGER, title TEXT, url TEXT);
            CREATE TABLE IF NOT EXISTS alarm_history (id INTEGER PRIMARY KEY, time TEXT, note TEXT);
        ''')
        self.db.commit()

    def build_ui(self):
        now = datetime.now()
        self.year = QLineEdit(str(now.year))
        self.year.setFixedWidth(60)
        self.month = QComboBox(); self.month.addItems([f"{i:02d}" for i in range(1, 13)])
        self.day = QComboBox(); self.day.addItems([f"{i:02d}" for i in range(1, 32)])
        self.hour = QComboBox(); self.hour.addItems([f"{i:02d}" for i in range(24)])
        self.minute = QComboBox(); self.minute.addItems([f"{i:02d}" for i in range(60)])
        self.month.setCurrentIndex(now.month - 1)
        self.day.setCurrentIndex(now.day - 1)
        self.hour.setCurrentIndex(now.hour)
        self.minute.setCurrentIndex(now.minute)

        date_layout = QHBoxLayout()
        for widget, label in zip([self.year, self.month, self.day], ["年", "月", "日"]):
            date_layout.addWidget(widget); date_layout.addWidget(QLabel(label))

        icon_label = QLabel()
        icon_path = Path("clock_icon.png")
        if icon_path.exists():
            icon_label.setPixmap(QPixmap(str(icon_path)).scaled(32, 32, Qt.KeepAspectRatio))
        date_layout.addWidget(icon_label)

        self.layout.addLayout(date_layout)

        time_layout = QHBoxLayout()
        for widget, label in zip([self.hour, self.minute], ["时", "分"]):
            time_layout.addWidget(widget); time_layout.addWidget(QLabel(label))
        self.layout.addLayout(time_layout)

        self.noteBox = QComboBox()
        self.noteBox.addItems(["下面的备注内容可以在历史记录里面查询，可以不填。"])
        self.noteBox.setCurrentIndex(0)
        self.noteBox.setEnabled(False)

        self.customNote = QLineEdit(); self.customNote.setPlaceholderText("请输入备注（可留空）")

        self.link_inputs = []
        for _ in range(5):
            title_input = QLineEdit(); title_input.setPlaceholderText("链接标题"); title_input.setFixedWidth(120)
            link_input = QLineEdit(); link_input.setPlaceholderText("链接地址")
            layout = QHBoxLayout()
            layout.addWidget(title_input)
            layout.addWidget(link_input)
            self.layout.addLayout(layout)
            self.link_inputs.append((title_input, link_input))

        self.btn_add = QPushButton("添加提醒"); self.btn_add.clicked.connect(self.add_alarm)
        self.btn_history = QPushButton("查看历史记录"); self.btn_history.clicked.connect(self.show_history)

        self.layout.addWidget(self.noteBox)
        self.layout.addWidget(self.customNote)
        self.layout.addWidget(self.btn_add)
        self.layout.addWidget(self.btn_history)

        self.alarmList = QListWidget(); self.layout.addWidget(self.alarmList)

    def add_alarm(self):
        try:
            dt = datetime(
                int(self.year.text()),
                int(self.month.currentText()),
                int(self.day.currentText()),
                int(self.hour.currentText()),
                int(self.minute.currentText())
            )
        except ValueError:
            QMessageBox.warning(self, "错误", "无效的日期/时间")
            return

        note = self.customNote.text().strip()
        self.cursor.execute("INSERT INTO alarms (time, note) VALUES (?, ?)", (dt.strftime("%Y-%m-%d %H:%M:%S"), note))
        self.db.commit()
        self.save_links()
        self.load_alarms()

    def save_links(self):
        self.cursor.execute("DELETE FROM alarm_links")
        for idx, (title_input, link_input) in enumerate(self.link_inputs):
            title, url = title_input.text().strip(), link_input.text().strip()
            if url:
                self.cursor.execute("INSERT INTO alarm_links (idx, title, url) VALUES (?, ?, ?)", (idx, title, url))
        self.db.commit()

    def load_saved_links(self):
        self.cursor.execute("SELECT idx, title, url FROM alarm_links ORDER BY idx")
        for idx, title, url in self.cursor.fetchall():
            if idx < len(self.link_inputs):
                self.link_inputs[idx][0].setText(title)
                self.link_inputs[idx][1].setText(url)

    def load_alarms(self):
        self.alarmList.clear()
        self.cursor.execute("SELECT id, time, note FROM alarms ORDER BY time")
        for alarm_id, time_str, note in self.cursor.fetchall():
            self.add_alarm_item(alarm_id, time_str, note)

    def add_alarm_item(self, alarm_id, time_str, note):
        widget = QWidget()
        layout = QHBoxLayout()
        layout.addWidget(QLabel(f"{time_str} | {note}"))
        btn = QPushButton("删除"); btn.setFixedWidth(60)
        btn.clicked.connect(lambda _, aid=alarm_id: self.delete_alarm(aid))
        layout.addWidget(btn)
        layout.setContentsMargins(0, 0, 0, 0)
        widget.setLayout(layout)

        item = QListWidgetItem(self.alarmList)
        item.setSizeHint(widget.sizeHint())
        self.alarmList.addItem(item)
        self.alarmList.setItemWidget(item, widget)

    def delete_alarm(self, alarm_id):
        self.cursor.execute("SELECT time, note FROM alarms WHERE id = ?", (alarm_id,))
        row = self.cursor.fetchone()
        if row:
            self.cursor.execute("INSERT INTO alarm_history (time, note) VALUES (?, ?)", row)
        self.cursor.execute("DELETE FROM alarms WHERE id = ?", (alarm_id,))
        self.db.commit()
        self.load_alarms()

    def check_alarms(self):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cursor.execute("SELECT id, time, note FROM alarms WHERE time <= ?", (now,))
        due = self.cursor.fetchall()
        if not due:
            return
        for alarm_id, time_str, note in due:
            links = [(title.text(), link.text()) for title, link in self.link_inputs if link.text()]
            self.notifier.alarm_triggered.emit(time_str, note, links)
            self.cursor.execute("INSERT INTO alarm_history (time, note) VALUES (?, ?)", (time_str, note))
            self.cursor.execute("DELETE FROM alarms WHERE id = ?", (alarm_id,))
        self.db.commit()
        self.load_alarms()

    def show_alarm(self, time_str, note, links):
        if self.sound.isLoaded():
            self.sound.play()
        else:
            QApplication.beep()
        self.dialog = AlarmDialog(time_str, note, links, self)
        self.dialog.exec()

    def show_history(self):
        dlg = HistoryDialog(self.cursor, self)
        dlg.exec()

    def init_tray(self):
        icon_path = Path("alarm.png")
        if not icon_path.exists():
            icon = QIcon.fromTheme("system-run")
        else:
            icon = QIcon(str(icon_path.absolute()))

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("提醒工具运行中")
        menu = QMenu(self)
        show_action = QAction("显示主界面", self)
        show_action.triggered.connect(self.show)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(QApplication.quit)
        menu.addAction(show_action)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def closeEvent(self, event):
        event.ignore()
        self.hide()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = AlarmApp()
    win.show()
    sys.exit(app.exec())
