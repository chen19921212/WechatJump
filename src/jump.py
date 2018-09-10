#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import math

import cv2
import numpy as np
from PIL import ImageDraw, ImageFont

from adb import PyADB
from model import MachineLearningModel

NULL_POS = np.array([0, 0])


class WechatJump:
    """ 所有的坐标都是 (x, y) 格式的，但是在 opencv 的数组中是 (y, x) 格式的"""
    def __init__(self, device_serial):
        self.adb = PyADB(device_serial)
        self.model = MachineLearningModel()
        self.model.train_polynomial_regression_model(degree=6)
        self.resolution = np.array(self.adb.get_resolution())
        self.start_btn = self.resolution * np.array([0.5, 0.67])
        self.again_btn = self.resolution * np.array([0.62, 0.79])
        self.top_chart_back_btn = self.resolution * np.array([0.07, 0.87])
        self.piece = cv2.imread("../assests/piece.png", cv2.IMREAD_GRAYSCALE)
        self.piece_delta = np.array([38, 186])
        self.center_black = cv2.imread("../assests/center_black.png", cv2.IMREAD_GRAYSCALE)
        self.center_white = cv2.imread("../assests/center_white.png", cv2.IMREAD_GRAYSCALE)
        self.center_delta = np.array([19, 15])

    def start_game(self):
        """点击开始游戏按钮"""
        self.adb.short_tap(self.start_btn)

    def another_game(self):
        """点击再玩一局按钮"""
        self.adb.short_tap(self.top_chart_back_btn)
        self.adb.short_tap(self.again_btn)

    @staticmethod
    def match_template(img, tpl, threshold=0.8, debug=False):
        """opencv模版匹配，图像要先处理为灰度图像"""
        result = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, maxVal, _, maxLoc = cv2.minMaxLoc(result)
        return np.array(maxLoc) if maxVal >= threshold else NULL_POS

    @staticmethod
    def calc_distance(a, b, jump_right):
        """在倾斜角 30 度方向上投影的距离。"""
        if jump_right:
            distance = abs((a[1]-b[1]) - (a[0]-b[0]) / math.sqrt(3))
        else:
            distance = abs((a[1]-b[1]) + (a[0]-b[0]) / math.sqrt(3))

        # 欧式距离
        # distance = np.sqrt(np.sum(np.square(a-b)))

        return distance

    def match_center_tpl(self, img):
        """使用模版匹配寻找小白点，小白点在跳中棋盘中心后出现。"""
        black_match_pos = self.match_template(img, self.center_black)
        white_match_pos = self.match_template(img, self.center_white)
        if black_match_pos.any():
            self.target_pos = black_match_pos + self.center_delta
            self.on_center = True
        elif white_match_pos.any():
            self.target_pos = white_match_pos + self.center_delta
            self.on_center = True
        else:
            self.target_pos = NULL_POS
            self.on_center = False
        return self.target_pos

    def init_attrs(self):
        """初始化变量"""
        self.last_distance = self.distance if hasattr(self, "distance") else None
        self.distance = None
        self.last_duration = self.duration if hasattr(self, "duration") else None
        self.duration = None
        self.last_jump_right = self.jump_right if hasattr(self, "jump_right") else None
        self.jump_right = None
        self.last_target_img = self.target_img if hasattr(self, "target_img") else NULL_POS
        self.target_img = NULL_POS
        self.piece_pos = NULL_POS
        self.target_pos = NULL_POS
        self.start_pos = NULL_POS
        self.top_pos = NULL_POS
        self.last_actual_distance = None
        self.on_center = None

    def get_piece_pos(self, img):
        """
        使用模版匹配寻找棋子位置。

        必须使用当前分辨率下的棋子图片作为模版，否则模版与当前棋子大小不一致时匹配结果很差。
        """
        match_pos = self.match_template(img, self.piece, 0.7)
        if not match_pos.any():
            raise ValueError("无法定位棋子")
        self.piece_pos =  match_pos + self.piece_delta

        # 计算跳跃方向
        self.jump_right = self.piece_pos[0] < self.resolution[0] // 2

        return self.piece_pos

    def get_target_pos(self, img):
        """
        获取目标棋盘中心点坐标。

        1. 使用模版匹配寻找小白点。
        2. 使用 Canny 边缘检测寻找目标棋盘上顶点坐标，边缘检测：灰度图像 -> 高斯模糊
         -> Canny边缘检测。
        3. 如果模版匹配没有找到小白点，则寻找下顶点并计算目标

        """
        self.match_center_tpl(img)

        # 高斯模糊后，处理成Canny边缘图像
        img = cv2.GaussianBlur(img, (5, 5), 0)
        img = cv2.Canny(img, 1, 10)

        # 有时棋子高度高于落脚点，为去掉棋子对判断的影响，抹掉棋子的边缘，将像素值置为0
        # 这里数组的索引是 img[y1:y2, x1:x2] 的形式
        img[
            self.piece_pos[1]-self.piece_delta[1]-2: self.piece_pos[1]+2,
            self.piece_pos[0]-self.piece_delta[0]-2: self.piece_pos[0]+self.piece_delta[0]+2,
        ] = 0

        # 为避免屏幕上半部分分数和小程序按钮的影响
        # 从 1/3*H 的位置开始向下逐行遍历到 2/3*H，寻找目标棋盘的上顶点
        y_start = self.resolution[1] // 3
        y_stop = self.resolution[1] // 3 * 2

        # 上顶点的 y 坐标
        for y in range(y_start, y_stop):
            if img[y].any():
                y_top = y
                break
        else:
            raise ValueError("无法定位目标棋盘上顶点")

        # 上顶点的 x 坐标，也是中心点的 x 坐标
        x = int(round(np.mean(np.nonzero(img[y_top]))))
        self.top_pos = np.array([x, y_top])

        # 如果模版匹配已经找到了目标棋盘中心点，就不需要再继续寻找下顶点继而确定中心点
        if self.target_pos.any():
            return self.target_pos

        # 下顶点的 y 坐标，+40是为了消除多圆环类棋盘的干扰
        for y in range(y_top+40, y_stop):
            if img[y, x] or img[y, x-1]:
                y_bottom = y
                break
        else:
            raise ValueError("无法定位目标棋盘下顶点")

        # 由上下顶点 y 坐标获得中心点 y 坐标
        self.target_pos = np.array([x, (y_top + y_bottom) // 2])
        return self.target_pos

    def get_start_pos(self, img):
        """通过模版匹配，获取起始棋盘中心坐标"""
        if self.last_target_img.any():
            match_pos = self.match_template(img, self.last_target_img, 0.7)
            if match_pos.any():
                shape = self.last_target_img.shape
                start_pos = match_pos + np.array([shape[1]//2, 0])
                # 如果坐标与当前棋子坐标差距过大，则认为有问题，丢弃
                if (np.abs(start_pos-self.piece_pos) < np.array([100, 100])).all():
                    self.start_pos = start_pos
        return self.start_pos

    def review_last_jump(self):
        """评估上次跳跃参数，计算实际跳跃距离。"""
        # 如果这些属性不存在，就无法进行评估
        if self.last_distance \
                and self.last_duration \
                and self.start_pos.any() \
                and self.last_jump_right is not None:
            pass
        else:
            return

        # 计算棋子和起始棋盘中心的偏差距离
        d = self.calc_distance(self.start_pos, self.piece_pos, self.last_jump_right)

        # 计算实际跳跃距离，这里要分情况讨论跳过头和没跳到两种情况讨论
        k = 1 / math.sqrt(3) if self.last_jump_right else -1 / math.sqrt(3)
        # 没跳到，实际距离 = 上次测量距离 - 偏差距离
        if self.piece_pos[1] > k*(self.piece_pos[0]-self.start_pos[0]) + self.start_pos[1]:
            self.last_actual_distance = self.last_distance - d
        # 跳过头，实际距离 = 上次测量距离 + 偏差距离
        elif self.piece_pos[1] < k*(self.piece_pos[0]-self.start_pos[0]) + self.start_pos[1]:
            self.last_actual_distance = self.last_distance + d
        # 刚刚好
        else:
            self.last_actual_distance = self.last_distance

        print(self.last_actual_distance, self.last_duration, self.on_center)

    def get_target_img(self, img):
        """获取当前目标棋盘的图像。"""
        half_height = self.target_pos[1] - self.top_pos[1]
        # 0.57735 是 tan 30 的约数
        half_width = int(round(half_height * math.sqrt(3)))
        self.target_img = img[
            self.target_pos[1]: self.target_pos[1]+half_height+100,
            self.target_pos[0]-half_width: self.target_pos[0]+half_width,
        ]
        return self.target_img

    def jump(self):
        """跳跃，并存储本次目标跳跃距离和按压时间"""
        # 计算棋子和目标棋盘距离
        self.distance = self.calc_distance(self.piece_pos, self.target_pos, self.jump_right)
        # self.duration = int(round(self.distance * k + b))
        self.duration = int(round(self.model.predict(self.distance)))
        self.adb.long_tap(self.resolution // 2, self.duration)

    def mark_img(self, img_rgb):
        draw = ImageDraw.Draw(img_rgb)
        # 棋子中心点
        draw.line(
            (0, self.piece_pos[1], self.resolution[0], self.piece_pos[1]),
            "#ff0000",
        )
        draw.line(
            (self.piece_pos[0], 0, self.piece_pos[0], self.resolution[1]),
            "#ff0000",
        )
        # 目标棋盘中心点
        draw.line(
            (0, self.target_pos[1], self.resolution[0], self.target_pos[1]),
            "#0000ff",
        )
        draw.line(
            (self.target_pos[0], 0, self.target_pos[0], self.resolution[1]),
            "#0000ff",
        )
        # 当前棋盘中心点
        draw.line(
            (0, self.start_pos[1], self.resolution[0], self.start_pos[1]),
            "#000000",
        )
        draw.line(
            (self.start_pos[0], 0, self.start_pos[0], self.resolution[1]),
            "#000000",
        )

        draw.multiline_text(
            (50, 50),
            "\n".join([
                f"上次向右跳跃: {self.last_jump_right}",
                f"上次落点中心: {self.on_center}",
                f"上次跳跃距离: {self.last_distance}",
                f"上次修正距离: {self.last_actual_distance}",
                f"上次按压时间: {self.last_duration}",
            ]),
            fill='#000000',
            font=ImageFont.truetype("../assests/font.ttf", 50)
        )

    def run(self):
        while True:
            # 读取图片
            img_rgb = self.adb.screencap()
            img = cv2.cvtColor(np.asarray(img_rgb), cv2.COLOR_RGB2GRAY)
            self.init_attrs()
            self.get_piece_pos(img)
            self.get_target_pos(img)
            self.get_start_pos(img)
            self.get_target_img(img)
            self.review_last_jump()
            # img_rgb.save("../tmp/origin.png")
            # self.mark_img(img_rgb)
            # img_rgb.save("../tmp/marked.png")
            self.jump()
            time.sleep(self.duration/5000+1.1)

if __name__ == '__main__':
    wj = WechatJump("48a666d9")
    wj.run()
