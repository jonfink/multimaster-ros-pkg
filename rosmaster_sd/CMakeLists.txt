cmake_minimum_required(VERSION 2.4.6)
include($ENV{ROS_ROOT}/core/rosbuild/rosbuild.cmake)

rosbuild_init()

#set the default path for built executables to the "bin" directory
set(EXECUTABLE_OUTPUT_PATH ${PROJECT_SOURCE_DIR}/bin)
#set the default path for built libraries to the "lib" directory
set(LIBRARY_OUTPUT_PATH ${PROJECT_SOURCE_DIR}/lib)

rosbuild_find_ros_package(roslaunch)

execute_process(WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
  COMMAND patch --dry-run -p7 -d ${roslaunch_PACKAGE_PATH} -i ${PROJECT_SOURCE_DIR}/ros_dist_changes.patch
  RESULT_VARIABLE _patch_failed)

if(_patch_failed)
  message("Great! ROS distribution has already been patched")
else (_patch_failed)
  message(FATAL_ERROR "Need to patch ROS distribution for rosmaster_sd (roscd rosmaster_sd && sh update_ros_dist.sh)")
endif(_patch_failed)