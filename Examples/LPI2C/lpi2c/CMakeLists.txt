# Copyright (C) 2025 Alif Semiconductor - All Rights Reserved.
# Use, distribution and modification of this code is permitted under the
# terms stated in the Alif Semiconductor Software License Agreement
#
# You should have received a copy of the Alif Semiconductor Software
# License Agreement with this file. If not, please write to:
# contact@alifsemi.com, or visit: https://alifsemi.com/license

cmake_minimum_required(VERSION 3.20.0)

set(CMAKE_POLICY_DEFAULT_CMP0123 NEW)

# Keep the E7 trace sink's memory outside the application's SRAM0 allocation.
# The project-local pyOCD lifecycle uses this allocation for buffered trace.
if(BOARD STREQUAL "alif_e7_dk/ae722f80f55d5xx/rtss_he")
  list(APPEND EXTRA_DTC_OVERLAY_FILE
    "${CMAKE_CURRENT_SOURCE_DIR}/trace-buffer-e7.overlay")
endif()

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(lpi2c)

target_sources(app PRIVATE src/main.c)
