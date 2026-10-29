# Shared parameters for the acknowledged MHU0 exchange; NoWait uses its own app.
function(configure_ipm_trace_demo core)
  set(TRACE_DEMO_ITERATIONS 10 CACHE STRING "Number of acknowledged MHU0 exchange rounds")
  set(TRACE_DEMO_DELAY_ROUND 5 CACHE STRING "HE channel-0 receive occurrence to delay")
  set(TRACE_DEMO_DELAY_US 50000 CACHE STRING "First HE receive delay in microseconds")
  set(TRACE_DEMO_SECOND_DELAY_ROUND 0 CACHE STRING "Second HE receive occurrence; zero disables it")
  set(TRACE_DEMO_SECOND_DELAY_US 0 CACHE STRING "Second HE receive delay in microseconds")

  foreach(parameter IN ITEMS TRACE_DEMO_ITERATIONS TRACE_DEMO_DELAY_ROUND
      TRACE_DEMO_DELAY_US TRACE_DEMO_SECOND_DELAY_ROUND TRACE_DEMO_SECOND_DELAY_US)
    string(LENGTH "${${parameter}}" digits)
    if(NOT "${${parameter}}" MATCHES "^(0|[1-9][0-9]*)$" OR digits GREATER 10)
      message(FATAL_ERROR "${parameter} must be an unsigned decimal integer")
    endif()
  endforeach()
  if(TRACE_DEMO_ITERATIONS LESS 1 OR TRACE_DEMO_ITERATIONS GREATER 2147483647)
    message(FATAL_ERROR "TRACE_DEMO_ITERATIONS must be between 1 and 2147483647")
  endif()
  target_compile_definitions(app PRIVATE TRACE_DEMO_ITERATIONS=${TRACE_DEMO_ITERATIONS})

  if(TRACE_DEMO_RX_DELAY)
    if(TRACE_DEMO_DELAY_ROUND LESS 1 OR TRACE_DEMO_DELAY_ROUND GREATER TRACE_DEMO_ITERATIONS
        OR TRACE_DEMO_DELAY_US LESS 1 OR TRACE_DEMO_DELAY_US GREATER 4294967295)
      message(FATAL_ERROR "The first delay needs a valid receive occurrence and positive uint32 microseconds")
    endif()
    if(TRACE_DEMO_SECOND_DELAY_ROUND EQUAL 0)
      if(NOT TRACE_DEMO_SECOND_DELAY_US EQUAL 0)
        message(FATAL_ERROR "A disabled second delay must have zero microseconds")
      endif()
    elseif(TRACE_DEMO_SECOND_DELAY_ROUND GREATER TRACE_DEMO_ITERATIONS
        OR TRACE_DEMO_SECOND_DELAY_ROUND EQUAL TRACE_DEMO_DELAY_ROUND
        OR TRACE_DEMO_SECOND_DELAY_US LESS 1 OR TRACE_DEMO_SECOND_DELAY_US GREATER 4294967295)
      message(FATAL_ERROR "The second delay needs a distinct valid occurrence and positive uint32 microseconds")
    endif()
    if(core STREQUAL "HE")
      target_compile_definitions(app PRIVATE TRACE_DEMO_RX_DELAY=1
        TRACE_DEMO_DELAY_ROUND=${TRACE_DEMO_DELAY_ROUND}U
        TRACE_DEMO_DELAY_US=${TRACE_DEMO_DELAY_US}U
        TRACE_DEMO_SECOND_DELAY_ROUND=${TRACE_DEMO_SECOND_DELAY_ROUND}U
        TRACE_DEMO_SECOND_DELAY_US=${TRACE_DEMO_SECOND_DELAY_US}U)
    endif()
  endif()
endfunction()
