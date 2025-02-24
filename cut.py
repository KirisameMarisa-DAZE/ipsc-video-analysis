#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jan 13 12:16:50 2025

@author:
    GitHub@KirisameMarisa-DAZE (master.spark.kirisame.marisa.daze@gmail.com)
    All rights reserved. © 2021~2025
"""

import sys
import os
import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QRect, QPoint, QSize
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QPushButton,
                             QFileDialog, QVBoxLayout, QWidget, QProgressBar, QSlider)

class VideoProcessor(QThread):
    progress_updated = pyqtSignal(int)
    finished = pyqtSignal(str)

    def __init__(self, input_path, output_dir, roi_rect):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.roi_rect = roi_rect
        self.cancel_flag = False

    def run(self):
        try:
            print("Processing started")  # 调试输出
            cap = cv2.VideoCapture(self.input_path)
            if not cap.isOpened():
                raise ValueError("无法打开输入视频")

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                raise ValueError("视频帧数为0")
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps == 0:
                fps = 25
            base_name = os.path.splitext(os.path.basename(self.input_path))[0]
            output_path = os.path.join(self.output_dir, f"{base_name}_cropped.mp4")

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps,
                                  (self.roi_rect.width(), self.roi_rect.height()))

            for frame_num in range(total_frames):
                if self.cancel_flag:
                    break

                ret, frame = cap.read()
                if not ret:
                    print(f"读取帧失败，退出于第 {frame_num} 帧")
                    break

                # 使用ROI参数裁剪视频帧
                x, y, w, h = self.roi_rect.x(), self.roi_rect.y(), self.roi_rect.width(), self.roi_rect.height()
                roi_frame = frame[y:y+h, x:x+w]
                out.write(roi_frame)

                self.progress_updated.emit(int((frame_num+1)/total_frames*100))

            cap.release()
            out.release()
            print("Processing finished")
            self.finished.emit(output_path if not self.cancel_flag else "")

        except Exception as e:
            print(f"Processing error: {str(e)}")
            self.finished.emit(f"错误: {str(e)}")

    def cancel(self):
        self.cancel_flag = True

class VideoLabel(QLabel):
    roi_selected = pyqtSignal(QRect)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setText("拖放视频文件到这里")
        self.setMinimumSize(640, 480)
        self.drag_active = False
        self.start_point = QPoint()
        self.current_roi = QRect()
        self.permanent_roi = QRect()  # 持久保存ROI框
        self.original_size = QSize()
        self.display_rect = QRect()
        self.pen = QPen(Qt.red, 2, Qt.SolidLine)

    def set_video_frame(self, pixmap, original_size):
        self.original_size = original_size
        scaled_pix = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(scaled_pix)

        # 计算显示区域的位置和大小
        pw = scaled_pix.width()
        ph = scaled_pix.height()
        x = (self.width() - pw) // 2
        y = (self.height() - ph) // 2
        self.display_rect = QRect(x, y, pw, ph)

    def mousePressEvent(self, event):
        if self.pixmap() and self.display_rect.contains(event.pos()):
            self.drag_active = True
            adj_pos = event.pos() - self.display_rect.topLeft()
            self.start_point = adj_pos
            self.current_roi = QRect(adj_pos, adj_pos)

    def mouseMoveEvent(self, event):
        if self.drag_active and self.display_rect.contains(event.pos()):
            adj_pos = event.pos() - self.display_rect.topLeft()
            self.current_roi = QRect(
                QPoint(min(self.start_point.x(), adj_pos.x()),
                       min(self.start_point.y(), adj_pos.y())),
                QPoint(max(self.start_point.x(), adj_pos.x()),
                       max(self.start_point.y(), adj_pos.y()))
            )
            self.update()

    def mouseReleaseEvent(self, event):
        if self.drag_active:
            self.drag_active = False
            self.permanent_roi = self.current_roi  # 保存持久ROI

            scale_x = self.original_size.width() / self.display_rect.width()
            scale_y = self.original_size.height() / self.display_rect.height()

            roi = QRect(
                int(self.current_roi.x() * scale_x),
                int(self.current_roi.y() * scale_y),
                int(self.current_roi.width() * scale_x),
                int(self.current_roi.height() * scale_y)
            )
            self.roi_selected.emit(roi)
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(self.pen)
        # 正在绘制时显示当前ROI，否则显示持久ROI
        if self.drag_active and not self.current_roi.isNull():
            adjusted_rect = self.current_roi.translated(self.display_rect.topLeft())
            painter.drawRect(adjusted_rect)
        elif not self.permanent_roi.isNull():
            adjusted_rect = self.permanent_roi.translated(self.display_rect.topLeft())
            painter.drawRect(adjusted_rect)

    def resizeEvent(self, event):
        if self.pixmap():
            scaled_pix = self.pixmap().scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.setPixmap(scaled_pix)
            pw = scaled_pix.width()
            ph = scaled_pix.height()
            x = (self.width() - pw) // 2
            y = (self.height() - ph) // 2
            self.display_rect = QRect(x, y, pw, ph)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频ROI裁剪工具")
        self.setAcceptDrops(True)
        self.video_path = ""
        self.roi_rect = QRect()
        self.processing_thread = None
        self.cap = None  # 用于视频预览
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

        # UI组件
        self.video_label = VideoLabel()
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        self.status_label = QLabel("就绪")
        self.select_dir_btn = QPushButton("选择输出目录")
        self.process_btn = QPushButton("开始处理")
        self.process_btn.setEnabled(False)
        self.process_btn.clicked.connect(self.start_processing)

        # 播放/暂停按钮和视频进度条
        self.play_pause_btn = QPushButton("播放")
        self.play_pause_btn.setEnabled(False)
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.sliderReleased.connect(self.slider_released)

        # 布局
        control_layout = QVBoxLayout()
        control_layout.addWidget(self.select_dir_btn)
        control_layout.addWidget(self.process_btn)
        control_layout.addWidget(self.play_pause_btn)
        control_layout.addWidget(self.slider)
        control_layout.addWidget(self.status_label)
        control_layout.addWidget(self.progress_bar)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.video_label)
        main_layout.addLayout(control_layout)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        # 信号连接
        self.select_dir_btn.clicked.connect(self.select_output_dir)
        self.video_label.roi_selected.connect(self.update_roi)
        self.output_dir = os.path.expanduser("~/Desktop")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                self.load_video(file_path)
                break

    def load_video(self, path):
        self.video_path = path
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            self.status_label.setText("无法打开视频文件")
            return

        fps = self.cap.get(cv2.CAP_PROP_FPS)
        if fps == 0:
            fps = 25
        total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        interval = int(1000 / fps)
        self.timer.setInterval(interval)
        self.slider.setMinimum(0)
        self.slider.setMaximum(total_frames - 1)

        ret, frame = self.cap.read()
        if not ret:
            self.status_label.setText("无法读取视频帧")
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        self.video_label.set_video_frame(pixmap, QSize(w, h))

        # 重置视频到第一帧
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.play_pause_btn.setEnabled(True)
        self.slider.setEnabled(True)
        self.process_btn.setEnabled(True)
        self.status_label.setText(f"已加载视频：{os.path.basename(path)}")

    def toggle_play_pause(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play_pause_btn.setText("播放")
        else:
            self.timer.start()
            self.play_pause_btn.setText("暂停")

    def update_frame(self):
        if self.cap:
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(q_img)
                self.video_label.set_video_frame(pixmap, QSize(w, h))
                current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                self.slider.setValue(current_frame)
            else:
                self.timer.stop()

    def slider_released(self):
        if self.cap:
            frame_number = self.slider.value()
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            self.update_frame()

    def select_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir)
        if dir_path:
            self.output_dir = dir_path
            self.status_label.setText(f"输出目录：{dir_path}")

    def update_roi(self, roi):
        self.roi_rect = roi
        self.status_label.setText(
            f"已选择ROI区域：X={roi.x()}, Y={roi.y()}, {roi.width()}x{roi.height()}")

    def start_processing(self):
        print("start_processing triggered")  # 调试输出，确认按钮点击
        if not self.roi_rect.isValid():
            self.status_label.setText("请先选择有效的ROI区域")
            return

        # 停止预览并释放资源
        if self.timer.isActive():
            self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        self.play_pause_btn.setEnabled(False)
        self.slider.setEnabled(False)

        self.processing_thread = VideoProcessor(self.video_path, self.output_dir, self.roi_rect)
        self.processing_thread.progress_updated.connect(self.update_progress)
        self.processing_thread.finished.connect(self.processing_finished)

        self.process_btn.setEnabled(False)
        self.progress_bar.show()
        self.processing_thread.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def processing_finished(self, result):
        self.progress_bar.hide()
        self.process_btn.setEnabled(True)
        if result.startswith("错误:"):
            self.status_label.setText(result)
        elif result:
            self.status_label.setText(f"处理完成！保存至：{result}")
        else:
            self.status_label.setText("处理已取消")

    def closeEvent(self, event):
        if self.processing_thread and self.processing_thread.isRunning():
            self.processing_thread.cancel()
            self.processing_thread.wait()
        if self.cap:
            self.cap.release()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
