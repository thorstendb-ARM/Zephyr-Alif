/* Copyright (C) 2024 Alif Semiconductor - All Rights Reserved.
 * Use, distribution and modification of this code is permitted under the
 * terms stated in the Alif Semiconductor Software License Agreement
 *
 * You should have received a copy of the Alif Semiconductor Software
 * License Agreement with this file. If not, please write to:
 * contact@alifsemi.com, or visit: https://alifsemi.com/license
 *
 */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/drivers/ipm.h>

#ifndef TRACE_DEMO_ITERATIONS
#define TRACE_DEMO_ITERATIONS 10
#endif
#if defined(TRACE_DEMO_RX_DELAY) && TRACE_DEMO_RX_DELAY
#ifndef TRACE_DEMO_DELAY_ROUND
#define TRACE_DEMO_DELAY_ROUND 5U
#endif
#ifndef TRACE_DEMO_DELAY_US
#define TRACE_DEMO_DELAY_US 50000U
#endif
#ifndef TRACE_DEMO_SECOND_DELAY_ROUND
#define TRACE_DEMO_SECOND_DELAY_ROUND 0U
#endif
#ifndef TRACE_DEMO_SECOND_DELAY_US
#define TRACE_DEMO_SECOND_DELAY_US 0U
#endif
#endif
const struct device *mhu0_r;
const struct device *mhu0_s;

static volatile bool msg_sent;
static volatile bool msg_received;
static uint32_t tx_msg;
#if defined(TRACE_DEMO_RX_DELAY) && TRACE_DEMO_RX_DELAY
static uint32_t ch0_rx_count;
#endif

static void recv_cb(const struct device *mhuv2_ipmdev, void *user_data,
		uint32_t id, volatile void *data)
{
	ARG_UNUSED(mhuv2_ipmdev);
	ARG_UNUSED(user_data);

#if defined(TRACE_DEMO_RX_DELAY) && TRACE_DEMO_RX_DELAY
	if (id == 0U && ch0_rx_count < TRACE_DEMO_ITERATIONS) {
		uint32_t delay_us = 0U;

		++ch0_rx_count;
		if (ch0_rx_count == TRACE_DEMO_DELAY_ROUND) {
			delay_us = TRACE_DEMO_DELAY_US;
		} else if (ch0_rx_count == TRACE_DEMO_SECOND_DELAY_ROUND) {
			delay_us = TRACE_DEMO_SECOND_DELAY_US;
		}
		if (delay_us != 0U) {
			/* Deliberately slow the selected RX ISR. The driver writes
			 * CH_CLR only after this callback returns, delaying the
			 * sender's completion as well. Do not sleep in an ISR.
			 */
			k_busy_wait(delay_us);
		}
	}
#endif

	printk("RTSS-HE: MSG rcvd on ch:%d is 0x%x\n", id, *((uint32_t *)data));
	msg_received = true;
}

static void send_cb(const struct device *mhuv2_ipmdev, void *user_data,
		uint32_t id, volatile void *data)
{
	ARG_UNUSED(mhuv2_ipmdev);
	ARG_UNUSED(user_data);
	ARG_UNUSED(data);

	printk("RTSS-HE: MSG sent on Ch:%d is 0x%x\n", id, tx_msg);
	msg_sent = true;
}

static void send(void)
{
	int wait = 0;
	int size = 4;

	msg_received = false;
	msg_sent     = false;
	tx_msg       = 0xADDEDACE;

	ipm_send(mhu0_s, wait, 0, &tx_msg, size);
	while (!msg_sent)
		;
	msg_sent     = false;
	tx_msg       = 0xBEADBEAD;
	ipm_send(mhu0_s, wait, 1, &tx_msg, size);
	while (!msg_sent)
		;
	msg_sent = false;
}

int main(void)
{
	uint32_t recv_data;
	int i = 0;

	msg_received = false;
	msg_sent = false;
	printk("RTSS-HE RTSS-HP MHU 0 example on %s\n", CONFIG_BOARD);
	mhu0_r = DEVICE_DT_GET(DT_NODELABEL(rtsshp_rtsshe_mhu0_r));
	mhu0_s = DEVICE_DT_GET(DT_NODELABEL(rtsshe_rtsshp_mhu0_s));
	if (!device_is_ready(mhu0_r) || !device_is_ready(mhu0_s)) {
		printk("MHU devices not ready\n");
		return -1;
	}
	ipm_register_callback(mhu0_r, recv_cb, &recv_data);
	ipm_register_callback(mhu0_s, send_cb, NULL);

	/* Enable Rx MHU interrupt */
	ipm_set_enabled(mhu0_r, true);

	while (i < TRACE_DEMO_ITERATIONS) {
		while (!msg_received)
			;
		send();
		++i;
	}
	/* Disable Rx MHU interrupt */
	ipm_set_enabled(mhu0_r, false);

	return 0;
}
