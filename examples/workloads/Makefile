CC ?= cc
CFLAGS ?= -O2 -g

all: hotspots

hotspots: hotspots.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f hotspots

.PHONY: all clean
