#!/bin/sh

echo "About to patch ROS distribution (will need sudo access)"
cat ros_dist_changes.patch | sudo patch -N -p7 -d `rospack find roslaunch`

echo "About to copy rosmaster_sd script to $ROS_ROOT/bin (will need sudo access)"
sudo cp bin/rosmaster_sd $ROS_ROOT/bin/

