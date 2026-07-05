/*
 * Proteo Phase-0 spike client.
 *
 * Opens an available EVDI device, connects it with the EDID blob given on the
 * command line (making a virtual DRM connector appear), then keeps the device
 * alive and periodically grabs pixels from the compositor-rendered framebuffer.
 *
 * The pixel grab is the decision-gate proof: non-zero pixels arriving here mean
 * KWin genuinely adopted the virtual output and renders into it.
 *
 * Build: gcc -Wall -O2 -o evdi_client evdi_client.c -levdi
 * Usage: ./evdi_client EDID_FILE
 * Stop:  Ctrl-C / SIGTERM — disconnects cleanly, the connector disappears.
 */

#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <evdi_lib.h>

#define BUFFER_ID 0
#define MAX_RECTS 16
#define MAX_DRM_CARDS 32

static volatile sig_atomic_t g_stop;

static void on_signal(int sig)
{
	(void)sig;
	g_stop = 1;
}

struct state {
	evdi_handle h;
	struct evdi_mode mode;
	uint8_t *fb;
	int have_mode;
	int registered;
	int awaiting_update;
	long frames_grabbed;
};

static void register_fb(struct state *s)
{
	if (s->registered) {
		evdi_unregister_buffer(s->h, BUFFER_ID);
		free(s->fb);
		s->fb = NULL;
		s->registered = 0;
	}
	int stride = s->mode.width * 4;
	s->fb = calloc((size_t)stride, (size_t)s->mode.height);
	if (!s->fb) {
		fprintf(stderr, "out of memory for %dx%d framebuffer\n",
			s->mode.width, s->mode.height);
		exit(1);
	}
	struct evdi_buffer buf = {
		.id = BUFFER_ID,
		.buffer = s->fb,
		.width = s->mode.width,
		.height = s->mode.height,
		.stride = stride,
	};
	evdi_register_buffer(s->h, buf);
	s->registered = 1;
	s->awaiting_update = 0;
}

static void grab_and_report(struct state *s)
{
	struct evdi_rect rects[MAX_RECTS];
	int n = MAX_RECTS;

	evdi_grab_pixels(s->h, rects, &n);

	size_t nonzero = 0;
	size_t total = (size_t)s->mode.width * 4 * (size_t)s->mode.height;
	for (size_t i = 0; i < total; i++)
		nonzero += (s->fb[i] != 0);

	s->frames_grabbed++;
	if (s->frames_grabbed <= 3 || s->frames_grabbed % 60 == 0)
		printf("[grab #%ld] %dx%d, %d dirty rect(s), "
		       "%zu/%zu non-zero bytes %s\n",
		       s->frames_grabbed, s->mode.width, s->mode.height, n,
		       nonzero, total,
		       nonzero ? "<< COMPOSITOR IS RENDERING" : "(all black)");
	fflush(stdout);
}

static void mode_changed_handler(struct evdi_mode mode, void *ud)
{
	struct state *s = ud;

	printf("[evdi] mode_changed: %dx%d@%d bpp=%d pixel_format=0x%08x\n",
	       mode.width, mode.height, mode.refresh_rate,
	       mode.bits_per_pixel, mode.pixel_format);
	fflush(stdout);
	s->mode = mode;
	s->have_mode = 1;
	register_fb(s);
}

static void dpms_handler(int dpms_mode, void *ud)
{
	(void)ud;
	printf("[evdi] dpms: %d\n", dpms_mode);
	fflush(stdout);
}

static void crtc_state_handler(int state, void *ud)
{
	(void)ud;
	printf("[evdi] crtc_state: %d\n", state);
	fflush(stdout);
}

static void update_ready_handler(int buffer, void *ud)
{
	struct state *s = ud;

	if (buffer == BUFFER_ID && s->registered) {
		s->awaiting_update = 0;
		grab_and_report(s);
	}
}

static int find_available_device(void)
{
	for (int i = 0; i < MAX_DRM_CARDS; i++)
		if (evdi_check_device(i) == AVAILABLE)
			return i;
	return -1;
}

int main(int argc, char **argv)
{
	if (argc != 2) {
		fprintf(stderr, "usage: %s EDID_FILE\n", argv[0]);
		return 2;
	}

	unsigned char edid[512];
	FILE *f = fopen(argv[1], "rb");
	if (!f) {
		perror(argv[1]);
		return 1;
	}
	size_t edid_len = fread(edid, 1, sizeof(edid), f);
	fclose(f);
	if (edid_len < 128 || edid_len % 128 != 0) {
		fprintf(stderr, "bad EDID size: %zu\n", edid_len);
		return 1;
	}

	int card = find_available_device();
	if (card < 0) {
		fprintf(stderr,
			"no AVAILABLE evdi device; is the module loaded?\n"
			"  sudo modprobe evdi initial_device_count=1\n");
		return 1;
	}
	printf("[evdi] using /dev/dri/card%d\n", card);

	struct state s = { 0 };
	s.h = evdi_open(card);
	if (s.h == EVDI_INVALID_HANDLE) {
		fprintf(stderr, "evdi_open(card%d) failed: %s\n", card,
			strerror(errno));
		return 1;
	}

	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);

	/* generous pixel-area limit: up to 4K */
	evdi_connect(s.h, edid, (unsigned int)edid_len, 4096u * 2160u);
	printf("[evdi] connected with %zu-byte EDID; virtual connector should "
	       "now appear (watch kscreen-doctor -o)\n", edid_len);
	fflush(stdout);

	struct evdi_event_context ctx = {
		.dpms_handler = dpms_handler,
		.mode_changed_handler = mode_changed_handler,
		.update_ready_handler = update_ready_handler,
		.crtc_state_handler = crtc_state_handler,
		.user_data = &s,
	};

	struct pollfd pfd = {
		.fd = evdi_get_event_ready(s.h),
		.events = POLLIN,
	};
	time_t last_request = 0;

	while (!g_stop) {
		int r = poll(&pfd, 1, 500);
		if (r < 0 && errno != EINTR)
			break;
		if (r > 0 && (pfd.revents & POLLIN))
			evdi_handle_events(s.h, &ctx);

		time_t now = time(NULL);
		if (s.registered && !s.awaiting_update &&
		    now != last_request) {
			last_request = now;
			if (evdi_request_update(s.h, BUFFER_ID))
				grab_and_report(&s);
			else
				s.awaiting_update = 1;
		}
	}

	printf("[evdi] disconnecting\n");
	evdi_disconnect(s.h);
	evdi_close(s.h);
	free(s.fb);
	return 0;
}
