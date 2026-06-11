import sys
import os
import shutil
import glob
import subprocess
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QByteArray
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QWidget, QGridLayout, QPushButton, 
                             QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QScrollArea, QFrame,
                             QFileDialog, QComboBox, QMessageBox, QCheckBox)
from PyQt6.QtNetwork import QUdpSocket, QHostAddress, QNetworkInterface

class USBWorker_Mac(QThread):
    finished = pyqtSignal(str, bool, str) # coord, success, message
    progress = pyqtSignal(str) # message

    def __init__(self, coord, source_dir, usb_path, append_coord):
        super().__init__()
        self.coord = coord
        self.source_dir = source_dir
        self.usb_path = usb_path # e.g., "/Volumes/UNTITLED"
        self.append_coord = append_coord # boolean

    def run(self):
        try:
            # 1. Mac 환경 USB 드라이브 이름 변경
            self.progress.emit("USB 이름 변경 시도 중...")
            
            rename_success = False
            import time
            for attempt in range(5):
                # 가장 보편적인 diskutil rename 시도
                rename_cmd = ["diskutil", "rename", self.usb_path, self.coord]
                rename_result = subprocess.run(rename_cmd, capture_output=True, text=True)
                
                # 강제로 새로운 마운트 경로가 생겼는지 확인 (returncode가 0이 아니어도 성공하는 Mac의 버그가 있음)
                expected_new_path = f"/Volumes/{self.coord}"
                if os.path.exists(expected_new_path):
                    rename_success = True
                    break
                elif rename_result.returncode == 0:
                    rename_success = True
                    break
                else:
                    self.progress.emit(f"⚠️ 시스템 대기 중... 재시도 ({attempt+1}/5)")
                    time.sleep(2)
            
            if not rename_success:
                # 최후의 수단: UUID나 Device Node를 찾아서 볼륨 포맷에 맞게 직접 라벨링 시도 (FAT32의 경우)
                self.progress.emit("⚠️ 기본 변경 실패. FAT32/exFAT 강제 이름 변경 시도...")
                try:
                    # 마운트 포인트(/Volumes/UNTITLED)를 통해 디바이스 노드(/dev/diskXsY) 찾기
                    info_cmd = ["diskutil", "info", "-plist", self.usb_path]
                    info_result = subprocess.run(info_cmd, capture_output=True, text=True)
                    
                    if "DeviceIdentifier" in info_result.stdout:
                        import plistlib
                        plist_data = plistlib.loads(info_result.stdout.encode('utf-8'))
                        dev_node = "/dev/" + plist_data.get("DeviceIdentifier", "")
                        
                        if dev_node != "/dev/":
                            # 디스크를 잠시 마운트 해제
                            subprocess.run(["diskutil", "unmount", dev_node], capture_output=True)
                            
                            # vfat / msdos (FAT32) 라벨 강제 변경
                            subprocess.run(["fatlabel", dev_node, self.coord], capture_output=True)
                            # exfat 라벨 강제 변경
                            subprocess.run(["exfatlabel", dev_node, self.coord], capture_output=True)
                            
                            # 다시 마운트
                            subprocess.run(["diskutil", "mount", dev_node], capture_output=True)
                            time.sleep(2)  # 마운트 될 때까지 대기
                except Exception as ex:
                    self.progress.emit(f"강제 레벨링 오류: {ex}")

            # 이름이 변경되었으므로, 새로운 마운트 경로 설정 (Mac은 이름이 곧 경로가 됨)
            # 만약 모든게 다 실패했다면 원래 폴더명 유지
            new_usb_path = f"/Volumes/{self.coord}"
            
            # 간혹 마운트 포인트가 바로 갱신되지 않을 수 있으므로, 경로가 존재하는지 대기/확인하는 로직이 필요할 수 있습니다.
            import time
            max_retries = 10
            for _ in range(max_retries):
                if os.path.exists(new_usb_path):
                    break
                time.sleep(0.5)
            
            if not os.path.exists(new_usb_path):
                # 변경된 이름으로 접근이 안되면 원래 경로 유지 (보통 이런경우 이름변경이 실패한 것임)
                new_usb_path = self.usb_path

            usb_target_dir = os.path.join(new_usb_path, "Lightshow")
            coord_source_dir = os.path.join(self.source_dir, self.coord)

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

            # 5. USB 안전 제거 (Mac diskutil)
            self.progress.emit("USB 안전 제거 중...")
            eject_cmd = ["diskutil", "eject", new_usb_path]
            subprocess.run(eject_cmd, capture_output=True)

            self.finished.emit(self.coord, True, f"{self.coord} 작업 완료 및 안전 제거됨")

        except Exception as e:
            self.finished.emit(self.coord, False, f"오류 발생: {str(e)}")


class USBCopyApp_Mac(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('K-Light Show USB Manager (Mac Ver.)')
        self.setStyleSheet("background-color: #1e1e1e; color: white;") 
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10) 
        main_layout.setSpacing(5)

        # 0. 설정 영역 (소스 폴더 및 USB 드라이브 선택)
        settings_layout = QHBoxLayout()
        
        self.btn_select_source = QPushButton("소스 폴더 선택")
        self.btn_select_source.setFixedHeight(30)
        self.btn_select_source.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 3px;")
        self.btn_select_source.clicked.connect(self.select_source_folder)
        
        self.lbl_source_path = QLabel("선택된 폴더 없음")
        self.lbl_source_path.setStyleSheet("color: #aaa;")
        
        self.lbl_usb = QLabel("USB 드라이브:")
        self.combo_usb = QComboBox()
        self.combo_usb.setFixedHeight(30)
        self.combo_usb.setMinimumWidth(150)
        
        self.btn_refresh_usb = QPushButton("새로고침")
        self.btn_refresh_usb.setFixedHeight(30)
        self.btn_refresh_usb.setStyleSheet("background-color: #2196F3; color: white; border-radius: 3px;")
        self.btn_refresh_usb.clicked.connect(self.refresh_usb_drives)
        
        settings_layout.addWidget(self.btn_select_source)
        settings_layout.addWidget(self.lbl_source_path)
        settings_layout.addStretch(1) 
        settings_layout.addWidget(self.lbl_usb)
        settings_layout.addWidget(self.combo_usb)
        settings_layout.addWidget(self.btn_refresh_usb)
        
        main_layout.addLayout(settings_layout)

        # 1. 상단 입력창 영역
        input_container = QVBoxLayout()
        self.label = QLabel('좌표 입력 (예: a4, A04) 후 엔터:')
        self.label.setFont(QFont("ActDmg", 12, QFont.Weight.Bold)) # Mac에 있을만한 폰트, 혹은 기본 폰트 사용
        
        self.input_field = QLineEdit()
        self.input_field.setFixedHeight(40)
        self.input_field.setFont(QFont("ActDmg", 14))
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
        self.grid_layout.setSpacing(2) 

        self.buttons = {}
        rows = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']
        btn_font = QFont("Arial", 11) 

        for r_idx, row_name in enumerate(rows):
            for col in range(4, 64): 
                coord = f"{row_name}{col:02d}"
                btn = QPushButton(coord)
                btn.setFixedSize(45, 30) 
                btn.setFont(btn_font)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: white; 
                        color: black; 
                        border: 1px solid #999;
                        border-radius: 3px;
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
        
        self.source_dir = "" 
        self.refresh_usb_drives() 
        
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
        
        # Mac 환경에서 /Volumes/ 디렉토리 확인
        volumes_dir = "/Volumes"
        if os.path.exists(volumes_dir):
            for item in os.listdir(volumes_dir):
                # 보통 시스템 드라이브 (Macintosh HD)나 복구 파티션 등은 제외해야 합니다.
                # 필요하다면 아래 리스트에 본인 맥의 메인 드라이브 이름 추가
                ignore_list = ["Macintosh HD", "Recovery", "VM", "com.apple.TimeMachine.localsnapshots"]
                if item not in ignore_list and not item.startswith("."):
                    path = os.path.join(volumes_dir, item)
                    if os.path.isdir(path):
                        self.combo_usb.addItem(f"USB: {item}", path)
                        
        if self.combo_usb.count() == 0:
            self.combo_usb.addItem("USB 없음", "")

    def process_coordinate(self, coord):
        coord = coord.upper()
        if coord in self.buttons:
            if not self.source_dir:
                QMessageBox.warning(self, "오류", "먼저 소스 폴더를 선택해주세요.")
                return
            
            usb_path = self.combo_usb.currentData()
            if not usb_path:
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

            self.buttons[coord].setEnabled(False)
            self.btn_select_source.setEnabled(False)
            self.btn_refresh_usb.setEnabled(False)
            self.combo_usb.setEnabled(False)

            self.buttons[coord].setStyleSheet("background-color: #f1c40f; color: black; font-weight: bold;")
            self.label.setText(f"🚀 {coord} 복사 시작... 잠시만 기다려주세요.")
            
            self.worker = USBWorker_Mac(coord, self.source_dir, usb_path, self.cb_append_coord.isChecked())
            self.worker.progress.connect(lambda msg: self.label.setText(f"진행 중: {msg}"))
            self.worker.finished.connect(self.on_worker_finished)
            self.worker.start()
            
        else:
            self.label.setText(f"❌ 잘못된 좌표: {coord}")

    def on_worker_finished(self, coord, success, message):
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
    ex = USBCopyApp_Mac()
    sys.exit(app.exec())
