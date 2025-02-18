#!/usr/bin/env python
from __future__ import print_function
import cv2
import numpy as np
import datetime
import time

import rospy
import sys

from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError
from std_srvs.srv import Empty

def opencv_version():
    v = cv2.__version__.split('.')[0]
    if v == '2':
        return 2
    elif v == '3':
        return 3
    raise Exception('opencv version can not be parsed. v={}'.format(v))


class VideoFrames:
    def __init__(self, image_topic, target_x, target_y, target_w, target_h):
        self.image_sub = rospy.Subscriber(image_topic, Image, self.callback_image, queue_size=1)
        self.bridge = CvBridge()
        self.frames = []
        self.target_x, self.target_y, self.target_w, self.target_h = target_x, target_y, target_w, target_h

    def callback_image(self, data):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            rospy.logerr('[ros-video-recorder][VideoFrames] Converting Image Error. ' + str(e))
            return

        self.frames.append((time.time(), cv_image))

    def get_latest(self, at_time, remove_older=True):
        fs = [x for x in self.frames if x[0] <= at_time]
        if len(fs) == 0:
            return None

        f = fs[-1]
        if remove_older:
            self.frames = self.frames[len(fs) - 1:]

        return f[1]


class VideoRecorder:
    def __init__(self, output_width, output_height, output_fps, output_format, output_path, initial_start):
        self.frame_wrappers = []
        self.start_time = -1
        self.end_time = -1
        self.pub_img = None
        self.bridge = CvBridge()
        self.fps = output_fps
        self.interval = 1.0 / self.fps
        self.output_width = output_width
        self.output_height = output_height
        self.record_flag = initial_start

        if opencv_version() == 2:
            self.fourcc = cv2.cv.FOURCC(*output_format)
        elif opencv_version() == 3:
            self.fourcc = cv2.VideoWriter_fourcc(*output_format)
        else:
            raise

        self.output_path = output_path
        
    def add_subscription(self, subscription):
        self.frame_wrappers.append(subscription)

    def set_broadcast(self, publish_topic):
        if not publish_topic:
            self.pub_img = None
        else:
            self.pub_img = rospy.Publisher(publish_topic, Image, queue_size=1)

    def set_service(self):
        rospy.Service('~stop', Empty, self.stop_srv_cb)
        rospy.Service('~start', Empty, self.start_srv_cb)

    def record_spin(self):
        r = rospy.Rate(1)
        try:
            while not rospy.is_shutdown() and not self.record_flag:
                r.sleep()
                rospy.loginfo("[ros-video-recorder] Record waiting.")
        except KeyboardInterrupt:
            sys.exit()

        if self.output_path:
            self.output_file = self.output_path.replace('[timestamp]', datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
            self.video_writer = cv2.VideoWriter(self.output_file, self.fourcc, self.fps, (self.output_width, self.output_height))
            rospy.loginfo("[ros-video-recorder] Record Started. file={}".format(self.output_file))
        else:
            self.video_writer = None

        self.start_record()
        self.record_spin()

    def start_record(self):
        self.start_time = time.time()
        curr_time = self.start_time
        self.end_time = -1
        while (self.end_time < 0 or curr_time <= self.end_time) and self.record_flag:
            try:
                canvas = np.zeros((self.output_height, self.output_width, 3), np.uint8)

                for frame_w in self.frame_wrappers:
                    f = frame_w.get_latest(at_time=curr_time)
                    if f is None:
                        continue

                    resized = cv2.resize(f, (frame_w.target_w, frame_w.target_h))
                    canvas[frame_w.target_y:frame_w.target_y+frame_w.target_h, frame_w.target_x:frame_w.target_x+frame_w.target_w] = resized
                    # rospy.sleep(0.01)

                if self.video_writer:
                    self.video_writer.write(canvas)
                if self.pub_img:
                    try:
                        self.pub_img.publish(self.bridge.cv2_to_imgmsg(canvas, 'bgr8'))
                    except CvBridgeError as e:
                        rospy.logerr('cvbridgeerror, e={}'.format(str(e)))
                        pass
                rospy.sleep(0.01)

                if rospy.is_shutdown() and self.end_time < 0:
                    self.terminate()

                while curr_time + self.interval > time.time():
                    rospy.sleep(self.interval)

                curr_time += self.interval
            except KeyboardInterrupt:
                self.terminate()
                continue

        if self.video_writer:
            self.video_writer.release()


    def start_srv_cb(self, req):
        if self.record_flag:
            rospy.loginfo("[ros-video-recorder] Record already Started.")
        else:
            self.record_flag = True
        return []

    def stop_srv_cb(self, req):
        if self.record_flag:
            rospy.loginfo("[ros-video-recorder] Record Stopped.")
            self.terminate()
        else:
            rospy.loginfo("[ros-video-recorder] Record already Stopped.")
        return []

    def terminate(self):
        rospy.loginfo("[ros-video-recorder] Video Saved. file={}".format(self.output_file))
        #rospy.loginfo("[ros-video-recorder] Video Saved.")
        self.end_time = time.time()
        self.record_flag = False


if __name__ == '__main__':
    rospy.init_node('video_recorder', anonymous=True,disable_signals = True)

    # parameters
    output_width = int(rospy.get_param('~output_width', '640'))
    output_height = int(rospy.get_param('~output_height', '480'))
    output_fps = int(rospy.get_param('~output_fps', '30'))
    output_format = rospy.get_param('~output_format', 'xvid')
    output_topic = rospy.get_param('~output_topic', '')
    output_path = rospy.get_param('~output_path', '')
    initial_start = rospy.get_param('~initial_start', False)
    num_videos = int(rospy.get_param('~num_videos', '1000'))

    ft = VideoRecorder(output_width, output_height, output_fps, output_format, output_path, initial_start)

    # get parameters for videos and initialize subscriptions
    for idx in range(num_videos):
        source_info = rospy.get_param('~source%d' % (idx+1), '')
        if not source_info:
            break
        source_info_list = source_info.split(',')

        source_topic = source_info_list[0].strip()
        target_x = int(source_info_list[1])
        target_y = int(source_info_list[2])
        target_w = int(source_info_list[3])
        target_h = int(source_info_list[4])

        vf = VideoFrames(source_topic, target_x, target_y, target_w, target_h)
        ft.add_subscription(vf)

    if output_topic:
        ft.set_broadcast(output_topic)

    ft.set_service()

    try:
        ft.record_spin()
    except KeyboardInterrupt:
        rospy.logerr("[ros-video-recorder] Shutting down+")

    ft.terminate()

