# Copyright (C) 2024 Alif Semiconductor - All Rights Reserved.
# Use, distribution and modification of this code is permitted under the
# terms stated in the Alif Semiconductor Software License Agreement
#
# You should have received a copy of the Alif Semiconductor Software
# License Agreement with this file. If not, please write to:
# contact@alifsemi.com, or visit: https://alifsemi.com/license

cmake_minimum_required(VERSION 3.20.0)

set(CMAKE_POLICY_DEFAULT_CMP0123 NEW)

# Both images reserve the same SRAM0 region for the shared E7 trace sink.
if(BOARD STREQUAL "alif_e7_dk/ae722f80f55d5xx/rtss_he")
  list(APPEND EXTRA_DTC_OVERLAY_FILE
    "${CMAKE_CURRENT_SOURCE_DIR}/../trace-buffer-e7.overlay")
endif()

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(mhuv2)

option(TRACE_DEMO_RX_DELAY "Delay selected MHU0 channel-0 receive interrupts" OFF)
option(TRACE_DEMO_NO_WAIT "Compare acknowledged MHU writes with a merged no-wait burst" OFF)
if(TRACE_DEMO_RX_DELAY AND TRACE_DEMO_NO_WAIT)
	message(FATAL_ERROR "Enable only one trace demo at a time")
endif()
option(SE_SERVICES "Build SE services test case" ON)
if("${BOARD}" STREQUAL "alif_e7_dk_rtss_he")
	option(APSS_MHU0 "Build APSS (A32) MHU0 test case" OFF)
	option(APSS_MHU1 "Build APSS (A32) MHU1 test case" OFF)
endif()
option(RTSS_HP_MHU0 "Build RTSS-HP (CM55) MHU0 test case" OFF)
option(RTSS_HP_MHU1 "Build RTSS-HP (CM55) MHU1 test case" OFF)
if(APSS_MHU0)
	target_sources(app PRIVATE src/for_apss_mhu0.c)
elseif(APSS_MHU1)
	target_sources(app PRIVATE src/for_apss_mhu1.c)
elseif(RTSS_HP_MHU0)
	if(TRACE_DEMO_NO_WAIT)
		target_sources(app PRIVATE ../trace_no_wait.c)
		target_compile_definitions(app PRIVATE TRACE_DEMO_NO_WAIT=1 TRACE_DEMO_CORE_HP=0)
		include("${CMAKE_CURRENT_SOURCE_DIR}/../trace_no_wait_config.cmake")
		configure_ipm_no_wait_demo()
	else()
		target_sources(app PRIVATE src/for_rtss_hp_mhu0.c)
		include("${CMAKE_CURRENT_SOURCE_DIR}/../trace_demo_config.cmake")
		configure_ipm_trace_demo(HE)
	endif()
elseif(RTSS_HP_MHU1)
	target_sources(app PRIVATE src/for_rtss_hp_mhu1.c)
elseif(SE_SERVICES)
	target_sources(app PRIVATE src/se_service_test.c)
endif()
