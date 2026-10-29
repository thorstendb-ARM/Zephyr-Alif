/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <zephyr/drivers/ipm.h>
#include <zephyr/sys/sys_io.h>
#include <cmsis_core.h>

#if !defined(TRACE_DEMO_NO_WAIT) || !TRACE_DEMO_NO_WAIT
#error "This source is only for the no-wait trace demo"
#endif
#ifndef TRACE_DEMO_CORE_HP
#error "Select the HP or HE role with TRACE_DEMO_CORE_HP"
#endif

#define TRACE_WORD_FIRST       0x11111111U
#define TRACE_WORD_SECOND      0x22222222U
#define TRACE_WORD_MERGED      (TRACE_WORD_FIRST | TRACE_WORD_SECOND)
#define TRACE_START_BASELINE   0xB0000001U
#define TRACE_BASELINE_DONE    0xB0000002U
#define TRACE_START_NO_WAIT    0xF0000001U
#define TRACE_BURST_DONE       0xF0000002U
#define TRACE_VERIFIED_DONE    0xF0000003U
#define TRACE_TIMEOUT_MS      1000U
#if !defined(TRACE_DEMO_NO_WAIT_ROUNDS) || !defined(TRACE_DEMO_NO_WAIT_ROUND) || \
	!defined(TRACE_DEMO_SECOND_NO_WAIT_ROUND)
#error "Configure the NoWait round schedule for both cores"
#endif

#if TRACE_DEMO_CORE_HP
#define TRACE_RX_NODE DT_ALIAS(rtsshemhu0r)
#define TRACE_TX_NODE DT_ALIAS(rtsshemhu0s)
/* MHUv2 receiver channels have a 0x20-byte stride and CH_ST at offset 0.
 * Poll only control channel 1; the unmodified driver's ISR reads channel 0.
 */
#define TRACE_CONTROL_STATUS (DT_REG_ADDR(TRACE_RX_NODE) + 0x20U)
#else
#define TRACE_RX_NODE DT_NODELABEL(rtsshp_rtsshe_mhu0_r)
#define TRACE_TX_NODE DT_NODELABEL(rtsshe_rtsshp_mhu0_s)
#endif

enum trace_phase {
	TRACE_PHASE_INIT = 0,
	TRACE_PHASE_READY = 1,
	TRACE_PHASE_BASELINE = 2,
	TRACE_PHASE_BASELINE_DONE = 3,
	TRACE_PHASE_NO_WAIT = 4,
	TRACE_PHASE_BURST_WRITTEN = 5,
	TRACE_PHASE_RX_RELEASED = 6,
	TRACE_PHASE_COMPLETE = 7,
	TRACE_PHASE_FAILED = 255,
};

enum trace_result {
	TRACE_RESULT_RUNNING = 0,
	TRACE_RESULT_PASS = 1,
	TRACE_ERROR_DEVICE = 0x101,
	TRACE_ERROR_SEND = 0x102,
	TRACE_ERROR_RX_ENABLE = 0x103,
	TRACE_ERROR_CALLBACK = 0x104,
	TRACE_ERROR_ACK_TIMEOUT = 0x105,
	TRACE_ERROR_CONTROL = 0x106,
	TRACE_ERROR_DATA = 0x107,
	TRACE_ERROR_RX_TIMEOUT = 0x108,
	TRACE_ERROR_BURST_TIMEOUT = 0x109,
	TRACE_ERROR_ACK_COUNT = 0x10A,
};

/* Each image owns separate instances. Keep names stable for DWT and the
 * debugger; control messages use channel 1, payloads always use channel 0.
 */
volatile uint32_t trace_demo_phase = TRACE_PHASE_INIT;
volatile uint32_t trace_demo_result = TRACE_RESULT_RUNNING;
volatile uint32_t trace_demo_round;
volatile uint32_t trace_demo_completed_rounds;
volatile int32_t trace_demo_api_error;
volatile uint32_t trace_callback_error;
volatile uint32_t trace_tx_ack_count;
volatile uint32_t trace_control_tx_ack_count;
volatile uint32_t trace_control_rx_count;
volatile uint32_t trace_control_rx_value;

#if TRACE_DEMO_CORE_HP
volatile uint32_t trace_rx_count;
volatile uint32_t trace_round_rx_count;
volatile uint32_t trace_last_rx_value;
volatile uint32_t trace_baseline_rx_count;
volatile uint32_t trace_baseline_rx_first;
volatile uint32_t trace_baseline_rx_second;
volatile uint32_t trace_fault_rx_count;
volatile uint32_t trace_fault_rx_value;
#endif

static const struct device *const mhu_rx = DEVICE_DT_GET(TRACE_RX_NODE);
static const struct device *const mhu_tx = DEVICE_DT_GET(TRACE_TX_NODE);

static bool trace_is_no_wait_round(uint32_t round)
{
	return round == TRACE_DEMO_NO_WAIT_ROUND ||
	       round == TRACE_DEMO_SECOND_NO_WAIT_ROUND;
}

static __attribute__((noinline, noreturn)) void trace_demo_stop(void)
{
#if TRACE_DEMO_CORE_HP
	/* Stop from thread context so the receive ISR has already cleared every
	 * delivered channel. A CMSIS Debugger pause then saves the trace buffer.
	 */
	if ((CoreDebug->DHCSR & CoreDebug_DHCSR_C_DEBUGEN_Msk) != 0U) {
		__BKPT(0);
	}
#endif
	for (;;) {
		k_sleep(K_FOREVER);
	}
}

static __attribute__((noreturn)) void trace_fail(enum trace_result result)
{
	trace_demo_result = result;
	trace_demo_phase = TRACE_PHASE_FAILED;
	trace_demo_stop();
}

static void trace_check_callback(void)
{
	if (trace_callback_error != 0U) {
		trace_fail(TRACE_ERROR_CALLBACK);
	}
}

static void trace_wait_count(volatile uint32_t *counter, uint32_t expected,
			     enum trace_result timeout_result)
{
	uint32_t started_at = k_uptime_get_32();

	while (*counter < expected) {
		trace_check_callback();
		if ((k_uptime_get_32() - started_at) >= TRACE_TIMEOUT_MS) {
			trace_fail(timeout_result);
		}
		k_sleep(K_MSEC(1));
	}
	trace_check_callback();
}

static void trace_wait_control(uint32_t expected_count, uint32_t expected_value)
{
	trace_wait_count(&trace_control_rx_count, expected_count, TRACE_ERROR_RX_TIMEOUT);
	if (trace_control_rx_count != expected_count ||
	    trace_control_rx_value != expected_value) {
		trace_fail(TRACE_ERROR_CONTROL);
	}
}

static void trace_send(uint32_t channel, uint32_t value)
{
	int ret = ipm_send(mhu_tx, 0, channel, &value, sizeof(value));

	if (ret != 0) {
		trace_demo_api_error = ret;
		trace_fail(TRACE_ERROR_SEND);
	}
}

static void trace_enable_rx(bool enable)
{
	int ret = ipm_set_enabled(mhu_rx, enable);

	if (ret != 0) {
		trace_demo_api_error = ret;
		trace_fail(TRACE_ERROR_RX_ENABLE);
	}
}

static void trace_recv_cb(const struct device *dev, void *user_data,
			  uint32_t channel, volatile void *data)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(user_data);

	if (data == NULL) {
		trace_callback_error = 1U;
		return;
	}
	uint32_t value = *(const volatile uint32_t *)data;

	if (channel == 1U) {
		trace_control_rx_value = value;
		++trace_control_rx_count;
		return;
	}
#if TRACE_DEMO_CORE_HP
	if (channel == 0U) {
		trace_last_rx_value = value;
		if (trace_demo_phase == TRACE_PHASE_BASELINE) {
			if (trace_round_rx_count == 0U) {
				trace_baseline_rx_first = value;
			} else {
				trace_baseline_rx_second = value;
			}
			uint32_t expected = trace_round_rx_count == 0U ?
				TRACE_WORD_FIRST : TRACE_WORD_SECOND;

			if (value != expected ||
			    trace_round_rx_count >= 2U) {
				trace_callback_error = 2U;
			}
			++trace_baseline_rx_count;
		} else if (trace_demo_phase == TRACE_PHASE_RX_RELEASED) {
			trace_fault_rx_value = value;
			if (value != TRACE_WORD_MERGED || trace_round_rx_count != 0U) {
				trace_callback_error = 2U;
			}
			++trace_fault_rx_count;
		} else {
			trace_callback_error = 3U;
		}
		++trace_round_rx_count;
		++trace_rx_count;
		return;
	}
#endif
	trace_callback_error = 4U;
}

static void trace_send_cb(const struct device *dev, void *user_data,
			  uint32_t channel, volatile void *data)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(user_data);
	ARG_UNUSED(data);

	if (channel == 0U) {
		++trace_tx_ack_count;
	} else if (channel == 1U) {
		++trace_control_tx_ack_count;
	} else {
		trace_callback_error = 5U;
	}
}

#if TRACE_DEMO_CORE_HP
static void trace_run_hp(void)
{
	uint32_t expected_control_replies = 0U;
	uint32_t expected_baseline_reads = 0U;
	uint32_t expected_fault_reads = 0U;

	/* HE is allowed to wait at READY while the debugger stops HP at main. */
	k_sleep(K_MSEC(500));
	for (uint32_t round = 1U; round <= TRACE_DEMO_NO_WAIT_ROUNDS; ++round) {
		trace_demo_round = round;
		trace_round_rx_count = 0U;
		if (!trace_is_no_wait_round(round)) {
			trace_demo_phase = TRACE_PHASE_BASELINE;
			trace_send(1U, TRACE_START_BASELINE);
			trace_wait_control(++expected_control_replies, TRACE_BASELINE_DONE);
			trace_wait_count(&trace_control_tx_ack_count, round, TRACE_ERROR_ACK_TIMEOUT);
			expected_baseline_reads += 2U;
			if (trace_round_rx_count != 2U ||
			    trace_baseline_rx_count != expected_baseline_reads ||
			    trace_baseline_rx_first != TRACE_WORD_FIRST ||
			    trace_baseline_rx_second != TRACE_WORD_SECOND) {
				trace_fail(TRACE_ERROR_DATA);
			}
			trace_demo_phase = TRACE_PHASE_BASELINE_DONE;
		} else {
			/* Block consumption before HE writes either word. The control
			 * token is polled while the receive ISR is disabled.
			 */
			trace_enable_rx(false);
			trace_demo_phase = TRACE_PHASE_NO_WAIT;
			trace_send(1U, TRACE_START_NO_WAIT);
			uint32_t started_at = k_uptime_get_32();

			while (sys_read32(TRACE_CONTROL_STATUS) != TRACE_BURST_DONE) {
				trace_check_callback();
				if ((k_uptime_get_32() - started_at) >= TRACE_TIMEOUT_MS) {
					trace_fail(TRACE_ERROR_BURST_TIMEOUT);
				}
				k_sleep(K_MSEC(1));
			}
			/* BURST_DONE follows both payload writes. Channel 0 is still
			 * unread, so its first driver read sees the combined bits.
			 */
			trace_demo_phase = TRACE_PHASE_RX_RELEASED;
			trace_enable_rx(true);
			expected_control_replies += 2U;
			trace_wait_control(expected_control_replies, TRACE_VERIFIED_DONE);
			trace_wait_count(&trace_control_tx_ack_count, round, TRACE_ERROR_ACK_TIMEOUT);
			++expected_fault_reads;
			if (trace_round_rx_count != 1U ||
			    trace_fault_rx_count != expected_fault_reads ||
			    trace_fault_rx_value != TRACE_WORD_MERGED) {
				trace_fail(TRACE_ERROR_DATA);
			}
		}
		if (trace_rx_count != expected_baseline_reads + expected_fault_reads) {
			trace_fail(TRACE_ERROR_DATA);
		}
		trace_demo_completed_rounds = round;
	}
	trace_demo_result = TRACE_RESULT_PASS;
	trace_demo_phase = TRACE_PHASE_COMPLETE;
	trace_demo_stop();
}
#else
static void trace_run_he(void)
{
	uint32_t expected_payload_acks = 0U;
	uint32_t expected_control_acks = 0U;

	/* There is no timeout before the first command: HP may be stopped at
	 * main in the debugger. Every wait in an active trial is bounded.
	 */
	while (trace_control_rx_count == 0U) {
		trace_check_callback();
		k_sleep(K_MSEC(1));
	}
	for (uint32_t round = 1U; round <= TRACE_DEMO_NO_WAIT_ROUNDS; ++round) {
		bool no_wait = trace_is_no_wait_round(round);

		trace_wait_control(round, no_wait ? TRACE_START_NO_WAIT : TRACE_START_BASELINE);
		trace_demo_round = round;
		trace_demo_phase = no_wait ? TRACE_PHASE_NO_WAIT : TRACE_PHASE_BASELINE;
		trace_send(0U, TRACE_WORD_FIRST);
		if (!no_wait) {
			trace_wait_count(&trace_tx_ack_count, ++expected_payload_acks,
					 TRACE_ERROR_ACK_TIMEOUT);
		}
		/* Fault rounds deliberately reuse channel 0 before completion. */
		trace_send(0U, TRACE_WORD_SECOND);
		if (no_wait) {
			__DSB();
			trace_demo_phase = TRACE_PHASE_BURST_WRITTEN;
			trace_send(1U, TRACE_BURST_DONE);
			trace_wait_count(&trace_control_tx_ack_count, ++expected_control_acks,
					 TRACE_ERROR_ACK_TIMEOUT);
		}
		trace_wait_count(&trace_tx_ack_count, ++expected_payload_acks,
				 TRACE_ERROR_ACK_TIMEOUT);
		if (trace_tx_ack_count != expected_payload_acks ||
		    trace_control_tx_ack_count != expected_control_acks) {
			trace_fail(TRACE_ERROR_ACK_COUNT);
		}
		trace_demo_completed_rounds = round;
		if (!no_wait) {
			trace_demo_phase = TRACE_PHASE_BASELINE_DONE;
		}
		/* Publish the final result before HP receives its final reply and
		 * stops both cores via the debugger. Intermediate replies are fully
		 * acknowledged before this control channel is used in another round.
		 */
		if (round == TRACE_DEMO_NO_WAIT_ROUNDS) {
			trace_demo_result = TRACE_RESULT_PASS;
			trace_demo_phase = TRACE_PHASE_COMPLETE;
		}
		trace_send(1U, no_wait ? TRACE_VERIFIED_DONE : TRACE_BASELINE_DONE);
		++expected_control_acks;
		if (round != TRACE_DEMO_NO_WAIT_ROUNDS) {
			trace_wait_count(&trace_control_tx_ack_count, expected_control_acks,
					 TRACE_ERROR_ACK_TIMEOUT);
		}
	}
}
#endif

int main(void)
{
	if (!device_is_ready(mhu_rx) || !device_is_ready(mhu_tx)) {
		trace_fail(TRACE_ERROR_DEVICE);
	}
	ipm_register_callback(mhu_rx, trace_recv_cb, NULL);
	ipm_register_callback(mhu_tx, trace_send_cb, NULL);
	trace_enable_rx(true);
	trace_demo_phase = TRACE_PHASE_READY;
#if TRACE_DEMO_CORE_HP
	trace_run_hp();
#else
	trace_run_he();
#endif
	return 0;
}
