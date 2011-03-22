cmake_minimum_required(VERSION 2.4.6)
include($ENV{ROS_ROOT}/core/rosbuild/rosbuild.cmake)

rosbuild_init()

#set the default path for built executables to the "bin" directory
set(EXECUTABLE_OUTPUT_PATH ${PROJECT_SOURCE_DIR}/bin)
#set the default path for built libraries to the "lib" directory
set(LIBRARY_OUTPUT_PATH ${PROJECT_SOURCE_DIR}/lib)

rosbuild_find_ros_package(roslaunch)

execute_process(WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
  COMMAND sudo patch -p1 -N -l -d ${roslaunch_PACKAGE_PATH}/src/roslaunch -i ${PROJECT_SOURCE_DIR}/ros_dist_changes.patch
  RESULT_VARIABLE _patch_failed)

if(_patch_failed)
  message("Application of patch to ROS distribution failed")
endif(_patch_failed)

execute_process(WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
  COMMAND sudo cp ${PROJECT_SOURCE_DIR}/bin/rosmaster_sd $ENV{ROS_ROOT}/bin/
  RESULT_VARIABLE _cp_failed)

if(_cp_failed)
  message("Copy of rosmaster_sd script to ROS distribution failed")
endif(_cp_failed)
