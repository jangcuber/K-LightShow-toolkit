import sys
import os
import shutil
import glob
import subprocess
import ctypes
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QByteArray
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QWidget, QGridLayout, QPushButton, 
                             QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QScrollArea, QFrame,
                             QFileDialog, QComboBox, QMessageBox, QCheckBox)
from PyQt6.QtNetwork import QUdpSocket, QHostAddress, QNetworkInterface

class USBWorker(QThread):
    finished = pyqtSignal(str, bool, str) # coord, success, message
    progress = pyqtSignal(str) # message

    def __init__(self, coord, source_dir, usb_drive, append_coord):
        super().__init__()
        self.coord = coord
        self.source_dir = source_dir
        self.usb_drive = usb_drive # e.g., "E"
        self.append_coord = append_coord # boolean

    def run(self):
        try:
            drive_path = f"{self.usb_drive}:\\"
            usb_target_dir = os.path.join(drive_path, "Lightshow")
            coord_source_dir = os.path.join(self.source_dir, self.coord)

            # 1. USB 드라이브 이름 변경 (Volume Label)
            # ctypes.windll.kernel32.SetVolumeLabelW(DrivePath, Label)
            success = ctypes.windll.kernel32.SetVolumeLabelW(drive_path, self.coord)
            if not success:
                self.progress.emit("⚠️ 드라이브 이름 변경 실패 (계속 진행)")

            # 2. 대상 폴더 (Lightshow) 생성
            os.makedirs(usb_target_dir, exist_ok=True)
            self.progress.emit("폴더 생성 완료")

            # 3. 소스 루트의 모든 .mp3 파일 복사 (옵션에 따라 이름 뒤에 좌표 추가)
            mp3_files = glob.glob(os.path.join(self.source_dir, "*.mp3"))
            for mp3 in mp3_files:
                if self.append_coord:
                    base_name, ext = os.path.splitext(os.path.basename(mp3))
                    new_name = f"{base_name}_{self.coord}{ext}"
                    dest_path = os.path.join(usb_target_dir, new_name)
                    shutil.copyfile(mp3, dest_path)
                else:
                    shutil.copy2(mp3, usb_target_dir)
            self.progress.emit("MP3 파일 복사 완료")

            # 4. 좌표 폴더 내의 파일들 복사 (.fseq 파일만, 옵션에 따라 이름 뒤에 좌표 추가)
            if os.path.exists(coord_source_dir):
                fseq_files = glob.glob(os.path.join(coord_source_dir, "*.fseq"))
                if fseq_files:
                    for fseq in fseq_files:
                        if self.append_coord:
                            base_name, ext = os.path.splitext(os.path.basename(fseq))
                            new_name = f"{base_name}_{self.coord}{ext}"
                            dest_path = os.path.join(usb_target_dir, new_name)
                            shutil.copyfile(fseq, dest_path)
                        else:
                            shutil.copy2(fseq, usb_target_dir)
                    self.progress.emit("좌표 파일(.fseq) 복사 완료")
                else:
                    self.progress.emit(f"⚠️ 경고: '{self.coord}' 폴더에 .fseq 파일이 없습니다.")
            else:
                self.progress.emit(f"⚠️ 경고: 소스에 '{self.coord}' 폴더가 없습니다.")

            # 5. USB 안전 제거 (PowerShell)
            self.progress.emit("USB 안전 제거 중...")
            ps_script = f"$drive=New-Object -comObject Shell.Application; $drive.Namespace(17).ParseName('{self.usb_drive}:').InvokeVerb('Eject')"
            subprocess.run(["powershell", "-command", ps_script], creationflags=subprocess.CREATE_NO_WINDOW)

            self.finished.emit(self.coord, True, f"{self.coord} 작업 완료 및 안전 제거됨")

        except Exception as e:
            self.finished.emit(self.coord, False, f"오류 발생: {str(e)}")
class USBCopyApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('K-Light Show USB Manager')
        self.setStyleSheet("background-color: #1e1e1e; color: white;") # 다크모드 스타일
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10) # 외곽 여백 최소화
        main_layout.setSpacing(5)

        # 0. 설정 영역 (소스 폴더 및 USB 드라이브 선택)
        settings_layout = QHBoxLayout()
        
        # 소스 폴더 선택
        self.btn_select_source = QPushButton("소스 폴더 선택")
        self.btn_select_source.setFixedHeight(30)
        self.btn_select_source.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 3px;")
        self.btn_select_source.clicked.connect(self.select_source_folder)
        
        self.lbl_source_path = QLabel("선택된 폴더 없음")
        self.lbl_source_path.setStyleSheet("color: #aaa;")
        
        # USB 드라이브 선택
        self.lbl_usb = QLabel("USB 드라이브:")
        self.combo_usb = QComboBox()
        self.combo_usb.setFixedHeight(30)
        self.combo_usb.setMinimumWidth(100)
        
        self.btn_refresh_usb = QPushButton("새로고침")
        self.btn_refresh_usb.setFixedHeight(30)
        self.btn_refresh_usb.setStyleSheet("background-color: #2196F3; color: white; border-radius: 3px;")
        self.btn_refresh_usb.clicked.connect(self.refresh_usb_drives)
        
        settings_layout.addWidget(self.btn_select_source)
        settings_layout.addWidget(self.lbl_source_path)
        settings_layout.addStretch(1) # 중앙 여백
        settings_layout.addWidget(self.lbl_usb)
        settings_layout.addWidget(self.combo_usb)
        settings_layout.addWidget(self.btn_refresh_usb)
        
        main_layout.addLayout(settings_layout)

        # 1. 상단 입력창 영역 (고정 높이로 여백 방지)
        input_container = QVBoxLayout()
        self.label = QLabel('좌표 입력 (예: a4, A04) 후 엔터:')
        self.label.setFont(QFont("Pretendard", 12, QFont.Weight.Bold))
        
        self.input_field = QLineEdit()
        self.input_field.setFixedHeight(40)
        self.input_field.setFont(QFont("Pretendard", 14))
        self.input_field.setStyleSheet("background-color: #333; border: 1px solid #555; padding-left: 10px;")
        self.input_field.returnPressed.connect(self.handle_keyboard_input)
        
        input_container.addWidget(self.label)
        
        # 파일명 뒤에 좌표 추가 옵션 체크박스
        self.cb_append_coord = QCheckBox("복사 시 파일 이름 뒤에 좌표 붙이기 (예: BTS_A04.mp3)")
        self.cb_append_coord.setChecked(True) # 기본값: 체크됨
        self.cb_append_coord.setStyleSheet("color: #ccc; margin-bottom: 5px;")
        input_container.addWidget(self.cb_append_coord)
        
        input_container.addWidget(self.input_field)
        main_layout.addLayout(input_container)

        # 2. 스크롤 가능한 버튼 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        container = QWidget()
        self.grid_layout = QGridLayout(container)
        self.grid_layout.setSpacing(2) # 버튼 사이 간격

        self.buttons = {}
        rows = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']
        
        # 버튼 폰트 설정
        btn_font = QFont("Arial", 8) 

        for r_idx, row_name in enumerate(rows):
            for col in range(4, 64): # 4번부터 63번까지
                coord = f"{row_name}{col:02d}"
                btn = QPushButton(coord)
                
                # 버튼 크기와 폰트 최적화
                btn.setFixedSize(40, 25) 
                btn.setFont(btn_font)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                
                # 초기 스타일 (검은 배경에 흰 글씨)
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: white; 
                        color: black; 
                        border: 1px solid #999;
                        border-radius: 2px;
                    }
                    QPushButton:hover {
                        background-color: #eee;
                    }
                """)
                
                btn.clicked.connect(lambda checked, c=coord: self.process_coordinate(c))
                self.grid_layout.addWidget(btn, r_idx, col-4)
                self.buttons[coord] = btn

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        self.setLayout(main_layout)
        
        self.source_dir = "" # 선택된 소스 폴더 경로 저장
        self.refresh_usb_drives() # 초기 USB 드라이브 목록 로드
        
        # --- UDP Sync 설정 ---
        self.udp_port = 45454
        self.udp_socket = QUdpSocket(self)
        self.udp_socket.bind(QHostAddress.SpecialAddress.AnyIPv4, self.udp_port, QUdpSocket.BindFlag.ShareAddress)
        self.udp_socket.readyRead.connect(self.receive_sync_data)
        
        self.showMaximized()

    def receive_sync_data(self):
        while self.udp_socket.hasPendingDatagrams():
            datagram, host, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            message = datagram.decode('utf-8')
            
            if message.startswith("SYNC_DONE:"):
                coord = message.split(":")[1]
                if coord in self.buttons:
                    current_style = self.buttons[coord].styleSheet()
                    # 본인이 작업한게 아니라 남이 한거라면 초록색으로 변경
                    if "background-color: #2ecc71" not in current_style:
                        self.buttons[coord].setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold;")
                        self.buttons[coord].setText(f"{coord}\n(동기화됨)")
                        self.label.setText(f"🔄 다른 PC에서 {coord} 복사를 완료했습니다.")

    def select_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "소스 폴더(mp3와 좌표 폴더가 있는 곳) 선택")
        if folder:
            self.source_dir = folder
            self.lbl_source_path.setText(folder)

    def refresh_usb_drives(self):
        self.combo_usb.clear()
        import ctypes
        
        # 드라이브 문자 확인 (D~Z)
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(3, 26): # D (3) to Z (25)
            if bitmask & (1 << i):
                drive_letter = chr(65 + i)
                drive_path = f"{drive_letter}:\\"
                
                # GetDriveType: 2 = DRIVE_REMOVABLE
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
                if drive_type == 2:
                    self.combo_usb.addItem(f"{drive_letter}: (이동식 디스크)", drive_letter)
                    
        if self.combo_usb.count() == 0:
            self.combo_usb.addItem("USB 없음", "")

    def process_coordinate(self, coord):
        coord = coord.upper()
        if coord in self.buttons:
            # 설정 검증
            if not self.source_dir:
                QMessageBox.warning(self, "오류", "먼저 소스 폴더를 선택해주세요.")
                return
            
            drive_letter = self.combo_usb.currentData()
            if not drive_letter:
                QMessageBox.warning(self, "오류", "복사할 USB 드라이브를 선택해주세요.")
                return

            current_style = self.buttons[coord].styleSheet()
            if "background-color: #2ecc71" in current_style:
                # 이미 완료된 경우 재시도 여부 확인
                reply = QMessageBox.question(
                    self, 
                    "다시 시작", 
                    f"⚠️ {coord}는 이미 완료된 좌표입니다!\n다시 복사 작업을 진행하시겠습니까?", 
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.No:
                    return
                # Yes를 누른 경우 아래 진행 로직으로 넘어감

            # UI 비활성화 (작업 중 중복 클릭 방지)
            self.buttons[coord].setEnabled(False)
            self.btn_select_source.setEnabled(False)
            self.btn_refresh_usb.setEnabled(False)
            self.combo_usb.setEnabled(False)

            # 상태 변경: 노란색(진행 중)
            self.buttons[coord].setStyleSheet("background-color: #f1c40f; color: black; font-weight: bold;")
            self.label.setText(f"🚀 {coord} 복사 시작... 잠시만 기다려주세요.")
            
            # 스레드 시작
            self.worker = USBWorker(coord, self.source_dir, drive_letter, self.cb_append_coord.isChecked())
            self.worker.progress.connect(lambda msg: self.label.setText(f"진행 중: {msg}"))
            self.worker.finished.connect(self.on_worker_finished)
            self.worker.start()
            
        else:
            self.label.setText(f"❌ 잘못된 좌표: {coord}")

    def on_worker_finished(self, coord, success, message):
        # UI 활성화
        self.btn_select_source.setEnabled(True)
        self.btn_refresh_usb.setEnabled(True)
        self.combo_usb.setEnabled(True)
        self.buttons[coord].setEnabled(True)

        if success:
            self.buttons[coord].setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold;")
            self.buttons[coord].setText(coord)
            self.label.setText(f"✅ 성공: {message}")
            
            # 다른 PC들에게 완료 방송(Broadcast) 발송
            sync_msg = f"SYNC_DONE:{coord}".encode('utf-8')
            msg_bytes = QByteArray(sync_msg)
            
            # 1. 기본 글로벌 브로드캐스트
            self.udp_socket.writeDatagram(msg_bytes, QHostAddress.SpecialAddress.Broadcast, self.udp_port)
            
            # 2. 다중 네트워크/Mac 환경을 위한 개별 인터페이스 브로드캐스트
            for iface in QNetworkInterface.allInterfaces():
                flags = iface.flags()
                if (flags & QNetworkInterface.InterfaceFlag.IsUp) and (flags & QNetworkInterface.InterfaceFlag.CanBroadcast):
                    for entry in iface.addressEntries():
                        bcast = entry.broadcast()
                        if bcast and not bcast.isNull():
                            self.udp_socket.writeDatagram(msg_bytes, bcast, self.udp_port)
            
            QMessageBox.information(self, "완료", f"{coord} 복사가 완료되었습니다.\nUSB를 제거하셔도 됩니다.")
            # 성공 후 USB 목록 갱신 및 초기화
            self.refresh_usb_drives()
        else:
            self.buttons[coord].setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold;")
            self.label.setText(f"❌ 실패: {message}")
            QMessageBox.critical(self, "오류", f"{coord} 복사 중 오류가 발생했습니다.\n{message}")

    def handle_keyboard_input(self):
        raw_text = self.input_field.text().strip().upper()
        if len(raw_text) >= 2:
            row = raw_text[0]
            try:
                num = int(raw_text[1:])
                formatted_coord = f"{row}{num:02d}"
                self.process_coordinate(formatted_coord)
            except ValueError:
                self.label.setText("형식이 올바르지 않습니다 (예: A4)")
        self.input_field.clear()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = USBCopyApp()
    sys.exit(app.exec())