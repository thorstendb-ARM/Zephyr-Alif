# Shared NoWait parameters keep both cores on the same round/control schedule.
function(configure_ipm_no_wait_demo)
  set(TRACE_DEMO_NO_WAIT_ROUNDS 10 CACHE STRING "Number of NoWait comparison rounds")
  set(TRACE_DEMO_NO_WAIT_ROUND 10 CACHE STRING "First round with two writes before completion")
  set(TRACE_DEMO_SECOND_NO_WAIT_ROUND 0 CACHE STRING "Second NoWait round; zero disables it")

  foreach(parameter IN ITEMS TRACE_DEMO_NO_WAIT_ROUNDS TRACE_DEMO_NO_WAIT_ROUND
      TRACE_DEMO_SECOND_NO_WAIT_ROUND)
    string(LENGTH "${${parameter}}" digits)
    if(NOT "${${parameter}}" MATCHES "^(0|[1-9][0-9]*)$" OR digits GREATER 10)
      message(FATAL_ERROR "${parameter} must be an unsigned decimal integer")
    endif()
  endforeach()
  if(TRACE_DEMO_NO_WAIT_ROUNDS LESS 1 OR TRACE_DEMO_NO_WAIT_ROUNDS GREATER 2147483647)
    message(FATAL_ERROR "TRACE_DEMO_NO_WAIT_ROUNDS must be between 1 and 2147483647")
  endif()
  if(TRACE_DEMO_NO_WAIT_ROUND LESS 1 OR TRACE_DEMO_NO_WAIT_ROUND GREATER TRACE_DEMO_NO_WAIT_ROUNDS)
    message(FATAL_ERROR "The first NoWait round must be within the configured rounds")
  endif()
  if(NOT TRACE_DEMO_SECOND_NO_WAIT_ROUND EQUAL 0)
    if(TRACE_DEMO_SECOND_NO_WAIT_ROUND GREATER TRACE_DEMO_NO_WAIT_ROUNDS
        OR TRACE_DEMO_SECOND_NO_WAIT_ROUND EQUAL TRACE_DEMO_NO_WAIT_ROUND)
      message(FATAL_ERROR "The second NoWait round must be distinct and within the configured rounds")
    endif()
  endif()
  target_compile_definitions(app PRIVATE
    TRACE_DEMO_NO_WAIT_ROUNDS=${TRACE_DEMO_NO_WAIT_ROUNDS}U
    TRACE_DEMO_NO_WAIT_ROUND=${TRACE_DEMO_NO_WAIT_ROUND}U
    TRACE_DEMO_SECOND_NO_WAIT_ROUND=${TRACE_DEMO_SECOND_NO_WAIT_ROUND}U)
endfunction()
