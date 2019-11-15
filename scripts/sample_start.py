#!/usr/bin/env python

import rospy
from std_srvs.srv import Empty

def record_start():
    rospy.wait_for_service('video_recorder/start')
    try:
        service = rospy.ServiceProxy('video_recorder/start',Empty)
        responce = service()
    except rospy.ServiceException, e:
        rospy.logerr("[ros-video-recorder] Service call failed")

if __name__ == "__main__":
    record_start()

